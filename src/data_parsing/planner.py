"""Pipeline Builder 规划：程序算事实，模型只在允许动作里选择。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data_parsing.repository import RuleRepository

ACTIONS = (
    "passthrough",
    "use_existing",
    "reuse_generic",
    "use_seeded",
    "generate",
    "human_review",
    "return_to_registration",
)

_FALLBACK_ORDER = (
    "use_existing",
    "reuse_generic",
    "use_seeded",
    "generate",
    "passthrough",
    "human_review",
    "return_to_registration",
)


def load_catalog() -> list[dict[str, Any]]:
    path = Path(__file__).resolve().parent / "skills" / "catalog.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("skills") or [])


def inventory(
    *,
    mappings: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    repository: RuleRepository,
    source_table: str,
    source_type: str,
    metrics: dict[str, Any] | None = None,
    replan: bool = False,
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for mapping in mappings:
        source_field = mapping["source_field"]
        standard_field = mapping["target_field"]
        related = [
            issue
            for issue in issues
            if issue.get("source_field") == source_field and issue.get("standard_field") == standard_field
        ]
        specific = specific_rule(repository, standard_field, source_table, source_type)
        generic = generic_rule(repository, standard_field, source_type)
        seeded_ids = []
        for issue in related:
            rule_id = seeded_rule_id(repository, issue)
            if rule_id:
                seeded_ids.append(rule_id)
        last_test = field_metrics(metrics, standard_field)
        failed_existing = replan and bool(specific) and int((last_test or {}).get("failure") or 0) > 0
        fact = {
            "source_field": source_field,
            "standard_field": standard_field,
            "has_issue": bool(related),
            "issue_types": [str(issue.get("issue_type") or "") for issue in related],
            "issues": related,
            "has_specific_rule": bool(specific),
            "specific_rule_id": specific["rule_id"] if specific else "",
            "has_generic_rule": bool(generic),
            "generic_rule_id": generic["rule_id"] if generic else "",
            "has_seeded_rule": bool(seeded_ids),
            "seeded_rule_id": seeded_ids[0] if seeded_ids else "",
            "seeded_rule_ids": seeded_ids,
            "last_test": last_test,
            "allowed_actions": [],
        }
        fact["allowed_actions"] = allowed_actions(fact, failed_existing=failed_existing)
        facts.append(fact)
    return facts


def allowed_actions(fact: dict[str, Any], *, failed_existing: bool = False) -> list[str]:
    if not fact.get("has_issue"):
        return ["passthrough", "human_review"]
    if fact.get("has_specific_rule") and not failed_existing:
        return ["use_existing", "human_review"]
    actions: list[str] = []
    if fact.get("has_generic_rule"):
        actions.append("reuse_generic")
    if fact.get("has_seeded_rule"):
        actions.append("use_seeded")
    actions.extend(["generate", "human_review"])
    if failed_existing or (not fact.get("has_generic_rule") and not fact.get("has_seeded_rule")):
        actions.append("return_to_registration")
    return actions


def fallback_action(fact: dict[str, Any]) -> str:
    allowed = fact.get("allowed_actions") or ["human_review"]
    for action in _FALLBACK_ORDER:
        if action in allowed:
            return action
    return str(allowed[0])


def resolve_actions(facts: list[dict[str, Any]], proposed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {(item.get("source_field"), item.get("standard_field")): item for item in proposed}
    resolved: list[dict[str, Any]] = []
    for fact in facts:
        item = by_key.get((fact["source_field"], fact["standard_field"])) or {}
        proposed_action = str(item.get("action") or "")
        allowed = fact.get("allowed_actions") or []
        overridden = proposed_action not in allowed
        action = fallback_action(fact) if overridden else proposed_action
        reason = str(item.get("reason") or "")
        if overridden:
            if proposed_action:
                extra = f"规划动作 {proposed_action} 不在允许列表中，回退为 {action}"
                reason = f"{reason}；{extra}" if reason else extra
            else:
                reason = reason or f"规划器未给出该字段动作，回退为 {action}"
        resolved.append(
            {
                "source_field": fact["source_field"],
                "standard_field": fact["standard_field"],
                "action": action,
                "proposed": proposed_action,
                "reason": reason,
                "overridden": overridden,
            }
        )
    return resolved


def planner_payload(
    facts: list[dict[str, Any]],
    *,
    source_table: str,
    source_type: str,
    replan_count: int,
) -> dict[str, Any]:
    compact = []
    for fact in facts:
        compact.append(
            {
                "source_field": fact["source_field"],
                "standard_field": fact["standard_field"],
                "has_issue": fact["has_issue"],
                "issue_types": fact["issue_types"],
                "has_specific_rule": fact["has_specific_rule"],
                "has_generic_rule": fact["has_generic_rule"],
                "has_seeded_rule": fact["has_seeded_rule"],
                "last_test": fact.get("last_test") or {},
                "allowed_actions": fact["allowed_actions"],
            }
        )
    return {
        "source_table": source_table,
        "source_type": source_type,
        "replan_count": replan_count,
        "catalog": load_catalog(),
        "fields": compact,
    }


def decision_record(
    fact: dict[str, Any],
    action: dict[str, Any],
    *,
    replan_count: int,
    execution_result: str = "",
) -> dict[str, Any]:
    return {
        "stage": "pipeline_building",
        "replan_count": replan_count,
        "observation": {
            "source_field": fact["source_field"],
            "standard_field": fact["standard_field"],
            "has_issue": fact["has_issue"],
            "has_specific_rule": fact["has_specific_rule"],
            "has_generic_rule": fact["has_generic_rule"],
            "has_seeded_rule": fact["has_seeded_rule"],
            "allowed_actions": list(fact.get("allowed_actions") or []),
            "last_test": fact.get("last_test") or {},
        },
        "decision": {
            "action": action["action"],
            "proposed": action.get("proposed") or action["action"],
            "reason": action.get("reason") or "",
        },
        "overridden": bool(action.get("overridden")),
        "execution_result": execution_result,
    }


def specific_rule(repository: RuleRepository, standard_field: str, source_table: str, source_type: str) -> dict[str, Any] | None:
    found = repository.lookup(standard_field=standard_field, source_table=source_table, source_type=source_type)
    if found and found.get("source_table") == source_table:
        return found
    return None


def generic_rule(repository: RuleRepository, standard_field: str, source_type: str) -> dict[str, Any] | None:
    found = repository.lookup(standard_field=standard_field, source_type=source_type)
    if found and not found.get("source_table"):
        return found
    return None


def seeded_rule_id(repository: RuleRepository, issue: dict[str, Any]) -> str:
    for rule in repository.list_rules(standard_field=issue["standard_field"], source_field=issue["source_field"]):
        if rule.get("source_table") != issue.get("source_table"):
            continue
        if rule.get("rule_type") != issue.get("issue_type"):
            continue
        if rule["versions"] and rule["versions"][-1]["test_status"] == "passed":
            return str(rule["rule_id"])
    return ""


def field_metrics(metrics: dict[str, Any] | None, standard_field: str) -> dict[str, int]:
    if not metrics:
        return {}
    item = metrics.get(standard_field) or {}
    if not item:
        return {}
    return {
        "failure": int(item.get("failure") or 0),
        "success": int(item.get("success") or 0),
        "total": int(item.get("total") or 0),
    }
