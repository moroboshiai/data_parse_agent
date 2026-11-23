"""标签采纳策略。没有可追溯证据的风险判断不能自动生效。"""

from __future__ import annotations

from typing import Any

from enrichment.schemas import RISK_NAMES


def apply_policy(
    *,
    event_id: str,
    facts: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    judgement: dict[str, Any] | None,
    model_failed: bool,
    strategy_version: str,
) -> dict[str, Any]:
    known = {item["evidence_id"] for item in evidence}
    labels: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.get("deterministic"):
            labels.append(_from_candidate(candidate, known))
            continue
        if candidate.get("knowledge_free"):
            label = _from_content(candidate, judgement, model_failed)
            if label:
                labels.append(label)
            continue
        labels.append(_from_model(candidate, judgement, known, model_failed))
    investigation = "investigation_required" if any(item["status"] == "investigation_required" for item in labels) else "not_required"
    return {
        "event_id": event_id,
        "strategy_version": strategy_version,
        "facts": facts,
        "labels": [item for item in labels if item["name"] in RISK_NAMES],
        "evidence": evidence,
        "investigation_status": investigation,
    }


def _from_candidate(candidate: dict[str, Any], known: set[str]) -> dict[str, Any]:
    evidence_ids = [item for item in candidate.get("evidence_ids") or [] if item in known]
    status = candidate.get("status") or "needs_review"
    if not evidence_ids:
        status = "rejected"
    elif status == "auto_accepted" and candidate.get("confidence") != "high":
        status = "needs_review"
    return {
        "name": candidate["name"],
        "confidence": candidate.get("confidence") or "low",
        "status": status,
        "evidence_ids": evidence_ids,
        "reason": candidate.get("reason") or "",
    }


def _from_content(candidate: dict[str, Any], judgement: dict[str, Any] | None, model_failed: bool) -> dict[str, Any] | None:
    if model_failed or judgement is None:
        return None
    name = candidate["name"]
    matched = next((item for item in judgement.get("labels") or [] if item.get("name") == name), None)
    if matched is None or matched.get("decision") != "accept":
        return None
    return _content_label(name, "needs_review", "medium", str(matched.get("reason") or "模型根据事件内容判断"))


def _content_label(name: str, status: str, confidence: str, reason: str) -> dict[str, Any]:
    return {"name": name, "confidence": confidence, "status": status, "evidence_ids": [], "reason": reason}


def _from_model(
    candidate: dict[str, Any],
    judgement: dict[str, Any] | None,
    known: set[str],
    model_failed: bool,
) -> dict[str, Any]:
    if model_failed or judgement is None:
        return {
            "name": candidate["name"],
            "confidence": "low",
            "status": "insufficient_evidence",
            "evidence_ids": [item for item in candidate.get("evidence_ids") or [] if item in known],
            "reason": "模型不可用，不能凭名称或语义下结论",
        }
    matched = next((item for item in judgement.get("labels") or [] if item.get("name") == candidate["name"]), None)
    if matched is None:
        return {
            "name": candidate["name"],
            "confidence": "low",
            "status": "insufficient_evidence",
            "evidence_ids": [],
            "reason": "模型未判断该候选标签",
        }
    evidence_ids = [item for item in matched.get("evidence_ids") or [] if item in known]
    decision = matched.get("decision")
    if decision == "reject":
        status = "rejected"
    elif decision == "insufficient" or not evidence_ids:
        status = "rejected" if decision == "accept" and not evidence_ids else "insufficient_evidence"
    else:
        status = "needs_review"
    if decision == "accept" and not evidence_ids:
        status = "rejected"
    return {
        "name": candidate["name"],
        "confidence": "medium" if status == "needs_review" else "low",
        "status": status,
        "evidence_ids": evidence_ids,
        "reason": str(matched.get("reason") or ""),
    }
