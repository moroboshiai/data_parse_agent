"""候选映射规则存储。注册阶段只保存建议，不把它标成生效规则。"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from table_registration.tools.mapping_memory import MappingMemory


def save_candidate(directory: str | Path, document: dict[str, Any]) -> Path:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{document['candidate_id']}.json"
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def delete_candidate(directory: str | Path, candidate_id: str) -> None:
    _candidate_file(directory, candidate_id).unlink()


def update_candidate_mappings(directory: str | Path, candidate_id: str, edits: list[dict[str, Any]]) -> dict[str, Any]:
    path = _candidate_file(directory, candidate_id)
    document = load_candidate(path)
    mappings = document.get("mappings")
    if not isinstance(mappings, list):
        raise ValueError("候选映射格式错误")
    for edit in edits:
        index = int(edit.get("index"))
        if index < 0 or index >= len(mappings) or not isinstance(mappings[index], dict):
            raise ValueError(f"映射序号超出范围: {index}")
        item = mappings[index]
        source_field = str(edit.get("source_field") or "").strip()
        target_field = str(edit.get("target_field") or "").strip()
        if not source_field or not target_field:
            raise ValueError("来源字段和规范字段不能为空")
        item["source_field"] = source_field
        item["target_field"] = target_field
        quality = item.get("quality")
        if isinstance(quality, dict):
            quality["source_field"] = source_field
            quality["target_field"] = target_field
        by_kind = {str(rule.get("kind") or ""): rule for rule in edit.get("rules") or [] if isinstance(rule, dict)}
        _apply_rule(item, "extraction_rule", by_kind.get("extraction"), source_field, target_field)
        _apply_rule(item, "cleaning_rule", by_kind.get("cleaning"), source_field, target_field)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return document


def _candidate_file(directory: str | Path, candidate_id: str) -> Path:
    folder = Path(directory).resolve()
    target = (folder / f"{candidate_id}.json").resolve()
    if target.parent != folder or not target.is_file():
        raise FileNotFoundError(f"找不到候选规则: {candidate_id}")
    return target


def _apply_rule(item: dict[str, Any], key: str, edit: dict[str, Any] | None, source_field: str, target_field: str) -> None:
    rule = item.get(key)
    if not isinstance(rule, dict) or edit is None:
        return
    rule["source_field"] = source_field
    rule["target_field"] = target_field
    rule["rule_id"] = str(edit.get("rule_id") or "")
    rule["description"] = str(edit.get("description") or "")
    if key == "extraction_rule":
        rule["pattern"] = str(edit.get("pattern") or "")
        if edit.get("group") is not None:
            rule["group"] = int(edit["group"])
        return
    operator = str(edit.get("operator") or rule.get("operator") or "")
    if operator:
        rule["operator"] = operator
        rule["rule_type"] = operator
    rule["output_format"] = str(edit.get("output_format") or "")


def load_candidate(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"找不到候选规则: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("候选规则格式错误")
    return payload


def confirm_candidate(path: str | Path, memory: MappingMemory) -> dict[str, Any]:
    source = Path(path)
    document = load_candidate(source)
    if document.get("status") == "failed":
        raise ValueError("失败结果不能确认")
    document["status"] = "confirmed"
    grouped: dict[str, list[str]] = defaultdict(list)
    schema_id = str(document.get("standard_schema_id") or "")
    for item in document.get("mappings") or []:
        item["status"] = "confirmed"
        target = item.get("target_field")
        if target:
            grouped[item["source_field"]].append(target)
    for source_field, targets in grouped.items():
        memory.replace_source(schema_id, source_field, targets)
    source.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return document
