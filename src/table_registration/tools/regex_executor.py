"""用样本测试提取规则。模型给出的正则必须经过这里，不能直接采用。"""

from __future__ import annotations

import re
import threading
from typing import Any

from table_registration.config import RuleSettings
from table_registration.rules.engine import check_regex_safety

_IPV4 = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}$")
_DATE = re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}")


def value_matches_type(value: str, expected_type: str) -> bool:
    kind = (expected_type or "string").lower()
    if kind in {"string", "unknown", "text", ""}:
        return bool(value)
    if kind in {"ip", "ipv4"}:
        return _IPV4.fullmatch(value) is not None
    if kind in {"url", "uri"}:
        return value.startswith("http://") or value.startswith("https://")
    if kind in {"datetime", "timestamp", "time"}:
        return _DATE.search(value) is not None
    return bool(value)


def test_extraction_rule(
    rule: dict[str, Any],
    samples: list[Any],
    settings: RuleSettings,
    *,
    timeout: float = 0.2,
) -> dict[str, Any]:
    pattern = str(rule.get("pattern") or "")
    errors = check_regex_safety(pattern, settings)
    if errors:
        return {"passed": False, "errors": errors, "mismatches": [], "previews": []}
    compiled = re.compile(pattern)
    group = int(rule.get("group") or 0)
    expected = str(rule.get("expected_type") or "string")
    previews: list[dict[str, Any]] = []
    mismatches: list[str] = []
    values = [str(value) for value in samples if value not in (None, "")]
    if not values:
        return {"passed": False, "errors": ["没有可用于测试的样本"], "mismatches": [], "previews": []}
    for value in values:
        extracted, error = _search(compiled, value[:500], group, timeout)
        if error:
            errors.append(f"{value}: {error}")
            continue
        if extracted is None:
            previews.append({"input": value, "output": None})
            continue
        if not value_matches_type(extracted, expected):
            mismatches.append(f"误匹配: {value} -> {extracted}")
            previews.append({"input": value, "output": extracted})
            continue
        previews.append({"input": value, "output": extracted})
    matched = [item for item in previews if item["output"] not in (None, "")]
    if not matched:
        errors.append("正则没有从样本中提取到内容")
    errors.extend(mismatches)
    return {
        "passed": not errors and not mismatches,
        "errors": errors,
        "mismatches": mismatches,
        "previews": previews,
    }


def apply_extraction(rule: dict[str, Any], value: Any) -> tuple[Any, str | None]:
    if value in (None, ""):
        return None, "样本值为空"
    try:
        compiled = re.compile(str(rule.get("pattern") or ""))
        match = compiled.search(str(value))
    except re.error as exc:
        return None, f"正则无法编译: {exc}"
    if not match:
        return None, "正则未匹配"
    group = int(rule.get("group") or 0)
    try:
        return match.group(group), None
    except IndexError:
        return None, "捕获组不存在"


def _search(compiled: re.Pattern[str], text: str, group: int, timeout: float) -> tuple[str | None, str | None]:
    holder: dict[str, Any] = {}

    def runner() -> None:
        try:
            holder["match"] = compiled.search(text)
        except Exception as exc:  # noqa: BLE001 - 把匹配异常转成测试失败
            holder["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return None, "正则匹配超时"
    if "error" in holder:
        return None, str(holder["error"])
    match = holder.get("match")
    if not match:
        return None, None
    try:
        return match.group(group), None
    except IndexError:
        return None, "捕获组不存在"
