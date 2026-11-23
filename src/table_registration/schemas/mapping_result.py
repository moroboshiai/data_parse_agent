"""映射阶段的结构化输出。禁止携带提取、清洗或治理字段。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceFieldModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: str
    field_name: str
    field_type: str = "unknown"
    description: str = ""


class NormalizedSourceSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_fields: list[SourceFieldModel]


class FieldMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_field: str
    target_field: str | None = None
    explanation: str = ""
    confidence: Literal["high", "medium", "low"] | None = None
    confidence_score: float | None = None
    evidence: list[str] = Field(default_factory=list)
    reason: str = ""
    needs_human_confirm: bool = False


class MappingBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mappings: list[FieldMapping]
