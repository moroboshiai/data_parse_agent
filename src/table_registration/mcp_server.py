"""把本地工具暴露为 MCP 服务。注册图直接调用这些函数，不经过本进程。"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from table_registration.config import find_repo_root, get_rule_settings
from table_registration.tools.candidate_store import save_candidate
from table_registration.tools.cleaning_executor import test_cleaning_rule as execute_cleaning_test
from table_registration.tools.file_parser import SampleReadError, parse_table, read_text_auto
from table_registration.tools.mapping_memory import MappingMemory
from table_registration.tools.mapping_validate import validate_mapping as check_mapping
from table_registration.tools.regex_executor import test_extraction_rule as execute_extraction_test
from table_registration.tools.sample import limit_samples
from table_registration.tools.schema_provider import SchemaError, load_source_schema_file, load_standard_schema, program_normalize

mcp = MCPServer("table-registration")


@mcp.tool()
def read_source_file(path: str) -> dict:
    """读取上传文件的文本内容。二进制表格只返回文件信息。"""
    source = Path(path)
    if not source.is_file():
        return {"ok": False, "error": "文件不存在或无法读取"}
    if source.suffix.lower() in {".xlsx", ".xlsm"}:
        return {"ok": True, "path": str(source), "format": source.suffix.lower(), "size": source.stat().st_size}
    try:
        text = read_text_auto(source)
    except SampleReadError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": str(source), "content": text[:20000]}


@mcp.tool()
def parse_source_table(path: str) -> dict:
    """解析 Excel、CSV 或 JSON 样本，并返回有限行预览。"""
    try:
        rows = parse_table(path)
    except SampleReadError as exc:
        return {"ok": False, "error": str(exc)}
    rules = get_rule_settings()
    limited, _samples, notices = limit_samples(rows, max_rows=rules.max_sample_rows, max_fields=rules.max_fields)
    columns = list(limited[0].keys()) if limited else []
    return {"ok": True, "columns": columns, "row_count": len(rows), "rows": limited, "notices": notices}


@mcp.tool()
def extract_table_sample(path: str) -> dict:
    """按字段抽取样本值。"""
    parsed = parse_source_table(path)
    if not parsed.get("ok"):
        return parsed
    samples = {}
    for column in parsed["columns"]:
        samples[column] = [row.get(column) for row in parsed["rows"]]
    return {"ok": True, "samples": samples, "notices": parsed["notices"]}


@mcp.tool()
def get_source_schema(path: str) -> dict:
    """读取来源表结构。结构化内容会标准化，自由文本则标记为需要 Skill。"""
    try:
        loaded = load_source_schema_file(path)
    except SchemaError as exc:
        return {"ok": False, "error": str(exc)}
    if loaded["kind"] == "text":
        return {"ok": True, "needs_skill": True, "raw_text": loaded["text"], "normalized": None}
    try:
        normalized = program_normalize(loaded["data"])
    except SchemaError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "needs_skill": False, "normalized": normalized}


@mcp.tool()
def get_standard_schema(path: str) -> dict:
    """读取规范表结构。"""
    try:
        return {"ok": True, "schema": load_standard_schema(path)}
    except SchemaError as exc:
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def validate_mapping(mappings_json: str, standard_schema_path: str) -> dict:
    """校验字段映射是否指向规范表，并检查多来源约束。"""
    try:
        mappings = json.loads(mappings_json)
        schema = load_standard_schema(standard_schema_path)
    except (json.JSONDecodeError, SchemaError) as exc:
        return {"ok": False, "violations": [str(exc)]}
    if not isinstance(mappings, list):
        return {"ok": False, "violations": ["映射结果必须是数组"]}
    return check_mapping(mappings, schema)


@mcp.tool()
def test_extraction_rule(rule_json: str, samples_json: str) -> dict:
    """用样本测试提取规则。"""
    try:
        rule = json.loads(rule_json)
        samples = json.loads(samples_json)
    except json.JSONDecodeError as exc:
        return {"passed": False, "errors": [str(exc)], "mismatches": [], "previews": []}
    return execute_extraction_test(rule, samples, get_rule_settings())


@mcp.tool()
def test_cleaning_rule(rule_json: str, samples_json: str) -> dict:
    """用样本测试清洗规则，并对幂等算子做重复执行比对。"""
    try:
        rule = json.loads(rule_json)
        samples = json.loads(samples_json)
    except json.JSONDecodeError as exc:
        return {"passed": False, "errors": [str(exc)], "mismatches": [], "previews": []}
    return execute_cleaning_test(rule, samples)


@mcp.tool()
def save_candidate_mapping(document_json: str, directory: str = "") -> dict:
    """保存候选映射规则。"""
    try:
        document = json.loads(document_json)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": str(exc)}
    if not isinstance(document, dict) or not document.get("candidate_id"):
        return {"ok": False, "error": "候选规则缺少 candidate_id"}
    root = find_repo_root()
    path = save_candidate(directory or root / "outputs" / "candidates", document)
    return {"ok": True, "path": str(path)}


@mcp.tool()
def lookup_confirmed_mapping(schema_id: str, source_field: str, memory_path: str = "") -> dict:
    """查询已经确认、可复用的字段映射。"""
    root = find_repo_root()
    memory = MappingMemory(memory_path or root / "data" / "mapping_memory.json")
    return {"records": memory.lookup(schema_id, source_field)}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
