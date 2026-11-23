"""置信度分流，以及把已映射字段送入质量分析。"""

from __future__ import annotations

from typing import Any

from table_registration.nodes.mapping_ops import run_mapping
from table_registration.rules.engine import apply_uniqueness, fields_needing_retry, filter_mapped, make_mapping


def confidence_gate(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    if state.get("status") == "failed":
        return {}
    names = [field["field_name"] for field in state.get("source_fields") or []]
    return {"retry_fields": fields_needing_retry(state.get("initial_mappings") or [], names)}


def sample_assisted_mapping(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    if state.get("status") == "failed":
        return {}
    retry = set(state.get("retry_fields") or [])
    fields = [field for field in state.get("source_fields") or [] if field["field_name"] in retry]
    mappings, error = run_mapping(
        state,
        deps,
        "map_with_sample_assist",
        fields,
        include_samples=True,
        previous=state.get("initial_mappings") or [],
    )
    if error:
        return {"status": "failed", "errors": [error]}
    return {"assisted_mappings": mappings}


def assemble_mappings(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    if state.get("status") == "failed":
        return {}
    initial = list(state.get("initial_mappings") or [])
    retry = list(state.get("retry_fields") or [])
    if state.get("mapping_mode") == "schema" and retry:
        retry_names = set(retry)
        kept = [item for item in initial if item["source_field"] not in retry_names]
        assisted = [item for item in state.get("assisted_mappings") or [] if item["source_field"] in retry_names]
        present = {item["source_field"] for item in assisted}
        for name in retry:
            if name not in present:
                assisted.append(
                    make_mapping(
                        source_field=name,
                        reason="二次映射未返回结果",
                        explanation="二次映射未返回结果",
                    )
                )
        merged = [*kept, *assisted]
    else:
        merged = initial
    resolved, messages, notes = apply_uniqueness(merged, state["standard_schema"]["fields"])
    return {
        "final_mappings": filter_mapped(resolved),
        "unmapped_fields": [item for item in resolved if not item.get("target_field")],
        "validation_results": messages,
        "errors": messages,
        "notices": notes,
    }
