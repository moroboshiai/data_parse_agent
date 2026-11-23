"""程序给出允许动作，模型只能在其中选择。"""

from __future__ import annotations

from typing import Any

from quality.schemas import QualityProfile

MEASURE_ACTIONS = (
    "get_volume_stats",
    "get_field_quality_stats",
    "run_field_rules",
    "run_relation_rules",
    "get_distribution_stats",
    "compare_baseline",
)


def allowed_actions(profile: QualityProfile) -> list[str]:
    actions = [
        "get_volume_stats",
        "get_field_quality_stats",
        "run_field_rules",
        "run_relation_rules",
    ]
    if profile.distribution_dimensions:
        actions.append("get_distribution_stats")
    actions.extend(["compare_baseline", "generate_report", "finish"])
    return actions


def fallback_actions(allowed: list[str]) -> list[dict[str, str]]:
    return [
        {"action": action, "reason": "模型不可用，执行全部允许的检测"}
        for action in allowed
        if action != "finish"
    ]


def resolve_plan(allowed: list[str], proposed: list[dict[str, Any]]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in proposed:
        action = str(item.get("action") or "")
        reason = str(item.get("reason") or "")
        if action == "finish":
            continue
        if action not in allowed or action in seen:
            rejected.append({"action": action, "reason": "动作未授权或重复"})
            continue
        accepted.append({"action": action, "reason": reason})
        seen.add(action)
    if "generate_report" in allowed and "generate_report" not in seen:
        accepted.append({"action": "generate_report", "reason": "需要输出质量报告"})
    if not any(item["action"] in MEASURE_ACTIONS for item in accepted):
        return fallback_actions(allowed), rejected
    return accepted, rejected


def selected_groups(actions: list[dict[str, str]]) -> set[str]:
    names = {item["action"] for item in actions}
    groups = set()
    if "run_field_rules" in names or "get_field_quality_stats" in names:
        groups.add("run_field_rules")
    if "run_relation_rules" in names:
        groups.add("run_relation_rules")
    if "compare_baseline" in names:
        groups.add("compare_baseline")
    return groups
