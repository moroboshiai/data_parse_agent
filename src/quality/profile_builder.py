"""从治理规范表结构生成质量画像草稿。首次接入时减少手工抄写。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from quality.rules.loader import load_rules
from quality.schemas import QualityProfile

_PARTITION_PATTERNS = {
    "yyyy-MM-dd HH:mm:ss": ["iso8601", "YYYY-MM-DD HH:MM:SS"],
    "yyyy-MM-dd": ["iso8601", "YYYY-MM-DD"],
    "yyyy/MM/dd HH:mm:ss": ["iso8601", "YYYY-MM-DD HH:MM:SS"],
}

_CATEGORY_DISTRIBUTIONS: dict[str, list[str]] = {
    "dns_log": ["dns_query_type", "dns_res_code", "proto_4"],
    "flow_log": ["proto_4", "proto_7", "cat1"],
    "alarm_event": ["proto_4", "cat1", "log_type", "log_type_name"],
}

_CATEGORY_DUPLICATE_HINTS: dict[str, list[str]] = {
    "dns_log": ["src_ip", "dst_ip", "domain", "proto_7", "time"],
    "flow_log": ["src_ip", "dst_ip", "proto_4", "proto_7", "time"],
    "alarm_event": ["time", "src_ip", "dst_ip", "name", "log_type"],
}

_CRITICAL_NAMES = frozenset(
    {
        "time",
        "recv_time",
        "src_ip",
        "dst_ip",
        "src_ip6",
        "dst_ip6",
        "domain",
        "sip",
        "dip",
        "name",
        "log_type",
        "event_id",
    }
)

_IMPORTANT_NAMES = frozenset({"proto_4", "proto_7", "cat1", "cat2", "rcode", "qtype", "action"})


def load_governance_schema(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"规范表文件不存在: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("规范表必须是 JSON 对象")
    return payload


def build_profile_from_standard_schema(
    path: str | Path,
    *,
    source_id: str = "",
    category: str = "",
    rules_root: str | Path | None = None,
    link_rules: bool = True,
) -> dict[str, Any]:
    """根据 data/standard_schema/*.json 生成 QualityProfile 字典（未写盘）。"""
    raw = load_governance_schema(path)
    alias = str(raw.get("category_alias") or "").strip()
    resolved_category = category.strip() or alias
    resolved_source = source_id.strip() or alias
    if not resolved_category or not resolved_source:
        raise ValueError("规范表缺少 category_alias，请通过 source_id 或 category 参数指定")
    time_field = str(raw.get("time_partition_field") or "time").strip()
    time_formats = _time_formats(str(raw.get("time_partition_field_type") or ""))
    field_names = {_field_name(item) for item in raw.get("fields") or [] if isinstance(item, dict)}
    field_names.discard("")
    distributions = [name for name in _CATEGORY_DISTRIBUTIONS.get(resolved_category, ["proto_4", "cat1"]) if name in field_names]
    duplicates = [name for name in _CATEGORY_DUPLICATE_HINTS.get(resolved_category, [time_field, "src_ip", "dst_ip"]) if name in field_names]
    rule_index = _rule_index(resolved_category, resolved_source, rules_root) if link_rules else {}
    fields = []
    for item in raw.get("fields") or []:
        if not isinstance(item, dict):
            continue
        name = _field_name(item)
        if not name:
            continue
        fields.append(
            _field_profile(
                item,
                check_rules=sorted(rule_index.get(name, [])),
            )
        )
    profile = {
        "source_id": resolved_source,
        "category": resolved_category,
        "structure_version": str(raw.get("structure_version") or "1"),
        "quality_profile_version": "1",
        "time_field": time_field if time_field in field_names else "",
        "time_formats": time_formats,
        "timezone": "Asia/Shanghai",
        "partition_fields": _partition_fields(raw, field_names),
        "distribution_dimensions": distributions,
        "duplicate_fields": duplicates,
        "ingest_field": "recv_time" if "recv_time" in field_names else "",
        "fields": fields,
    }
    return QualityProfile.model_validate(profile).model_dump()


def save_profile(path: str | Path, profile: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _field_name(item: dict[str, Any]) -> str:
    return str(item.get("storage_name") or item.get("name") or item.get("field_name") or "").strip()


def _time_formats(pattern: str) -> list[str]:
    text = pattern.strip().lower()
    if not text:
        return ["iso8601"]
    normalized = text.replace("yyyy", "YYYY").replace("dd", "DD").replace("HH", "HH").replace("mm", "MM").replace("ss", "SS")
    if normalized in _PARTITION_PATTERNS:
        return list(_PARTITION_PATTERNS[normalized])
    if "yyyy-mm-dd hh:mm:ss" in text:
        return ["iso8601", "YYYY-MM-DD HH:MM:SS"]
    return ["iso8601"]


def _partition_fields(raw: dict[str, Any], names: set[str]) -> list[str]:
    fields = []
    for key in (str(raw.get("time_partition_field") or ""), "recv_time", "time_part", "day_hour"):
        if key and key in names and key not in fields:
            fields.append(key)
    return fields


def _field_profile(item: dict[str, Any], *, check_rules: list[str]) -> dict[str, Any]:
    name = _field_name(item)
    storage_type = str(item.get("type") or "STRING").strip().upper()
    data_type, formats = _map_type(storage_type, item)
    level = _quality_level(name, storage_type, item)
    return {
        "field": name,
        "data_type": data_type,
        "storage_type": _storage_label(storage_type),
        "nullable": not _required(item),
        "quality_level": level,
        "comment": _comment(item),
        "format": formats,
        "enum_values": [],
        "check_rules": check_rules,
    }


def _map_type(storage_type: str, item: dict[str, Any]) -> tuple[str, list[str]]:
    name = _field_name(item).lower()
    if storage_type in {"TIMESTAMP", "DATETIME", "DATE"}:
        return "timestamp", ["iso8601"]
    if storage_type in {"INT", "INTEGER", "LONG", "BIGINT", "FLOAT", "DOUBLE", "NUMBER"}:
        return "number", []
    if storage_type == "IP" or name.endswith("_ip") or name in {"src_ip", "dst_ip", "sip", "dip"}:
        return "ip", ["ipv4", "ipv6"]
    if "domain" in name:
        return "domain", []
    if storage_type in {"KEYWORD", "ENUM"} or "枚举" in str(item.get("description") or ""):
        return "enum", []
    if storage_type == "BOOLEAN":
        return "boolean", []
    return "string", []


def _storage_label(storage_type: str) -> str:
    mapping = {
        "INT": "integer",
        "INTEGER": "integer",
        "LONG": "integer",
        "BIGINT": "integer",
        "FLOAT": "number",
        "DOUBLE": "number",
        "NUMBER": "number",
        "TIMESTAMP": "string",
        "DATETIME": "string",
        "STRING": "string",
        "KEYWORD": "string",
        "TEXT": "string",
        "IP": "string",
        "BOOLEAN": "boolean",
    }
    return mapping.get(storage_type.upper(), storage_type.lower() or "string")


def _quality_level(name: str, storage_type: str, item: dict[str, Any]) -> str:
    lowered = name.lower()
    if lowered in _CRITICAL_NAMES or storage_type in {"TIMESTAMP", "IP"}:
        return "critical"
    if lowered in _IMPORTANT_NAMES:
        return "important"
    desc = str(item.get("description") or "")
    if "必须" in desc or "必填" in desc:
        return "critical"
    if re.search(r"(重要|主键|唯一)", desc):
        return "important"
    return "optional"


def _required(item: dict[str, Any]) -> bool:
    desc = str(item.get("description") or "")
    if ("必填" in desc or "必须" in desc) and "可以为空" not in desc:
        return True
    if str(item.get("nullable") or "").strip().lower() in {"否", "false", "0", "no"}:
        return True
    return False


def _comment(item: dict[str, Any]) -> str:
    chinese = str(item.get("chinese_name") or "").strip()
    desc = str(item.get("description") or "").strip()
    if chinese and desc:
        return f"{chinese}：{desc[:240]}"
    return chinese or desc[:280]


def _rule_index(category: str, source_id: str, rules_root: str | Path | None) -> dict[str, list[str]]:
    rules = load_rules(category, source_id, rules_root)
    grouped: dict[str, set[str]] = {}
    for rule in rules:
        scope = rule.get("scope") or {}
        targets = list(scope.get("fields") or [])
        params = rule.get("params") or {}
        if params.get("field"):
            targets.append(str(params["field"]))
        for name in params.get("fields") or []:
            targets.append(str(name))
        rule_id = str(rule.get("rule_id") or "")
        if not rule_id:
            continue
        for name in targets:
            if name:
                grouped.setdefault(name, set()).add(rule_id)
    return {key: sorted(values) for key, values in grouped.items()}
