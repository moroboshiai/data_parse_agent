"""确定性初筛。资产事实不直接变成风险结论。"""

from __future__ import annotations

from typing import Any

TRUSTED_SOURCES = {"asset_database", "internal_threat_intel"}


def screen(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    facts: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    seen_facts: set[str] = set()
    for item in evidence:
        if item.get("evidence_type") != "asset":
            continue
        result = item.get("result") or {}
        if result.get("is_internal"):
            _add_fact(facts, seen_facts, "内部资产", str(result.get("asset_name") or "true"), item["evidence_id"])
        if result.get("is_key_asset"):
            _add_fact(facts, seen_facts, "重点资产", str(result.get("asset_level") or "true"), item["evidence_id"])
    for kind in ("domain", "ip"):
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in evidence:
            subject = item.get("subject") or {}
            if item.get("evidence_type") == "threat_intel" and subject.get("type") == kind:
                grouped.setdefault(str(subject.get("value") or ""), []).append(item)
        for items in grouped.values():
            _intel_candidate(items, facts, seen_facts, candidates)
    needs_model = any(not item["deterministic"] for item in candidates)
    return {"facts": facts, "candidates": candidates, "needs_model": needs_model}


def _intel_candidate(
    items: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    seen_facts: set[str],
    candidates: list[dict[str, Any]],
) -> None:
    statuses = {str((item.get("result") or {}).get("threat_status") or "") for item in items}
    evidence_ids = [item["evidence_id"] for item in items]
    if statuses & {"malicious", "suspicious"}:
        _add_fact(facts, seen_facts, "情报命中", ",".join(sorted(statuses)), evidence_ids[0])
    conflict = "benign" in statuses and bool(statuses & {"malicious", "suspicious"})
    confirmed = [
        item
        for item in items
        if (item.get("result") or {}).get("threat_status") == "malicious"
        and (item.get("result") or {}).get("confidence") == "high"
        and item.get("source") in TRUSTED_SOURCES
    ]
    if conflict:
        candidates.append(
            {
                "name": "恶意通信" if "malicious" in statuses else "可疑域名",
                "evidence_ids": evidence_ids,
                "deterministic": True,
                "confidence": "low",
                "status": "needs_review",
                "reason": "同一指标存在冲突情报",
            }
        )
        return
    if confirmed and statuses == {"malicious"}:
        candidates.append(
            {
                "name": "恶意通信",
                "evidence_ids": [item["evidence_id"] for item in confirmed],
                "deterministic": True,
                "confidence": "high",
                "status": "auto_accepted",
                "reason": "可信情报源确认恶意指标",
            }
        )
        return
    if "malicious" in statuses:
        candidates.append(
            {
                "name": "恶意通信",
                "evidence_ids": evidence_ids,
                "deterministic": True,
                "confidence": "medium",
                "status": "needs_review",
                "reason": "情报未达到自动采纳条件",
            }
        )
        return
    if "suspicious" in statuses:
        candidates.append(
            {
                "name": "可疑域名",
                "evidence_ids": evidence_ids,
                "deterministic": False,
                "confidence": "medium",
                "status": "needs_review",
                "reason": "可疑情报需要语义判断",
            }
        )


def _add_fact(facts: list[dict[str, Any]], seen: set[str], name: str, value: str, evidence_id: str) -> bool:
    if name in seen:
        return False
    seen.add(name)
    facts.append({"name": name, "value": value, "evidence_ids": [evidence_id]})
    return True
