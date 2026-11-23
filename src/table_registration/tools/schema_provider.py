"""来源表与规范表结构读取。缺省类型保持 unknown，不推测字段类型。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from table_registration.tools.file_parser import SampleReadError, read_text_auto

_NAME_KEYS = (
    "storage_name", "field_name", "name", "source_field", 
    "规范字段名", "名称", "字段名", "字段名称")

_SEMANTIC_TYPE_KEYS = ("field_type", "type", "data_type", "类型", "字段类型")

_DESC_KEYS = ("description", "desc", "comment", "说明", "描述", "字段说明")

_ID_KEYS = ("field_id", "id", "字段标识")


class SchemaError(ValueError):
    pass


def load_standard_schema(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise SchemaError("规范表文件不存在或无法读取")
    try:
        payload = json.loads(read_text_auto(source))
    except (OSError, json.JSONDecodeError, SampleReadError) as exc:
        raise SchemaError("规范表文件无法读取") from exc
    if not isinstance(payload, dict):
        raise SchemaError("规范表格式错误")
    return normalize_standard_schema(payload)


def is_catalog_standard_schema(payload: dict[str, Any]) -> bool:
    """治理目录导出的规范表：source_id + fields[].source_field，source_type 为样例而非类型。"""
    if payload.get("source_id") and isinstance(payload.get("fields"), list):
        return True
    fields = payload.get("fields")
    if not isinstance(fields, list) or not fields:
        return False
    first = fields[0]
    return isinstance(first, dict) and "source_field" in first and "name" not in first


def normalize_standard_schema(payload: dict[str, Any]) -> dict[str, Any]:
    """统一为表注册内部规范表：id、name、fields[].name/type/description/allow_multi_source。"""
    if not isinstance(payload, dict):
        raise SchemaError("规范表格式错误")
    catalog = is_catalog_standard_schema(payload)
    schema_id = str(
        payload.get("id") 
        or payload.get("source_id") 
        or payload.get("category_alias")
        or ""
    ).strip()
    display_name = str(
        payload.get("name") 
        or payload.get("category_name")
        or payload.get("category_alias") 
        or schema_id
    ).strip()
    fields = [_standard_field(item, catalog=catalog) for item in payload.get("fields") or [] if isinstance(item, dict)]
    normalized: dict[str, Any] = {
        "id": schema_id,
        "name": display_name,
        "fields": fields,
    }
    if payload.get("structure_version") is not None:
        normalized["structure_version"] = payload.get("structure_version")
    if payload.get("category_alias") is not None:
        normalized["category_alias"] = payload.get("category_alias")
    return normalized


def _standard_field(item: dict[str, Any], *, catalog: bool) -> dict[str, Any]:
    name = _pick(item, _NAME_KEYS)
    if catalog:
        field_type = _pick(item, _SEMANTIC_TYPE_KEYS) or "unknown"
        if field_type == name or not _looks_semantic_type(field_type):
            field_type = "unknown"
    else:
        field_type = _pick(item, _SEMANTIC_TYPE_KEYS) or "unknown"
    description = _pick(item, ("description", "desc", "comment", "说明", "描述", "字段说明"))
    return {
        "name": name,
        "type": field_type or "unknown",
        "description": description,
        "allow_multi_source": bool(item.get("allow_multi_source", False)),
    }


def _looks_semantic_type(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered or lowered == "unknown":
        return False
    if lowered in {"string", "int", "integer", "float", "double", "boolean", "bool"}:
        return True
    if lowered in {"ip", "ipv4", "ipv6", "url", "uri", "datetime", "timestamp", "time", "date", "text"}:
        return True
    return len(lowered) <= 24 and " " not in lowered and "/" not in lowered and not lowered[0].isdigit()


def load_source_schema_file(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise SchemaError("来源表结构文件不存在或无法读取")
    suffix = source.suffix.lower()
    try:
        if suffix in {".txt", ".md"}:
            return {"kind": "text", "text": read_text_auto(source)}
        payload = json.loads(read_text_auto(source))
    except (OSError, json.JSONDecodeError, SampleReadError) as exc:
        raise SchemaError("来源表结构文件无法读取") from exc
    if isinstance(payload, str):
        return {"kind": "text", "text": payload}
    if isinstance(payload, (dict, list)):
        return {"kind": "structured", "data": payload}
    raise SchemaError("来源表结构格式错误")


def program_normalize(raw: dict[str, Any] | list[Any]) -> dict[str, Any]:
    fields = _coerce_fields(raw)
    if not fields:
        raise SchemaError("来源表结构没有有效字段")
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for field in fields:
        if not field["field_name"]:
            raise SchemaError("字段名称不能为空")
        if field["field_id"] in seen_ids or field["field_name"] in seen_names:
            raise SchemaError("字段标识不能重复")
        seen_ids.add(field["field_id"])
        seen_names.add(field["field_name"])
    return {"source_fields": fields}


def fields_from_samples(samples: dict[str, list[Any]]) -> list[dict[str, str]]:
    return [
        {"field_id": name, "field_name": name, "field_type": "unknown", "description": ""}
        for name in samples
    ]


def _coerce_fields(raw: dict[str, Any] | list[Any]) -> list[dict[str, str]]:
    if isinstance(raw, list):
        if all(isinstance(item, str) for item in raw):
            return [_field(item, item, None, "") for item in raw]
        return [_from_object(item) for item in raw if isinstance(item, dict)]
    if "raw_text" in raw and "source_fields" not in raw and "fields" not in raw:
        raise SchemaError("非结构化来源表结构需要由标准化能力处理")
    if isinstance(raw.get("source_fields"), list):
        return [_from_object(item) for item in raw["source_fields"] if isinstance(item, dict)]
    if isinstance(raw.get("fields"), list):
        return [_from_object(item) for item in raw["fields"] if isinstance(item, dict)]
    if raw and all(not isinstance(value, (dict, list)) for value in raw.values()):
        return [_field(str(key).strip(), str(value).strip(), None, "") for key, value in raw.items()]
    raise SchemaError("来源表结构格式错误")


def _from_object(item: dict[str, Any]) -> dict[str, str]:
    name = _pick(item, _NAME_KEYS)
    field_id = _pick(item, _ID_KEYS) or name
    field_type = _pick(item, _SEMANTIC_TYPE_KEYS)
    if "source_field" in item and field_type == name:
        field_type = ""
    description = _pick(item, _DESC_KEYS)
    return _field(field_id, name, field_type, description)


def _pick(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        if key in item and item[key] is not None:
            return str(item[key]).strip()
    return ""


def _field(field_id: str, field_name: str, field_type: str | None, description: str) -> dict[str, str]:
    provided = (field_type or "").strip()
    return {
        "field_id": field_id.strip() or field_name.strip(),
        "field_name": field_name.strip(),
        "field_type": provided or "unknown",
        "description": description.strip(),
    }
