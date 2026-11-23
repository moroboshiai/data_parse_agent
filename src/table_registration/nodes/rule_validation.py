"""用样本执行规则测试。失败会记入错误，不会被悄悄丢掉。"""

from __future__ import annotations

from typing import Any

from table_registration.tools.cleaning_executor import test_cleaning_rule
from table_registration.tools.regex_executor import test_extraction_rule


def rule_validation(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    if state.get("status") == "failed":
        return {}
    samples = state.get("source_samples") or {}
    extraction_rules = []
    cleaning_rules = []
    messages: list[str] = []
    for rule in state.get("extraction_rules") or []:
        current = dict(rule)
        result = test_extraction_rule(current, samples.get(current["source_field"], []), deps.rules)
        current["test_result"] = result
        extraction_rules.append(current)
        if not result["passed"]:
            messages.append(f"提取规则 {current['rule_id']} 未通过样本测试: {'；'.join(result['errors'])}")
    for rule in state.get("cleaning_rules") or []:
        current = dict(rule)
        result = test_cleaning_rule(current, samples.get(current["source_field"], []))
        current["test_result"] = result
        cleaning_rules.append(current)
        if not result["passed"]:
            messages.append(f"清洗规则 {current['rule_id']} 未通过样本测试: {'；'.join(result['errors'])}")
    return {
        "extraction_rules": extraction_rules,
        "cleaning_rules": cleaning_rules,
        "validation_results": messages,
        "errors": messages,
    }
