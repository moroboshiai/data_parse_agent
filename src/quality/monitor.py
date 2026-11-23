"""对比当前窗口和基线。只有高严重度问题才请求模型判断是否诊断。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from quality.diagnose import run_diagnose
from quality.engine import inspect_rows, snapshot
from quality.issues import build_issues
from quality.profile import load_profile
from quality.reader import iter_rows
from quality.rules.loader import load_rules
from quality.schemas import AnomalyDecision, QualityProfile
from quality.skills import QualitySkills
from quality.store import baseline_path, load_baseline, save_baseline, save_issue, save_metrics
from quality.timing import parse_bound
from table_registration.llm import LlmError


class MonitorState(TypedDict, total=False):
    input_path: str
    output_dir: str
    window_start: str
    window_end: str
    repository: str
    inspection: dict[str, Any]
    issues: list[dict[str, Any]]
    diagnoses: list[dict[str, Any]]
    model_failed: bool
    result: dict[str, Any]


def run_monitor(
    *,
    profile_path: str,
    input_path: str,
    llm: Any,
    output_dir: str,
    start: str = "",
    end: str = "",
    baseline_path_value: str = "",
    repository: str = "",
    rules_root: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    profile = load_profile(profile_path)
    rules = load_rules(profile.category, profile.source_id, rules_root)
    path = baseline_path_value or str(baseline_path(output_dir, profile.source_id, profile.category))
    graph = _graph(profile, rules, QualitySkills(llm), load_baseline(path), path, now)
    state = graph.invoke(
        {
            "input_path": input_path,
            "output_dir": output_dir,
            "window_start": start,
            "window_end": end,
            "repository": repository,
            "inspection": {},
            "issues": [],
            "diagnoses": [],
            "model_failed": False,
            "result": {},
        }
    )
    return dict(state.get("result") or {})


def _graph(
    profile: QualityProfile,
    rules: list[dict[str, Any]],
    skills: QualitySkills,
    baseline: dict[str, Any] | None,
    baseline_file: str,
    now: datetime | None,
):
    graph = StateGraph(MonitorState)

    def scan(state: MonitorState) -> dict[str, Any]:
        inspection = inspect_rows(
            iter_rows(state.get("input_path") or ""),
            rules,
            profile,
            start=parse_bound(state.get("window_start"), profile.timezone, is_end=False),
            end=parse_bound(state.get("window_end"), profile.timezone, is_end=True),
            baseline=baseline,
            now=now,
        )
        issues = build_issues(
            inspection,
            selected_groups={"run_field_rules", "run_relation_rules", "compare_baseline"},
            window_start=state.get("window_start") or "",
            window_end=state.get("window_end") or "",
        )
        output = state.get("output_dir") or ""
        for issue in issues:
            save_issue(output, issue)
        run_id = "QM-" + uuid4().hex[:12]
        save_metrics(output, run_id, inspection)
        save_baseline(baseline_file, {**snapshot(inspection), "source_id": profile.source_id, "category": profile.category, "total_count": inspection.get("total_count")})
        return {"inspection": inspection, "issues": issues}

    def review(state: MonitorState) -> dict[str, Any]:
        diagnoses = []
        model_failed = False
        checked = 0
        for issue in state.get("issues") or []:
            if issue.get("severity") != "high" or checked >= 3:
                continue
            checked += 1
            try:
                decision = skills.run(
                    "anomaly-analysis",
                    {
                        "issue": {
                            "issue_id": issue.get("issue_id"),
                            "title": issue.get("issue_title"),
                            "field_name": issue.get("field_name"),
                            "abnormal_rate": issue.get("abnormal_rate"),
                            "severity": issue.get("severity"),
                        },
                        "instruction": "只判断是否需要继续做质量溯源。不要把它解释成安全攻击。",
                    },
                    AnomalyDecision,
                )
            except (LlmError, ValidationError):
                model_failed = True
                break
            if not decision.needs_diagnosis:
                continue
            result = run_diagnose(
                issue=issue,
                llm=skills.llm,
                output_dir=state.get("output_dir") or "",
                repository=state.get("repository") or None,
            )
            diagnoses.append(result)
        inspection = state.get("inspection") or {}
        payload = {
            "source_id": profile.source_id,
            "category": profile.category,
            "total_count": inspection.get("total_count"),
            "issue_count": len(state.get("issues") or []),
            "issues": state.get("issues") or [],
            "diagnoses": diagnoses,
            "model_failed": model_failed,
            "baseline_path": baseline_file,
        }
        return {"diagnoses": diagnoses, "model_failed": model_failed, "result": payload}

    graph.add_node("scan", scan)
    graph.add_node("review", review)
    graph.add_edge(START, "scan")
    graph.add_edge("scan", "review")
    graph.add_edge("review", END)
    return graph.compile()
