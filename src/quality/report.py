"""根据检测摘要组装报告。叙述由模型填写，质量等级以规则结果为准。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4
from quality.schemas import QualityNarrative, QualityProfile
from quality.timing import zone

_DIMENSIONS = ("completeness", "validity", "consistency", "uniqueness", "timeliness")
_STATUS_RANK = {"ok": 0, "warning": 1, "critical": 2}


def new_report_id(source_id: str) -> str:
    stamp = datetime.now(zone("Asia/Shanghai")).strftime("%Y%m%d%H%M%S")
    return f"QR-{source_id}-{stamp}-{uuid4().hex[:6]}"


def program_status(issues: list[dict[str, Any]]) -> str:
    if any(item.get("severity") == "high" for item in issues):
        return "critical"
    if issues:
        return "warning"
    return "ok"


def stronger_status(program: str, narrative: str) -> str:
    if _STATUS_RANK.get(narrative, 0) > _STATUS_RANK.get(program, 0):
        return narrative if narrative in _STATUS_RANK else program
    return program


def build_report(
    *,
    profile: QualityProfile,
    inspection: dict[str, Any],
    issues: list[dict[str, Any]],
    actions: list[dict[str, str]],
    narrative: QualityNarrative,
    model_failed: bool,
    window_start: str,
    window_end: str,
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    selected = {item["action"] for item in actions}
    status = program_status(issues)
    if not model_failed:
        status = stronger_status(status, narrative.quality_status)
    summary = narrative.summary
    recommendations = list(narrative.recommendations)
    if model_failed:
        summary = summary or "模型不可用，报告只包含规则和统计结果。"
        recommendations = recommendations or ["根据字段异常率和样本人工复核。"]
    report: dict[str, Any] = {
        "report_id": new_report_id(profile.source_id),
        "source_id": profile.source_id,
        "category": profile.category,
        "time_range": {
            "start": window_start,
            "end": window_end,
            "time_field": profile.time_field,
            "timezone": profile.timezone,
        },
        "overview": {},
        "dimensions": {},
        "fields": [],
        "distributions": {},
        "issues": issues,
        "anomalies": [item for item in issues if item.get("issue_type") == "statistical"],
        "diagnosis": [],
        "recommendations": recommendations,
        "summary": summary,
        "quality_status": status,
        "model_failed": model_failed,
        "plan": actions,
        "decisions": decisions,
    }
    if "get_volume_stats" in selected:
        report["overview"] = {
            "total_count": inspection.get("total_count") or 0,
            "outside_count": inspection.get("outside_count") or 0,
            "time_invalid_count": inspection.get("time_invalid_count") or 0,
            "first_event_time": inspection.get("first_event_time") or "",
            "last_event_time": inspection.get("last_event_time") or "",
            "hourly_count": inspection.get("hourly_count") or {},
            "quality_status": status,
            "ingest_delay": None,
        }
    results = inspection.get("rule_results") or []
    report["dimensions"] = {name: _dimension(results, name) for name in _DIMENSIONS}
    if "get_field_quality_stats" in selected:
        report["fields"] = [_field_section(profile, inspection, results, field.field) for field in profile.fields]
    if "get_distribution_stats" in selected:
        report["distributions"] = inspection.get("distribution_top") or {}
    return report


def _dimension(results: list[dict[str, Any]], name: str) -> dict[str, Any]:
    related = [item for item in results if item.get("dimension") == name and item.get("status") == "completed"]
    checked = sum(int(item.get("pass_count") or 0) + int(item.get("fail_count") or 0) for item in related)
    failed = sum(int(item.get("fail_count") or 0) for item in related)
    return {
        "rule_count": len(related),
        "fail_count": failed,
        "fail_rate": (failed / checked) if checked else 0,
        "triggered_rules": [item.get("rule_id") for item in related if item.get("triggered")],
    }


def _field_section(profile: QualityProfile, inspection: dict[str, Any], results: list[dict[str, Any]], field_name: str) -> dict[str, Any]:
    meta = next((item for item in profile.fields if item.field == field_name), None)
    null_result = _match(results, field_name, "field_empty")
    invalid_result = next((item for item in results if item.get("field") == field_name and item.get("operator") in {"validate_ip", "validate_domain", "validate_time", "validate_number"}), None)
    enum_result = _match(results, field_name, "validate_enum")
    return {
        "field": field_name,
        "comment": meta.comment if meta else "",
        "quality_level": meta.quality_level if meta else "",
        "total_count": inspection.get("total_count") or 0,
        "null_count": null_result.get("fail_count") if null_result else 0,
        "null_rate": null_result.get("fail_rate") if null_result else 0,
        "invalid_count": invalid_result.get("fail_count") if invalid_result else 0,
        "invalid_rate": invalid_result.get("fail_rate") if invalid_result else 0,
        "unknown_enum_count": enum_result.get("unknown_count") if enum_result else 0,
    }


def _match(results: list[dict[str, Any]], field_name: str, operator: str) -> dict[str, Any] | None:
    return next((item for item in results if item.get("field") == field_name and item.get("operator") == operator), None)
