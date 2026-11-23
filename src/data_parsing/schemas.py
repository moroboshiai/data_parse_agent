"""解析 Skill 的结构化输出。不接受模型自行宣布规则生效。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


PlanAction = Literal[
    "passthrough",
    "use_existing",
    "reuse_generic",
    "use_seeded",
    "generate",
    "human_review",
    "return_to_registration",
]


class PlannedAction(_Strict):
    source_field: str
    standard_field: str
    action: PlanAction
    reason: str = ""


class PipelinePlan(_Strict):
    actions: list[PlannedAction] = Field(default_factory=list)


class ReuseOpinion(_Strict):
    reuse: bool
    rule_id: str = ""
    reason: str = ""


class RuleDraft(_Strict):
    standard_field: str
    source_field: str
    operator: str
    params: dict[str, Any] = Field(default_factory=dict)
    rule_type: str = "extraction"


class RuleOptimization(_Strict):
    operator: str
    params: dict[str, Any] = Field(default_factory=dict)
    rule_type: str = "extraction"
    reason: str = ""


class Diagnosis(_Strict):
    action: Literal["optimize", "record_only", "reregister"]
    reason: str = ""
    issue_type: str = ""


class QualityOpinion(_Strict):
    accept: bool = False
    reason: str = ""
