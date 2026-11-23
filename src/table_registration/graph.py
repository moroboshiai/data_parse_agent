"""表注册主控图。模型只在映射、质量分析和规则生成节点里被调用。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from table_registration.config import RuleSettings, find_repo_root, init_from_repo
from table_registration.llm import LlmClient
from table_registration.nodes.cleaning_generation import cleaning_generation
from table_registration.nodes.extraction_generation import extraction_generation
from table_registration.nodes.field_quality import field_quality
from table_registration.nodes.input_validation import validate_sample
from table_registration.nodes.mapping_review import assemble_mappings, confidence_gate, sample_assisted_mapping
from table_registration.nodes.result_assembly import result_assembly
from table_registration.nodes.rule_validation import rule_validation
from table_registration.nodes.sample_mapping import sample_mapping
from table_registration.nodes.schema_inspection import inspect_schema
from table_registration.nodes.schema_mapping import schema_mapping
from table_registration.skill_runtime import SkillRuntime
from table_registration.state import RegistrationState
from table_registration.tools.mapping_memory import MappingMemory
from table_registration.tools.schema_provider import SchemaError, load_standard_schema


@dataclass
class GraphDeps:
    rules: RuleSettings
    memory: MappingMemory
    skills: SkillRuntime
    candidate_dir: Path


def build_graph(deps: GraphDeps):
    graph = StateGraph(RegistrationState)

    def _validate(state: RegistrationState) -> dict[str, Any]:
        return validate_sample(state, deps)

    def _inspect(state: RegistrationState) -> dict[str, Any]:
        return inspect_schema(state, deps)

    def _sample_map(state: RegistrationState) -> dict[str, Any]:
        return sample_mapping(state, deps)

    def _schema_map(state: RegistrationState) -> dict[str, Any]:
        return schema_mapping(state, deps)

    def _gate(state: RegistrationState) -> dict[str, Any]:
        return confidence_gate(state, deps)

    def _assisted(state: RegistrationState) -> dict[str, Any]:
        return sample_assisted_mapping(state, deps)

    def _assemble(state: RegistrationState) -> dict[str, Any]:
        return assemble_mappings(state, deps)

    def _quality(state: RegistrationState) -> dict[str, Any]:
        return field_quality(state, deps)

    def _extract(state: RegistrationState) -> dict[str, Any]:
        return extraction_generation(state, deps)

    def _clean(state: RegistrationState) -> dict[str, Any]:
        return cleaning_generation(state, deps)

    def _test_rules(state: RegistrationState) -> dict[str, Any]:
        return rule_validation(state, deps)

    def _assemble_result(state: RegistrationState) -> dict[str, Any]:
        return result_assembly(state, deps)

    graph.add_node("validate_sample", _validate)
    graph.add_node("inspect_schema", _inspect)
    graph.add_node("sample_mapping", _sample_map)
    graph.add_node("schema_mapping", _schema_map)
    graph.add_node("confidence_gate", _gate)
    graph.add_node("sample_assisted", _assisted)
    graph.add_node("assemble_mappings", _assemble)
    graph.add_node("field_quality", _quality)
    graph.add_node("extraction_generation", _extract)
    graph.add_node("cleaning_generation", _clean)
    graph.add_node("rule_validation", _test_rules)
    graph.add_node("result_assembly", _assemble_result)

    graph.add_edge(START, "validate_sample")
    graph.add_conditional_edges(
        "validate_sample",
        lambda state: "end" if state.get("status") == "failed" else "inspect_schema",
        {"inspect_schema": "inspect_schema", "end": END},
    )
    graph.add_conditional_edges(
        "inspect_schema",
        _route_after_inspect,
        {"schema_mapping": "schema_mapping", "sample_mapping": "sample_mapping", "end": END},
    )
    graph.add_conditional_edges(
        "schema_mapping",
        lambda state: "end" if state.get("status") == "failed" else "confidence_gate",
        {"confidence_gate": "confidence_gate", "end": END},
    )
    graph.add_conditional_edges(
        "sample_mapping",
        lambda state: "end" if state.get("status") == "failed" else "assemble_mappings",
        {"assemble_mappings": "assemble_mappings", "end": END},
    )
    graph.add_conditional_edges(
        "confidence_gate",
        lambda state: "sample_assisted" if state.get("retry_fields") else "assemble_mappings",
        {"sample_assisted": "sample_assisted", "assemble_mappings": "assemble_mappings"},
    )
    graph.add_conditional_edges(
        "sample_assisted",
        lambda state: "end" if state.get("status") == "failed" else "assemble_mappings",
        {"assemble_mappings": "assemble_mappings", "end": END},
    )
    graph.add_edge("assemble_mappings", "field_quality")
    graph.add_edge("field_quality", "extraction_generation")
    graph.add_edge("extraction_generation", "cleaning_generation")
    graph.add_edge("cleaning_generation", "rule_validation")
    graph.add_edge("rule_validation", "result_assembly")
    graph.add_edge("result_assembly", END)
    return graph.compile()


def _route_after_inspect(state: RegistrationState) -> str:
    if state.get("status") == "failed":
        return "end"
    if state.get("mapping_mode") == "schema":
        return "schema_mapping"
    return "sample_mapping"


def run_registration(
    *,
    sample_rows: list[dict[str, Any]] | None = None,
    sample_path: str | None = None,
    source_schema: dict[str, Any] | str | None = None,
    source_schema_path: str | None = None,
    standard_schema: dict[str, Any] | None = None,
    standard_schema_path: str | None = None,
    source_name: str = "source_table",
    llm: Any | None = None,
    memory_path: str | Path | None = None,
    candidate_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root else find_repo_root()
    _llm_settings, rules = init_from_repo(root)
    if standard_schema is None and standard_schema_path:
        try:
            standard_schema = load_standard_schema(standard_schema_path)
        except SchemaError as exc:
            return _failed(str(exc))
    client = llm if llm is not None else LlmClient()
    deps = GraphDeps(
        rules=rules,
        memory=MappingMemory(memory_path or root / "data" / "mapping_memory.json"),
        skills=SkillRuntime(client),
        candidate_dir=Path(candidate_dir or root / "outputs" / "candidates"),
    )
    state: RegistrationState = {
        "sample_path": sample_path or "",
        "sample_rows": sample_rows or [],
        "source_schema_raw": source_schema,
        "source_schema_path": source_schema_path or "",
        "standard_schema": standard_schema or {},
        "source_name": source_name,
        "source_table": {},
        "source_fields": [],
        "source_samples": {},
        "mapping_mode": "",
        "initial_mappings": [],
        "assisted_mappings": [],
        "retry_fields": [],
        "final_mappings": [],
        "unmapped_fields": [],
        "field_quality_results": [],
        "extraction_rules": [],
        "cleaning_rules": [],
        "validation_results": [],
        "candidate_rules": [],
        "candidate_document": {},
        "candidate_path": "",
        "notices": [],
        "errors": [],
        "status": "running",
    }
    return build_graph(deps).invoke(state)


def _failed(message: str) -> dict[str, Any]:
    return {"status": "failed", "errors": [message], "candidate_path": "", "candidate_document": {}}
