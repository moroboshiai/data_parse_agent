"""指定时间范围的质量分析。检测由程序完成，模型只规划并写报告叙述。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from quality.engine import inspect_rows
from quality.issues import build_issues
from quality.planner import allowed_actions, fallback_actions, resolve_plan, selected_groups
from quality.profile import load_profile
from quality.reader import iter_rows
from quality.report import build_report
from quality.rules.loader import load_rules
from quality.schemas import QualityNarrative, QualityPlan, QualityProfile
from quality.skills import QualitySkills
from quality.store import load_baseline, save_issue, save_metrics, save_report
from quality.timing import parse_bound
from table_registration.llm import LlmError


class AnalyzeState(TypedDict, total=False):
    input_path: str
    output_dir: str
    window_start: str
    window_end: str
    allowed: list[str]
    accepted: list[dict[str, str]]
    decisions: list[dict[str, Any]]
    model_failed: bool
    inspection: dict[str, Any]
    issues: list[dict[str, Any]]
    report: dict[str, Any]


def run_analyze(
    *,
    profile_path: str,
    input_path: str,
    llm: Any,
    output_dir: str,
    start: str = "",
    end: str = "",
    baseline_path: str = "",
    rules_root: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    profile = load_profile(profile_path)
    rules = load_rules(profile.category, profile.source_id, rules_root)
    graph = _graph(profile, rules, QualitySkills(llm), load_baseline(baseline_path), now)
    state = graph.invoke(
        {
            "input_path": input_path,
            "output_dir": output_dir,
            "window_start": start,
            "window_end": end,
            "allowed": allowed_actions(profile),
            "accepted": [],
            "decisions": [],
            "model_failed": False,
            "inspection": {},
            "issues": [],
            "report": {},
        }
    )
    return dict(state.get("report") or {})


def _graph(
    profile: QualityProfile,
    rules: list[dict[str, Any]],
    skills: QualitySkills,
    baseline: dict[str, Any] | None,
    now: datetime | None,
):
    graph = StateGraph(AnalyzeState)

    def plan(state: AnalyzeState) -> dict[str, Any]:
        allowed = list(state.get("allowed") or [])
        payload = {
            "source_id": profile.source_id,
            "category": profile.category,
            "time_field": profile.time_field,
            "window_start": state.get("window_start") or "",
            "window_end": state.get("window_end") or "",
            "allowed_actions": allowed,
            "distribution_dimensions": profile.distribution_dimensions,
            "instruction": "只从 allowed_actions 里选择。不要发明查询，不要请求 SQL。数据量变化只作为质量现象。",
        }
        try:
            proposed = skills.run("quality-planning", payload, QualityPlan)
            accepted, rejected = resolve_plan(allowed, [item.model_dump() for item in proposed.actions])
            model_failed = False
        except (LlmError, ValidationError):
            accepted, rejected = fallback_actions(allowed), []
            model_failed = True
        return {
            "accepted": accepted,
            "model_failed": model_failed,
            "decisions": [{"accepted": accepted, "rejected": rejected, "model_failed": model_failed}],
        }

    def execute(state: AnalyzeState) -> dict[str, Any]:
        start = parse_bound(state.get("window_start"), profile.timezone, is_end=False)
        end = parse_bound(state.get("window_end"), profile.timezone, is_end=True)
        inspection = inspect_rows(
            iter_rows(state.get("input_path") or ""),
            rules,
            profile,
            start=start,
            end=end,
            baseline=baseline,
            now=now,
        )
        issues = build_issues(
            inspection,
            selected_groups=selected_groups(list(state.get("accepted") or [])),
            window_start=state.get("window_start") or "",
            window_end=state.get("window_end") or "",
        )
        return {"inspection": inspection, "issues": issues}

    def publish(state: AnalyzeState) -> dict[str, Any]:
        inspection = state.get("inspection") or {}
        issues = list(state.get("issues") or [])
        narrative = QualityNarrative()
        model_failed = bool(state.get("model_failed"))
        if not model_failed:
            payload = {
                "source_id": profile.source_id,
                "category": profile.category,
                "total_count": inspection.get("total_count"),
                "issues": [
                    {
                        "issue_id": item.get("issue_id"),
                        "title": item.get("issue_title"),
                        "severity": item.get("severity"),
                        "field_name": item.get("field_name"),
                        "abnormal_rate": item.get("abnormal_rate"),
                    }
                    for item in issues
                ],
                "instruction": "只根据给定指标总结数据质量。不要把数量或分布变化判定为攻击。",
            }
            try:
                narrative = skills.run("quality-analysis", payload, QualityNarrative)
            except (LlmError, ValidationError):
                model_failed = True
        report = build_report(
            profile=profile,
            inspection=inspection,
            issues=issues,
            actions=list(state.get("accepted") or []),
            narrative=narrative,
            model_failed=model_failed,
            window_start=state.get("window_start") or "",
            window_end=state.get("window_end") or "",
            decisions=list(state.get("decisions") or []),
        )
        output = state.get("output_dir") or ""
        save_report(output, report)
        save_metrics(output, report["report_id"], inspection)
        for issue in issues:
            save_issue(output, issue)
        return {"report": report, "model_failed": model_failed}

    graph.add_node("plan", plan)
    graph.add_node("execute", execute)
    graph.add_node("publish", publish)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "publish")
    graph.add_edge("publish", END)
    return graph.compile()
