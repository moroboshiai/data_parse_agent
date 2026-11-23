"""复核阶段只允许学习、诊断或结束。未授权动作由程序回退。"""

from __future__ import annotations

from typing import Any


ALLOWED_REVIEW_ACTIONS = ("learn", "diagnose", "finish")


def fallback_action(*, has_events: bool, has_high_issues: bool) -> str:
    if has_events:
        return "learn"
    if has_high_issues:
        return "diagnose"
    return "finish"


def resolve_review_action(
    proposed: str,
    *,
    has_events: bool,
    has_high_issues: bool,
) -> tuple[str, list[dict[str, Any]]]:
    rejected: list[dict[str, Any]] = []
    action = proposed if proposed in ALLOWED_REVIEW_ACTIONS else ""
    if proposed and proposed not in ALLOWED_REVIEW_ACTIONS:
        rejected.append({"action": proposed, "reason": "动作未授权"})
    if not action:
        action = fallback_action(has_events=has_events, has_high_issues=has_high_issues)
    if action == "learn" and not has_events:
        action = "diagnose" if has_high_issues else "finish"
    if action == "diagnose" and not has_high_issues:
        action = "finish"
    return action, rejected
