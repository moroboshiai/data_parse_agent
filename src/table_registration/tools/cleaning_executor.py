"""白名单清洗算子。不执行模型给出的任意代码。"""

from __future__ import annotations

import re
from typing import Any

from table_registration.rules.engine import check_idempotent
from common.timefmt import format_clock, parse_clock

ALLOWED_OPERATORS = {
    "trim", 
    "normalize_datetime", 
    "lower", 
    "upper", 
    "collapse_whitespace"
}

_DEFAULT_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
)


class CleaningError(ValueError):
    pass


def apply_cleaning(rule: dict[str, Any], value: Any) -> Any:
    if value is None:
        return None
    operator = str(rule.get("operator") or "")
    if operator not in ALLOWED_OPERATORS:
        raise CleaningError(f"算子不在允许列表中: {operator}")
    text = str(value)
    if operator == "trim":
        return text.strip()
    if operator == "lower":
        return text.lower()
    if operator == "upper":
        return text.upper()
    if operator == "collapse_whitespace":
        return re.sub(r"\s+", " ", text).strip()
    return _normalize_datetime(text, rule)


def test_cleaning_rule(rule: dict[str, Any], samples: list[Any]) -> dict[str, Any]:
    errors: list[str] = []
    previews: list[dict[str, Any]] = []
    values = [value for value in samples if value not in (None, "")]
    if not values:
        return {"passed": False, "errors": ["没有可用于测试的样本"], "mismatches": [], "previews": []}
    if rule.get("operator") not in ALLOWED_OPERATORS:
        return {
            "passed": False,
            "errors": [f"算子不在允许列表中: {rule.get('operator')}"],
            "mismatches": [],
            "previews": [],
        }
    for value in values:
        try:
            output = apply_cleaning(rule, value)
        except CleaningError as exc:
            errors.append(str(exc))
            continue
        previews.append({"input": value, "output": output})
        if output in (None, ""):
            errors.append(f"清洗结果为空: {value}")
            continue
        if rule.get("idempotent", True):
            problem = check_idempotent(lambda current: apply_cleaning(rule, current), value)
            if problem:
                errors.append(f"{value}: {problem}")
    return {"passed": not errors, "errors": errors, "mismatches": [], "previews": previews}


def _normalize_datetime(text: str, rule: dict[str, Any]) -> str:
    output_format = str(rule.get("output_format") or rule.get("expression") or "%Y-%m-%d %H:%M:%S")
    formats: list[str] = []
    for item in [*list(rule.get("input_formats") or []), output_format, *_DEFAULT_TIME_FORMATS]:
        if item and item not in formats:
            formats.append(item)
    try:
        parsed = parse_clock(text, formats)
    except ValueError as exc:
        raise CleaningError(str(exc)) from exc
    return format_clock(parsed, output_format)
