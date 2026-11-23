"""表注册任务的共享状态。各节点只更新自己负责的字段。"""

from typing import Annotated, Any, TypedDict


def concat(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    return [*(left or []), *(right or [])]


class RegistrationState(TypedDict, total=False):
    sample_path: str
    sample_rows: list[dict[str, Any]]
    source_schema_raw: dict[str, Any] | str | None
    source_schema_path: str
    standard_schema: dict[str, Any]
    source_name: str
    source_table: dict[str, Any]
    source_fields: list[dict[str, Any]]
    source_samples: dict[str, list[Any]]
    mapping_mode: str
    initial_mappings: list[dict[str, Any]]
    assisted_mappings: list[dict[str, Any]]
    retry_fields: list[str]
    final_mappings: list[dict[str, Any]]
    unmapped_fields: list[dict[str, Any]]
    field_quality_results: list[dict[str, Any]]
    extraction_rules: list[dict[str, Any]]
    cleaning_rules: list[dict[str, Any]]
    validation_results: Annotated[list[str], concat]
    candidate_rules: list[dict[str, Any]]
    candidate_document: dict[str, Any]
    candidate_path: str
    notices: Annotated[list[str], concat]
    errors: Annotated[list[str], concat]
    status: str
