"""对已发现的质量问题收集证据并形成诊断。没有证据的假设保持未验证。"""

from __future__ import annotations

from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from quality.evidence import collect_evidence, verify_hypotheses
from quality.schemas import DiagnosisDraft, GovernanceDraft
from quality.skills import QualitySkills
from quality.store import save_diagnosis, save_issue, save_task
from table_registration.llm import LlmError


class DiagnoseState(TypedDict, total=False):
    issue: dict[str, Any]
    evidence: list[dict[str, Any]]
    verified: list[dict[str, Any]]
    unverified: list[dict[str, Any]]
    summary: str
    model_failed: bool
    diagnosis: dict[str, Any]
    task: dict[str, Any]
    output_dir: str


def run_diagnose(
    *,
    issue: dict[str, Any],
    llm: Any,
    output_dir: str,
    repository: str | None = None,
) -> dict[str, Any]:
    graph = _graph(QualitySkills(llm), repository)
    state = graph.invoke(
        {
            "issue": issue,
            "evidence": [],
            "verified": [],
            "unverified": [],
            "summary": "",
            "model_failed": False,
            "diagnosis": {},
            "task": {},
            "output_dir": output_dir,
        }
    )
    return {"diagnosis": state.get("diagnosis") or {}, "task": state.get("task") or {}}


def _graph(skills: QualitySkills, repository: str | None):
    graph = StateGraph(DiagnoseState)

    def gather(state: DiagnoseState) -> dict[str, Any]:
        return {"evidence": collect_evidence(state.get("issue") or {}, repository)}

    def hypothesize(state: DiagnoseState) -> dict[str, Any]:
        issue = state.get("issue") or {}
        evidence = list(state.get("evidence") or [])
        try:
            draft = skills.run(
                "quality-diagnosis",
                {
                    "issue": {
                        "issue_id": issue.get("issue_id"),
                        "rule_id": issue.get("rule_id"),
                        "field_name": issue.get("field_name"),
                        "issue_title": issue.get("issue_title"),
                        "abnormal_rate": issue.get("abnormal_rate"),
                    },
                    "evidence": evidence,
                    "instruction": "每个假设的 evidence_ids 必须来自给定证据。不能把质量异常直接说成攻击。",
                },
                DiagnosisDraft,
            )
        except (LlmError, ValidationError):
            return {"model_failed": True, "verified": [], "unverified": [], "summary": "模型不可用，仅保留证据。"}
        verified, unverified = verify_hypotheses([item.model_dump() for item in draft.hypotheses], evidence)
        return {"verified": verified, "unverified": unverified, "summary": draft.summary}

    def recommend(state: DiagnoseState) -> dict[str, Any]:
        issue = dict(state.get("issue") or {})
        verified = list(state.get("verified") or [])
        model_failed = bool(state.get("model_failed"))
        draft = GovernanceDraft(description="模型不可用，需要人工根据证据复核。" if model_failed else "")
        if not model_failed:
            try:
                draft = skills.run(
                    "governance-recommendation",
                    {
                        "issue_id": issue.get("issue_id"),
                        "verified_causes": verified,
                        "unverified_causes": state.get("unverified") or [],
                        "instruction": "只建议由哪个治理环节复核。不要直接修改规则，不要给出攻击结论。",
                    },
                    GovernanceDraft,
                )
            except (LlmError, ValidationError):
                model_failed = True
                draft = GovernanceDraft(description="模型不可用，需要人工根据证据复核。")
        if not verified:
            draft.target_agent = "human_review"
        diagnosis_id = "QD-" + uuid4().hex[:12]
        task_id = "QT-" + uuid4().hex[:12]
        diagnosis = {
            "diagnosis_id": diagnosis_id,
            "issue_id": issue.get("issue_id"),
            "source_id": issue.get("source_id"),
            "category": issue.get("category"),
            "hypotheses": verified + list(state.get("unverified") or []),
            "evidence": state.get("evidence") or [],
            "verified_causes": verified,
            "unverified_causes": state.get("unverified") or [],
            "diagnosis_summary": state.get("summary") or draft.description,
            "recommendations": [draft.description] if draft.description else [],
            "model_failed": model_failed,
        }
        task = {
            "task_id": task_id,
            "issue_id": issue.get("issue_id"),
            "diagnosis_id": diagnosis_id,
            "target_agent": draft.target_agent or "human_review",
            "target_source_id": issue.get("source_id"),
            "target_fields": [issue.get("field_name")] if issue.get("field_name") else [],
            "task_type": draft.task_type or "review",
            "task_description": draft.description,
            "expected_result": draft.expected_result,
            "verification_plan": draft.verification_metrics,
            "status": "pending",
        }
        issue["status"] = "confirmed" if verified else "diagnosing"
        output = state.get("output_dir") or ""
        save_diagnosis(output, diagnosis)
        save_task(output, task)
        save_issue(output, issue)
        return {"diagnosis": diagnosis, "task": task, "model_failed": model_failed}

    graph.add_node("gather", gather)
    graph.add_node("hypothesize", hypothesize)
    graph.add_node("recommend", recommend)
    graph.add_edge(START, "gather")
    graph.add_edge("gather", "hypothesize")
    graph.add_edge("hypothesize", "recommend")
    graph.add_edge("recommend", END)
    return graph.compile()
