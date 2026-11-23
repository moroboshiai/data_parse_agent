"""质检契约。模型只填写计划和叙述，不能自行宣布检测通过。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class FieldProfile(_Model):
    field: str
    data_type: str = "string"
    storage_type: str = "string"
    nullable: bool = True
    quality_level: str = "optional"
    comment: str = ""
    format: list[str] = Field(default_factory=list)
    enum_values: list[str] = Field(default_factory=list)
    check_rules: list[str] = Field(default_factory=list)


class QualityProfile(_Model):
    source_id: str
    category: str
    structure_version: str = "1"
    quality_profile_version: str = "1"
    time_field: str = ""
    time_formats: list[str] = Field(default_factory=lambda: ["iso8601"])
    timezone: str = "Asia/Shanghai"
    partition_fields: list[str] = Field(default_factory=list)
    distribution_dimensions: list[str] = Field(default_factory=list)
    duplicate_fields: list[str] = Field(default_factory=list)
    ingest_field: str = ""
    fields: list[FieldProfile] = Field(default_factory=list)


class PlannedAction(_Model):
    action: str
    reason: str = ""


class QualityPlan(_Model):
    actions: list[PlannedAction] = Field(default_factory=list)
    status: str = "planned"


class QualityNarrative(_Model):
    summary: str = ""
    quality_status: Literal["ok", "warning", "critical"] = "ok"
    recommendations: list[str] = Field(default_factory=list)


class AnomalyDecision(_Model):
    needs_diagnosis: bool = False
    reason: str = ""


class Hypothesis(_Model):
    statement: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class DiagnosisDraft(_Model):
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    summary: str = ""


class GovernanceDraft(_Model):
    target_agent: str = "human_review"
    task_type: str = "review"
    description: str = ""
    expected_result: str = ""
    verification_metrics: list[str] = Field(default_factory=list)


def dump_model(model: BaseModel) -> dict[str, Any]:
    return model.model_dump()
