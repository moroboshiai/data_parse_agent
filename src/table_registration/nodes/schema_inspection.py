"""判断有没有来源表结构，并把结构化说明收成统一字段列表。"""

from __future__ import annotations

from typing import Any

from table_registration.llm import LlmError
from table_registration.rules.engine import choose_mapping_mode, validate_standard_schema
from table_registration.schemas.mapping_result import NormalizedSourceSchema
from table_registration.tools.schema_provider import (
    SchemaError,
    fields_from_samples,
    load_source_schema_file,
    normalize_standard_schema,
    program_normalize,
)


def inspect_schema(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    if state.get("status") == "failed":
        return {}
    try:
        standard_schema = normalize_standard_schema(state.get("standard_schema") or {})
    except SchemaError as exc:
        return {"status": "failed", "errors": [str(exc)]}
    schema_errors = validate_standard_schema(standard_schema)
    if schema_errors:
        return {"status": "failed", "errors": schema_errors, "standard_schema": standard_schema}
    raw, load_error = _load_raw(state)
    if load_error:
        return {"status": "failed", "errors": [load_error]}
    if _missing(raw):
        return {
            "standard_schema": standard_schema,
            "source_fields": fields_from_samples(state.get("source_samples") or {}),
            "mapping_mode": choose_mapping_mode(False),
        }
    if _is_text(raw):
        return _normalize_with_skill(raw if isinstance(raw, str) else str(raw["raw_text"]), deps)
    try:
        normalized = program_normalize(raw)
    except SchemaError as exc:
        return {"status": "failed", "errors": [str(exc)]}
    return {
        "standard_schema": standard_schema,
        "source_fields": normalized["source_fields"],
        "mapping_mode": choose_mapping_mode(True),
    }


def _load_raw(state: dict[str, Any]) -> tuple[Any, str | None]:
    raw = state.get("source_schema_raw")
    path = state.get("source_schema_path") or ""
    if raw not in (None, "", {}) or not path:
        return raw, None
    try:
        loaded = load_source_schema_file(path)
    except SchemaError as exc:
        return None, str(exc)
    if loaded["kind"] == "text":
        return loaded["text"], None
    return loaded["data"], None


def _missing(raw: Any) -> bool:
    return raw in (None, "", {})


def _is_text(raw: Any) -> bool:
    if isinstance(raw, str):
        return True
    return isinstance(raw, dict) and "raw_text" in raw and "source_fields" not in raw and "fields" not in raw


def _normalize_with_skill(text: str, deps: Any) -> dict[str, Any]:
    try:
        result = deps.skills.run(
            "normalize_source_schema",
            {"raw_text": text},
            NormalizedSourceSchema,
            _force_unknown_types,
        )
    except LlmError as exc:
        return {"status": "failed", "errors": [f"来源表结构标准化失败: {exc}"]}
    fields = [item.model_dump() for item in result.source_fields]
    for field in fields:
        field["field_type"] = "unknown"
        if not field["field_id"]:
            field["field_id"] = field["field_name"]
    if not fields or any(not field["field_name"] for field in fields):
        return {"status": "failed", "errors": ["来源表结构没有有效字段"]}
    identities = [field["field_id"] for field in fields]
    names = [field["field_name"] for field in fields]
    if len(identities) != len(set(identities)) or len(names) != len(set(names)):
        return {"status": "failed", "errors": ["字段标识不能重复"]}
    return {"source_fields": fields, "mapping_mode": choose_mapping_mode(True)}


def _force_unknown_types(payload: dict[str, Any]) -> dict[str, Any]:
    fields = []
    for item in payload.get("source_fields") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("field_name") or "").strip()
        fields.append(
            {
                "field_id": str(item.get("field_id") or name).strip(),
                "field_name": name,
                "field_type": "unknown",
                "description": str(item.get("description") or ""),
            }
        )
    payload["source_fields"] = fields
    return payload
