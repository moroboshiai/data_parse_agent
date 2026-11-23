"""为诊断收集有限证据。不把全表放进模型上下文。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def collect_evidence(issue: dict[str, Any], repository: str | Path | None = None) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    samples = ((issue.get("evidence") or {}).get("sample_invalid_values") or [])[:5]
    for index, sample in enumerate(samples):
        evidence.append({"evidence_id": f"sample-{index}", "kind": "sample", "detail": sample})
    evidence.append(
        {
            "evidence_id": "issue-metrics",
            "kind": "metric",
            "detail": {
                "rule_id": issue.get("rule_id"),
                "field_name": issue.get("field_name"),
                "abnormal_count": issue.get("abnormal_count"),
                "abnormal_rate": issue.get("abnormal_rate"),
                "total_count": issue.get("total_count"),
            },
        }
    )
    if repository:
        evidence.extend(_repository_evidence(Path(repository), str(issue.get("source_id") or ""), str(issue.get("category") or "")))
    return evidence


def verify_hypotheses(hypotheses: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    known = {str(item.get("evidence_id")) for item in evidence}
    verified = []
    unverified = []
    for item in hypotheses:
        ids = [str(value) for value in item.get("evidence_ids") or []]
        target = verified if ids and set(ids) <= known else unverified
        target.append({**item, "evidence_ids": ids, "status": "verified" if target is verified else "unverified"})
    return verified, unverified


def _repository_evidence(root: Path, source_id: str, category: str) -> list[dict[str, Any]]:
    found = []
    pipelines = _read_list(root / "pipelines.json", "pipelines")
    matched = [
        {
            "pipeline_id": item.get("pipeline_id"),
            "version": item.get("version"),
            "status": item.get("status"),
            "source_table": item.get("source_table"),
        }
        for item in pipelines
        if item.get("standard_schema_id") == source_id or item.get("source_table") == source_id or item.get("source_type") == category
    ][:5]
    if matched:
        found.append({"evidence_id": "pipeline-history", "kind": "pipeline", "detail": matched})
    pipeline_ids = {item.get("pipeline_id") for item in matched}
    events = [
        {
            "pipeline_id": item.get("pipeline_id"),
            "standard_field": item.get("standard_field"),
            "issue_type": item.get("issue_type"),
            "error": item.get("error"),
        }
        for item in _read_list(root / "events.json", "events")
        if item.get("pipeline_id") in pipeline_ids
    ][:5]
    if events:
        found.append({"evidence_id": "parse-events", "kind": "parse_event", "detail": events})
    return found


def _read_list(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    values = payload.get(key) if isinstance(payload, dict) else []
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []
