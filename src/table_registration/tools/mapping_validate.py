"""映射结果合法性检查，供图内节点和 MCP 共用。"""

from __future__ import annotations

from typing import Any

from table_registration.rules.engine import (
    apply_uniqueness,
    validate_mapping_targets,
    validate_standard_schema,
)


def validate_mapping(
    mappings: list[dict[str, Any]],
    standard_schema: dict[str, Any],
) -> dict[str, Any]:
    violations = validate_standard_schema(standard_schema)
    fields = standard_schema.get("fields") or []
    violations.extend(validate_mapping_targets(mappings, fields))
    _resolved, messages, _notes = apply_uniqueness(mappings, fields)
    violations.extend(messages)
    return {"ok": not violations, "violations": violations}
