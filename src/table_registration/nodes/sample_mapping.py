"""没有来源结构时，只用样本和规范表做映射。"""

from __future__ import annotations

from typing import Any

from table_registration.nodes.mapping_ops import run_mapping


def sample_mapping(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    if state.get("status") == "failed":
        return {}
    mappings, error = run_mapping(
        state,
        deps,
        "map_from_sample",
        state.get("source_fields") or [],
        include_samples=True,
    )
    if error:
        return {"status": "failed", "errors": [error], "initial_mappings": []}
    return {"initial_mappings": mappings}
