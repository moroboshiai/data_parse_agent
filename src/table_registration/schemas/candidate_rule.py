"""候选映射规则。候选、已确认、生效规则用状态区分。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CandidateMapping(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_field: str
    target_field: str
    explanation: str
    confidence: Literal["high", "medium", "low"]
    evidence: list[str] = Field(default_factory=list)
    basis: list[str] = Field(default_factory=list)
    quality: dict[str, Any] = Field(default_factory=dict)
    extraction_rule: dict[str, Any] | None = None
    cleaning_rule: dict[str, Any] | None = None
    validation: dict[str, Any] = Field(default_factory=dict)
    status: str
    version: int = 1


class CandidateDocument(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidate_id: str
    status: str
    source_table: dict[str, Any]
    standard_schema_id: str
    mapping_mode: str
    mappings: list[CandidateMapping]
    unmapped_fields: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)
    created_at: str = ""
