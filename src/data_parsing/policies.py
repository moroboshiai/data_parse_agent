"""解析阶段的硬约束。模型输出不能绕过这些判断。"""

from __future__ import annotations

ALLOWED_OPERATORS = {
    "passthrough",
    "extract_regex",
    "extract_ip",
    "extract_domain",
    "trim",
    "replace",
    "normalize_time",
    "normalize_ipv4",
    "convert_type",
    "collapse_whitespace",
    "lower",
    "upper",
    "mark_invalid",
}

ISSUE_TYPES = {
    "extraction",
    "normalization",
    "redundancy",
    "type_conversion",
    "invalid_value",
    "composite_split",
    "canonicalization",
}

RULE_STATUSES = {"discovered", "candidate", "validated", "canary", "active", "deprecated"}


class RulePolicyError(ValueError):
    pass


def assert_operator(operator: str) -> str:
    if operator not in ALLOWED_OPERATORS:
        raise RulePolicyError(f"算子不在允许列表中: {operator}")
    return operator


def assert_can_activate(version: dict) -> None:
    if version.get("test_status") != "passed":
        raise RulePolicyError("未通过验证的规则不得自动成为生产规则")
