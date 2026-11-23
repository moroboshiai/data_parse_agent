"""富化数据契约。事实和风险标签分开，模型不能自行宣布标签生效。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


ALLOWED_FIELDS = (
    "event_id",
    "event_type",
    "timestamp",
    "src_ip",
    "dst_ip",
    "domain",
    "dns_query_type",
    "response_code",
)

FACT_NAMES = ("内部资产", "重点资产", "情报命中")
RISK_NAMES = ("异常外联", "可疑域名", "恶意通信")
LABEL_STATUSES = (
    "auto_accepted",
    "needs_review",
    "rejected",
    "insufficient_evidence",
    "investigation_required",
)
STRATEGY_VERSION = "1.0.0"


class Subject(_Strict):
    type: Literal["ip", "domain"]
    value: str


class Evidence(_Strict):
    evidence_id: str
    evidence_type: Literal["asset", "threat_intel", "history"]
    subject: Subject
    result: dict[str, Any]
    source: str
    retrieved_at: str = ""


class Fact(_Strict):
    name: Literal["内部资产", "重点资产", "情报命中"]
    value: str
    evidence_ids: list[str] = Field(default_factory=list)


class RiskLabel(_Strict):
    name: Literal["异常外联", "可疑域名", "恶意通信"]
    confidence: Literal["low", "medium", "high"] = "low"
    status: Literal[
        "auto_accepted",
        "needs_review",
        "rejected",
        "insufficient_evidence",
        "investigation_required",
    ]
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class EnrichmentRecord(_Strict):
    event_id: str
    strategy_version: str = STRATEGY_VERSION
    event_type: str = ""
    timestamp: str = ""
    src_ip: str = ""
    dst_ip: str = ""
    domain: str = ""
    facts: list[Fact] = Field(default_factory=list)
    labels: list[RiskLabel] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    investigation_status: Literal["not_required", "investigation_required"] = "not_required"


class LabelDecision(_Strict):
    name: str
    decision: Literal["accept", "reject", "insufficient"]
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class EventJudgement(_Strict):
    event_id: str
    labels: list[LabelDecision] = Field(default_factory=list)


class ClassificationResult(_Strict):
    judgements: list[EventJudgement] = Field(default_factory=list)


class ToolAction(_Strict):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    purpose: str = ""


class InvestigationPlan(_Strict):
    reasoning_summary: str = ""
    actions: list[ToolAction] = Field(default_factory=list)
    stop: bool = False


class InvestigationSummary(_Strict):
    recommendation: str = ""
    missing_evidence: list[str] = Field(default_factory=list)
    labels: list[LabelDecision] = Field(default_factory=list)
