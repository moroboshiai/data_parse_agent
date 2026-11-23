"""只为需要清洗的已映射字段生成白名单算子规则。"""

from __future__ import annotations

from typing import Any

from table_registration.llm import LlmError
from table_registration.nodes.field_quality import _concurrent
from table_registration.rules.engine import stamp_version
from table_registration.schemas.quality_result import CleaningRuleDraft
from table_registration.tools.sample import representative_values


def cleaning_generation(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    if state.get("status") == "failed":
        return {}
    tasks = _tasks(state)
    results = _concurrent(tasks, lambda task: _generate(state, deps, task), deps.rules.batch_size)
    rules = []
    errors = []
    sequence = 1
    for draft, error in results:
        if error:
            errors.append(error)
            continue
        stamped = stamp_version(draft, deps.rules.rule_version)
        stamped["rule_id"] = f"C{sequence:03d}"
        stamped["test_result"] = None
        sequence += 1
        rules.append(stamped)
    return {"cleaning_rules": rules, "errors": errors}


def _tasks(state: dict[str, Any]) -> list[dict[str, Any]]:
    qualities = {
        (item["source_field"], item["target_field"]): item for item in state.get("field_quality_results") or []
    }
    tasks = []
    for mapping in state.get("final_mappings") or []:
        quality = qualities.get((mapping["source_field"], mapping["target_field"]))
        if quality and quality.get("needs_cleaning"):
            tasks.append({"mapping": mapping, "quality": quality})
    return tasks


def _generate(state, deps, task) -> tuple[dict[str, Any] | None, str | None]:
    mapping = task["mapping"]
    quality = task["quality"]
    payload = {
        "source_field": mapping["source_field"],
        "target_field": mapping["target_field"],
        "cleaning_goal": quality.get("cleaning_goal") or "",
        "samples": representative_values(state.get("source_samples", {}).get(mapping["source_field"], [])),
    }
    try:
        draft = deps.skills.run("generate_cleaning_rule", payload, CleaningRuleDraft)
    except LlmError as exc:
        return None, f"{mapping['source_field']} 清洗规则生成失败: {exc}"
    data = draft.model_dump()
    if data["source_field"] != mapping["source_field"] or data["target_field"] != mapping["target_field"]:
        return None, f"{mapping['source_field']} 的清洗规则与映射字段不一致"
    return data, None
