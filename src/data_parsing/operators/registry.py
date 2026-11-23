"""白名单算子。只执行注册表中的函数，不执行模型给出的代码。"""

from __future__ import annotations

import re
from ipaddress import IPv4Address
from typing import Any
from urllib.parse import urlparse

from data_parsing.policies import RulePolicyError, assert_operator
from common.timefmt import format_clock, parse_clock

_IPV4 = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")
_DOMAIN = re.compile(r"^(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")
_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
)
_INVALID = {"", "-", "n/a", "na", "none", "null", "无"}


class OperatorResult:
    def __init__(self, value: Any, *, ok: bool, error: str = "", invalid: bool = False) -> None:
        self.value = value
        self.ok = ok
        self.error = error
        self.invalid = invalid


def execute(operator: str, value: Any, params: dict[str, Any] | None = None) -> OperatorResult:
    try:
        name = assert_operator(operator)
    except RulePolicyError as exc:
        return OperatorResult(value, ok=False, error=str(exc))
    options = dict(params or {})
    options.pop("code", None)
    options.pop("__code__", None)
    try:
        return _OPERATORS[name](value, options)
    except Exception as exc:  # noqa: BLE001 - 算子失败变成可追溯的执行结果
        return OperatorResult(value, ok=False, error=str(exc))


def _passthrough(value: Any, params: dict[str, Any]) -> OperatorResult:
    return OperatorResult(value, ok=True)


def _extract_regex(value: Any, params: dict[str, Any]) -> OperatorResult:
    if value in (None, ""):
        return OperatorResult(None, ok=False, error="样本值为空")
    pattern = str(params.get("pattern") or "")
    group = int(params.get("group") or 1)
    matched = re.search(pattern, str(value))
    if not matched:
        return OperatorResult(None, ok=False, error="正则未匹配")
    try:
        extracted = matched.group(group)
    except IndexError:
        return OperatorResult(None, ok=False, error="捕获组不存在")
    return OperatorResult(extracted, ok=bool(extracted))


def _extract_ip(value: Any, params: dict[str, Any]) -> OperatorResult:
    if value in (None, ""):
        return OperatorResult(None, ok=False, error="样本值为空")
    found = _IPV4.findall(str(value))
    if not found:
        return OperatorResult(None, ok=False, error="未提取到 IP")
    if params.get("all"):
        return OperatorResult(";".join(found), ok=True)
    return OperatorResult(found[0], ok=True)


def _extract_domain(value: Any, params: dict[str, Any]) -> OperatorResult:
    if value in (None, ""):
        return OperatorResult(None, ok=False, error="样本值为空")
    text = str(value).strip()
    host = urlparse(text).hostname if "://" in text else text.split("/")[0].split(":")[0]
    host = (host or "").strip().lower()
    if not _DOMAIN.match(host):
        return OperatorResult(None, ok=False, error="未提取到域名")
    return OperatorResult(host, ok=True)


def _trim(value: Any, params: dict[str, Any]) -> OperatorResult:
    if value is None:
        return OperatorResult(None, ok=False, error="样本值为空")
    return OperatorResult(str(value).strip(), ok=True)


def _replace(value: Any, params: dict[str, Any]) -> OperatorResult:
    if value is None:
        return OperatorResult(None, ok=False, error="样本值为空")
    old = str(params.get("old") or "")
    new = str(params.get("new") or "")
    return OperatorResult(str(value).replace(old, new), ok=True)


def normalize_ipv4_field(field_name: str, value: Any) -> Any:
    """IPv4 规范字段上，把 32 位整数地址转成点分形式。已是点分地址或其它内容保持原值。"""
    if not _is_ipv4_field(field_name) or value in (None, ""):
        return value
    converted = _ipv4_from_integer(value)
    return converted if converted is not None else value


def _is_ipv4_field(field_name: str) -> bool:
    name = field_name.strip().lower()
    if name.endswith("_ip6") or name.endswith("ip6"):
        return False
    return name.endswith("_ip") or name in {"dns_a"}


def _ipv4_from_integer(value: Any) -> str | None:
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text.isdigit():
        return None
    number = int(text)
    if number > 0xFFFFFFFF:
        return None
    return str(IPv4Address(number))


def _normalize_ipv4(value: Any, params: dict[str, Any]) -> OperatorResult:
    if value in (None, ""):
        return OperatorResult(None, ok=False, error="样本值为空")
    converted = _ipv4_from_integer(value)
    if converted is None:
        text = str(value).strip()
        if _IPV4.fullmatch(text):
            return OperatorResult(text, ok=True)
        return OperatorResult(value, ok=False, error=f"无法转换为 IPv4: {text}")
    return OperatorResult(converted, ok=True)


def _normalize_time(value: Any, params: dict[str, Any]) -> OperatorResult:
    if value in (None, ""):
        return OperatorResult(None, ok=False, error="样本值为空")
    output_format = str(params.get("output_format") or "%Y-%m-%d %H:%M:%S")
    formats: list[str] = []
    for item in [*list(params.get("input_formats") or []), output_format, *_TIME_FORMATS]:
        if item and item not in formats:
            formats.append(item)
    try:
        parsed = parse_clock(str(value), formats)
    except ValueError as exc:
        return OperatorResult(value, ok=False, error=str(exc))
    return OperatorResult(format_clock(parsed, output_format), ok=True)


def _convert_type(value: Any, params: dict[str, Any]) -> OperatorResult:
    if value in (None, ""):
        return OperatorResult(None, ok=False, error="样本值为空")
    target = str(params.get("target") or "str")
    text = str(value).strip()
    try:
        if target in {"int", "integer"}:
            return OperatorResult(int(text), ok=True)
        if target == "float":
            return OperatorResult(float(text), ok=True)
        return OperatorResult(text, ok=True)
    except ValueError:
        return OperatorResult(value, ok=False, error=f"无法转换为 {target}")


def _collapse(value: Any, params: dict[str, Any]) -> OperatorResult:
    if value is None:
        return OperatorResult(None, ok=False, error="样本值为空")
    return OperatorResult(re.sub(r"\s+", " ", str(value)).strip(), ok=True)


def _lower(value: Any, params: dict[str, Any]) -> OperatorResult:
    if value is None:
        return OperatorResult(None, ok=False, error="样本值为空")
    return OperatorResult(str(value).lower(), ok=True)


def _upper(value: Any, params: dict[str, Any]) -> OperatorResult:
    if value is None:
        return OperatorResult(None, ok=False, error="样本值为空")
    return OperatorResult(str(value).upper(), ok=True)


def _mark_invalid(value: Any, params: dict[str, Any]) -> OperatorResult:
    text = "" if value is None else str(value).strip().lower()
    if text in _INVALID:
        return OperatorResult(value, ok=False, error="异常占位值", invalid=True)
    return OperatorResult(value, ok=True)


_OPERATORS = {
    "passthrough": _passthrough,
    "extract_regex": _extract_regex,
    "extract_ip": _extract_ip,
    "extract_domain": _extract_domain,
    "trim": _trim,
    "replace": _replace,
    "normalize_time": _normalize_time,
    "normalize_ipv4": _normalize_ipv4,
    "convert_type": _convert_type,
    "collapse_whitespace": _collapse,
    "lower": _lower,
    "upper": _upper,
    "mark_invalid": _mark_invalid,
}
