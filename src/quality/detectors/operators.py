"""通用行级算子。字段名、枚举和阈值都由规则参数传入。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from quality.timing import parse_time, partition_matches

Outcome = Literal["pass", "fail", "unknown", "skip"]

_LABEL = re.compile(r"^[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?$", re.IGNORECASE)


@dataclass
class EvalContext:
    now: datetime
    seen: dict[str, set[str]] = field(default_factory=dict)
    partial: dict[str, bool] = field(default_factory=dict)
    max_fingerprints: int = 10000


def evaluate(operator: str, row: dict[str, Any], params: dict[str, Any], ctx: EvalContext) -> Outcome:
    function = OPERATORS.get(operator)
    if function is None:
        raise KeyError(f"未知质检算子: {operator}")
    return function(row, params, ctx)


def field_empty(row: dict[str, Any], params: dict[str, Any], ctx: EvalContext) -> Outcome:
    del ctx
    return "fail" if _blank(row.get(params.get("field"))) else "pass"


def validate_ip(row: dict[str, Any], params: dict[str, Any], ctx: EvalContext) -> Outcome:
    del ctx
    value = row.get(params.get("field"))
    if _blank(value):
        return "skip"
    allowed = set(params.get("allowed_formats") or ["ipv4"])
    text = str(value).strip()
    if "ipv4" in allowed and _ipv4(text):
        return "pass"
    if "ipv6" in allowed and _ipv6(text):
        return "pass"
    if "ipv4_integer" in allowed and _ipv4_integer(text):
        return "pass"
    return "fail"


def validate_domain(row: dict[str, Any], params: dict[str, Any], ctx: EvalContext) -> Outcome:
    del ctx
    value = row.get(params.get("field"))
    if _blank(value):
        return "skip"
    return "pass" if _domain(str(value).strip()) else "fail"


def validate_time(row: dict[str, Any], params: dict[str, Any], ctx: EvalContext) -> Outcome:
    del ctx
    value = row.get(params.get("field"))
    if _blank(value):
        return "skip"
    parsed = parse_time(value, list(params.get("formats") or ["iso8601"]), str(params.get("timezone") or "Asia/Shanghai"))
    return "pass" if parsed is not None else "fail"


def validate_enum(row: dict[str, Any], params: dict[str, Any], ctx: EvalContext) -> Outcome:
    del ctx
    value = row.get(params.get("field"))
    if _blank(value):
        return "skip"
    known = {str(item).strip().lower() for item in params.get("values") or []}
    if str(value).strip().lower() in known:
        return "pass"
    return "fail" if params.get("fail_unknown") else "unknown"


def validate_number(row: dict[str, Any], params: dict[str, Any], ctx: EvalContext) -> Outcome:
    del ctx
    value = row.get(params.get("field"))
    if _blank(value):
        return "skip"
    try:
        number = float(str(value).strip())
    except ValueError:
        return "fail"
    if params.get("integer") and not number.is_integer():
        return "fail"
    if "min" in params and number < float(params["min"]):
        return "fail"
    if "max" in params and number > float(params["max"]):
        return "fail"
    return "pass"


def validate_dns_rdata(row: dict[str, Any], params: dict[str, Any], ctx: EvalContext) -> Outcome:
    """按应答类型检查应答值。类型映射来自规则，不写死在引擎里。"""

    del ctx
    record_type = row.get(params.get("type_field"))
    value = row.get(params.get("value_field"))
    if _blank(record_type) or _blank(value):
        return "skip"
    mapping = {str(key).upper(): kind for key, kind in (params.get("mapping") or {}).items()}
    kind = mapping.get(str(record_type).strip().upper())
    if kind is None:
        return "unknown"
    return "pass" if _matches(str(value).strip(), kind) else "fail"


def type_relation(row: dict[str, Any], params: dict[str, Any], ctx: EvalContext) -> Outcome:
    del ctx
    query = row.get(params.get("query_field"))
    answer = row.get(params.get("answer_field"))
    if _blank(query) or _blank(answer):
        return "skip"
    query_name = str(query).strip().upper()
    answer_name = str(answer).strip().upper()
    compatible = {str(key).upper(): [str(item).upper() for item in values] for key, values in (params.get("compatible") or {}).items()}
    allowed = set(compatible.get(query_name) or compatible.get("*") or [])
    allowed.add(query_name)
    if answer_name in allowed:
        return "pass"
    known = {name for names in compatible.values() for name in names}
    known.update(compatible)
    return "unknown" if answer_name not in known and not params.get("fail_unknown", True) else "fail"


def rcode_value_conflict(row: dict[str, Any], params: dict[str, Any], ctx: EvalContext) -> Outcome:
    del ctx
    code = row.get(params.get("rcode_field"))
    value = row.get(params.get("value_field"))
    if _blank(code):
        return "skip"
    empty_codes = {str(item).strip().upper() for item in params.get("empty_rcodes") or ["3", "NXDOMAIN"]}
    if str(code).strip().upper() not in empty_codes:
        return "pass"
    if _blank(value):
        return "pass"
    if str(value).strip().upper() in {"NULL", "NONE", "-"}:
        return "pass"
    return "fail"


def value_in_collection(row: dict[str, Any], params: dict[str, Any], ctx: EvalContext) -> Outcome:
    del ctx
    item = row.get(params.get("item_field"))
    collection = row.get(params.get("collection_field"))
    if _blank(item) or _blank(collection):
        return "skip"
    text = str(item).strip()
    raw = str(collection).strip()
    if text == raw:
        return "pass"
    separators = list(params.get("separators") or [",", ";", " "])
    pattern = "[" + "".join(re.escape(item) for item in separators) + "]+"
    tokens = {part.strip() for part in re.split(pattern, raw) if part.strip()}
    return "pass" if text in tokens else "fail"


def time_matches_partition(row: dict[str, Any], params: dict[str, Any], ctx: EvalContext) -> Outcome:
    del ctx
    timezone_name = str(params.get("timezone") or "Asia/Shanghai")
    moment = parse_time(row.get(params.get("time_field")), list(params.get("time_formats") or ["iso8601"]), timezone_name)
    raw = ""
    for name in params.get("partition_fields") or []:
        if not _blank(row.get(name)):
            raw = str(row.get(name)).strip()
            break
    if not raw:
        return "skip"
    if moment is None:
        return "fail"
    matched = partition_matches(moment, raw, timezone_name)
    if matched is None:
        return "unknown"
    return "pass" if matched else "fail"


def record_required(row: dict[str, Any], params: dict[str, Any], ctx: EvalContext) -> Outcome:
    del ctx
    all_of = list(params.get("all_of") or [])
    any_of = list(params.get("any_of") or [])
    if any(_blank(row.get(name)) for name in all_of):
        return "fail"
    if any_of and all(_blank(row.get(name)) for name in any_of):
        return "fail"
    return "pass"


def record_fingerprint(row: dict[str, Any], params: dict[str, Any], ctx: EvalContext) -> Outcome:
    fields = list(params.get("fields") or [])
    if not fields:
        return "skip"
    rule_id = str(params.get("_rule_id") or "fingerprint")
    seen = ctx.seen.setdefault(rule_id, set())
    token = json.dumps({name: row.get(name) for name in fields}, ensure_ascii=False, sort_keys=True, default=str)
    if token in seen:
        return "fail"
    if len(seen) >= ctx.max_fingerprints:
        ctx.partial[rule_id] = True
        return "skip"
    seen.add(token)
    return "pass"


def future_time(row: dict[str, Any], params: dict[str, Any], ctx: EvalContext) -> Outcome:
    value = row.get(params.get("field"))
    if _blank(value):
        return "skip"
    moment = parse_time(value, list(params.get("formats") or ["iso8601"]), str(params.get("timezone") or "Asia/Shanghai"))
    if moment is None:
        return "skip"
    slack = timedelta(hours=float(params.get("slack_hours") or 24))
    return "fail" if moment > ctx.now + slack else "pass"


OPERATORS = {
    "field_empty": field_empty,
    "validate_ip": validate_ip,
    "validate_domain": validate_domain,
    "validate_time": validate_time,
    "validate_enum": validate_enum,
    "validate_number": validate_number,
    "validate_dns_rdata": validate_dns_rdata,
    "type_relation": type_relation,
    "rcode_value_conflict": rcode_value_conflict,
    "value_in_collection": value_in_collection,
    "time_matches_partition": time_matches_partition,
    "record_required": record_required,
    "record_fingerprint": record_fingerprint,
    "future_time": future_time,
}

RELATION_OPERATORS = {
    "validate_dns_rdata",
    "type_relation",
    "rcode_value_conflict",
    "value_in_collection",
    "time_matches_partition",
}


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(part.isdigit() and 0 <= int(part) <= 255 and (part == "0" or not part.startswith("0")) for part in parts)
    except ValueError:
        return False


def _ipv6(value: str) -> bool:
    if ":" not in value:
        return False
    try:
        import ipaddress

        ipaddress.IPv6Address(value)
        return True
    except ValueError:
        return False


def _ipv4_integer(value: str) -> bool:
    if not value.isdigit():
        return False
    number = int(value)
    return 0 <= number <= 0xFFFFFFFF


def _domain(value: str) -> bool:
    text = value[:-1] if value.endswith(".") else value
    if not text or len(text) > 253 or any(char.isspace() for char in text):
        return False
    try:
        text = text.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    labels = text.split(".")
    return all(_LABEL.fullmatch(label) for label in labels)


def _matches(value: str, kind: str) -> bool:
    if kind == "ipv4":
        return _ipv4(value)
    if kind == "ipv6":
        return _ipv6(value)
    if kind == "domain":
        return _domain(value)
    if kind == "text":
        return not _blank(value)
    return not _blank(value)
