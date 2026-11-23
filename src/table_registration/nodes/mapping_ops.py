"""映射节点共用的分批、历史复用和模型调用。"""

from __future__ import annotations

from typing import Any

from table_registration.llm import LlmError
from table_registration.rules.engine import (
    MappingIsolationError,
    make_mapping,
    mapping_payload_normalizer,
    review_mapping,
)
from table_registration.schemas.mapping_result import MappingBatch
from table_registration.tools.sample import representative_values


def chunks(items: list[Any], size: int):
    step = max(1, size)
    for index in range(0, len(items), step):
        yield items[index : index + step]


def run_mapping(
    state: dict[str, Any],
    deps: Any,
    task_type: str,
    source_fields: list[dict[str, Any]],
    *,
    include_samples: bool,
    previous: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    standard = state["standard_schema"]
    names = {field["name"] for field in standard["fields"]}
    hits, rest = partition_history(source_fields, deps.memory, str(standard.get("id") or ""), names)
    produced = list(hits)
    samples = state.get("source_samples") or {}
    try:
        for batch in chunks(rest, deps.rules.mapping_batch_fields):
            previous_batch = None
            if previous is not None:
                names_in_batch = {field["field_name"] for field in batch}
                previous_batch = [item for item in previous if item["source_field"] in names_in_batch]
            payload = build_mapping_payload(
                batch,
                standard,
                samples,
                include_samples=include_samples,
                previous=previous_batch,
            )
            result = deps.skills.run(
                task_type,
                payload,
                MappingBatch,
                mapping_payload_normalizer(deps.rules),
            )
            produced.extend(item.model_dump() for item in result.mappings)
    except MappingIsolationError as exc:
        return [], str(exc)
    except LlmError as exc:
        return [], f"映射模型调用失败: {exc}"

    allowed = {field["field_name"] for field in source_fields}
    reviewed: list[dict[str, Any]] = []
    for item in produced:
        if item["source_field"] not in allowed:
            continue
        reviewed.append(
            review_mapping(
                item,
                standard["fields"],
                samples.get(item["source_field"], []),
                deps.rules,
            )
        )
    reviewed = dedupe_pairs(reviewed)
    seen = {item["source_field"] for item in reviewed}
    for field in source_fields:
        if field["field_name"] not in seen:
            reviewed.append(make_mapping(source_field=field["field_name"], reason="模型未返回该字段映射", explanation="模型未返回该字段映射"))
    return reviewed, None


def partition_history(source_fields, memory, schema_id: str, standard_names: set[str]):
    hits = []
    rest = []
    for field in source_fields:
        records = memory.lookup(schema_id, field["field_name"])
        usable = [item for item in records if item.get("target_field") in standard_names]
        if records and len(usable) == len(records):
            for item in usable:
                hits.append(
                    make_mapping(
                        source_field=field["field_name"],
                        target_field=item["target_field"],
                        explanation="复用已确认映射",
                        confidence="high",
                        evidence=["历史已确认映射"],
                        reason="该来源字段与规范字段的映射已确认",
                        needs_human_confirm=False,
                    )
                )
        else:
            rest.append(field)
    return hits, rest


def build_mapping_payload(source_fields, standard_schema, samples, *, include_samples: bool, previous):
    body = {
        "source_fields": source_fields,
        "standard_fields": [
            {
                "name": field["name"],
                "type": field.get("type") or "unknown",
                "description": field.get("description") or "",
                "allow_multi_source": bool(field.get("allow_multi_source", False)),
            }
            for field in standard_schema["fields"]
        ],
    }
    if include_samples:
        body["samples"] = {
            field["field_name"]: representative_values(samples.get(field["field_name"], []))
            for field in source_fields
        }
    if previous is not None:
        body["previous_mappings"] = previous
    return body


def dedupe_pairs(mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = []
    seen = set()
    for item in mappings:
        key = (item["source_field"], item.get("target_field"))
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept
