"""把触发的规则收成质量问题。问题单独保存，不回写原始记录。"""

from __future__ import annotations

import hashlib
from typing import Any


def build_issues(
    inspection: dict[str, Any],
    *,
    selected_groups: set[str],
    window_start: str = "",
    window_end: str = "",
) -> list[dict[str, Any]]:
    issues = []
    for result in inspection.get("rule_results") or []:
        if not result.get("triggered") or result.get("status") != "completed":
            continue
        if result.get("group") not in selected_groups:
            continue
        issues.append(_issue(inspection, result, window_start, window_end))
    return issues


def _issue(inspection: dict[str, Any], result: dict[str, Any], window_start: str, window_end: str) -> dict[str, Any]:
    source_id = str(inspection.get("source_id") or "")
    rule_id = str(result.get("rule_id") or "")
    raw = "|".join([source_id, rule_id, window_start, window_end])
    return {
        "issue_id": "QI-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12],
        "source_id": source_id,
        "category": inspection.get("category") or "",
        "rule_id": rule_id,
        "rule_version": result.get("rule_version") or "",
        "dimension": result.get("dimension") or "",
        "field_name": result.get("field") or "",
        "severity": result.get("severity") or "medium",
        "issue_type": "statistical" if result.get("operator") in {"compare_metric", "compare_baseline", "compare_distribution"} else "rule",
        "issue_title": result.get("rule_name") or rule_id,
        "issue_description": _description(result),
        "total_count": result.get("total_count") or 0,
        "abnormal_count": result.get("fail_count") or 0,
        "abnormal_rate": result.get("fail_rate") or 0,
        "first_seen": inspection.get("first_event_time") or window_start,
        "last_seen": inspection.get("last_event_time") or window_end,
        "window_start": window_start,
        "window_end": window_end,
        "status": "discovered",
        "evidence": result.get("evidence") or {},
    }


def _description(result: dict[str, Any]) -> str:
    evidence = result.get("evidence") or {}
    if "threshold" in evidence:
        return f"{result.get('rule_name')}：观测值 {evidence.get('observed')}，阈值 {evidence.get('comparison')} {evidence.get('threshold')}"
    if "ratio" in evidence:
        return f"{result.get('rule_name')}：当前 {evidence.get('observed')}，基线 {evidence.get('baseline')}，比值 {evidence.get('ratio')}"
    if "delta" in evidence:
        return f"{result.get('rule_name')}：分布最大偏差 {evidence.get('delta')}"
    return f"{result.get('rule_name')}：异常 {result.get('fail_count')} / {result.get('total_count')}"
