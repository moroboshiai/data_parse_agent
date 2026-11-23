"""质量分析与规则草稿。映射阶段不得使用这些模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FieldQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_field: str
    target_field: str
    direct_mapping: bool = False
    needs_extraction: bool = False
    needs_cleaning: bool = False
    analysis: str = ""
    extraction_goal: str = ""
    cleaning_goal: str = ""
    issues: list[str] = Field(default_factory=list)


class ExtractionRuleDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_field: str
    target_field: str
    rule_type: Literal["regex"] = "regex"
    pattern: str
    group: int = 1
    expected_type: str = "string"
    description: str = ""


class CleaningRuleDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_field: str
    target_field: str
    rule_type: str = "operator"
    operator: Literal["trim", "normalize_datetime", "lower", "upper", "collapse_whitespace"]
    input_formats: list[str] = Field(default_factory=list)
    output_format: str = ""
    expression: str = ""
    idempotent: bool = True
    description: str = ""
