"""解析反馈闭环。先诊断，再决定是否生成新版本；回归失败不替换生效规则。"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from data_parsing.operators.registry import execute
from data_parsing.repository import RuleRepository
from data_parsing.schemas import Diagnosis, RuleOptimization
from data_parsing.skill_runtime import ParsingSkills
from table_registration.llm import LlmError


class LearningState(TypedDict, total=False):
    pipeline_id: str
    events: list[dict[str, Any]]
    pending: list[dict[str, Any]]
    decisions: list[dict[str, Any]]


def learn_from_events(
    *,
    repository: RuleRepository,
    pipeline_id: str,
    llm: Any,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    selected = events if events is not None else repository.list_events(pipeline_id=pipeline_id, resolution="")
    graph = _graph(ParsingSkills(llm), repository)
    state = graph.invoke({"pipeline_id": pipeline_id, "events": selected, "pending": [], "decisions": []})
    decisions = list(state.get("decisions") or [])
    _store_decisions(repository, pipeline_id, decisions)
    return {"pipeline_id": pipeline_id, "decisions": decisions}


def regression_report(
    old_operator: str,
    old_params: dict[str, Any],
    new_operator: str,
    new_params: dict[str, Any],
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    originals = [item for item in samples if item.get("kind") == "original"]
    anomalies = [item for item in samples if item.get("kind") == "anomaly"]
    boundaries = [item for item in samples if item.get("kind") == "boundary"]
    counters = [item for item in samples if item.get("kind") == "counterexample"]
    original_rate = _rate(new_operator, new_params, originals)
    anomaly_rate = _anomaly_rate(old_operator, old_params, new_operator, new_params, anomalies)
    boundary_rate = _rate(new_operator, new_params, boundaries)
    false_rate = _false_rate(new_operator, new_params, counters)
    passed = bool(originals and anomalies) and original_rate == 1 and anomaly_rate == 1 and boundary_rate == 1 and false_rate == 0
    return {
        "passed": passed,
        "original_compatibility": original_rate,
        "anomaly_coverage": anomaly_rate,
        "boundary_rate": boundary_rate,
        "false_extraction_rate": false_rate,
        "empty_rate": 1 - original_rate if originals else 1,
        "failure_rate": 1 - original_rate if originals else 1,
    }


def _graph(skills: ParsingSkills, repository: RuleRepository):
    graph = StateGraph(LearningState)

    def diagnose(state: LearningState) -> dict[str, Any]:
        decisions = []
        pending = []
        for event in state.get("events") or []:
            action = _program_action(event)
            reason = "程序诊断"
            if not action:
                try:
                    opinion = skills.run("parsing-issue-diagnosis", event, Diagnosis)
                except (LlmError, ValidationError) as exc:
                    action = "record_only"
                    reason = f"诊断失败: {exc}"
                else:
                    action = opinion.action
                    reason = opinion.reason
            decisions.append({"event_id": event.get("event_id", ""), "action": action, "reason": reason, "event": event})
            if action == "optimize":
                pending.append(event)
            elif event.get("event_id"):
                repository.resolve_event(event["event_id"], action)
        return {"decisions": decisions, "pending": pending}

    def optimize(state: LearningState) -> dict[str, Any]:
        decisions = []
        seen: set[tuple[str, str]] = set()
        for event in state.get("pending") or []:
            key = (event.get("standard_field") or "", event.get("source_field") or "")
            if key in seen:
                continue
            seen.add(key)
            decisions.append(_optimize_event(repository, skills, state["pipeline_id"], event))
        return {"decisions": [*list(state.get("decisions") or []), *decisions]}

    graph.add_node("diagnose", diagnose)
    graph.add_node("optimize", optimize)
    graph.add_edge(START, "diagnose")
    graph.add_edge("diagnose", "optimize")
    graph.add_edge("optimize", END)
    return graph.compile()


def _optimize_event(repository: RuleRepository, skills: ParsingSkills, pipeline_id: str, event: dict[str, Any]) -> dict[str, Any]:
    rule_id = event.get("current_rule_id") or ""
    if not rule_id:
        return {"event_id": event.get("event_id", ""), "action": "record_only", "reason": "没有可优化的当前规则"}
    current = repository.version_of(rule_id, event.get("current_rule_version"))
    try:
        draft = skills.run(
            "rule-optimization",
            {"event": event, "current_operator": current["operator"], "current_params": current.get("params") or {}},
            RuleOptimization,
        )
    except (LlmError, ValidationError) as exc:
        return {"event_id": event.get("event_id", ""), "action": "record_only", "reason": f"规则优化失败: {exc}"}
    samples = repository.list_samples(rule_id=rule_id)
    samples.append(
        {
            "rule_id": rule_id,
            "standard_field": event.get("standard_field") or "",
            "kind": "anomaly",
            "value": event.get("raw_value"),
            "expected": event.get("expected"),
            "expect_failure": False,
        }
    )
    report = regression_report(current["operator"], current.get("params") or {}, draft.operator, draft.params, samples)
    version = repository.append_version(
        rule_id,
        {
            "operator": draft.operator,
            "params": draft.params,
            "test_status": "passed" if report["passed"] else "failed",
            "status": "canary" if report["passed"] else "candidate",
            "created_from": "agent_learning",
            "test_report": report,
        },
    )
    number = version["versions"][-1]["version"]
    if report["passed"]:
        repository.add_samples(samples[-1:])
        _attach_canary(repository, pipeline_id, event.get("standard_field") or "", rule_id, number)
        action = "canary"
    else:
        action = "rejected"
    if event.get("event_id"):
        repository.resolve_event(event["event_id"], action)
    return {"event_id": event.get("event_id", ""), "action": action, "rule_id": rule_id, "version": number, "report": report}


def _store_decisions(repository: RuleRepository, pipeline_id: str, decisions: list[dict[str, Any]]) -> None:
    try:
        pipeline = repository.get_pipeline(pipeline_id)
    except KeyError:
        return
    pipeline["learn_decisions"] = _public_decisions(decisions)
    repository.save_pipeline(pipeline)


def _public_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    for item in decisions:
        row = _public_decision(item)
        key = str(row.get("event_id") or "")
        if key and key in index:
            ordered[index[key]] = row
        else:
            if key:
                index[key] = len(ordered)
            ordered.append(row)
    return ordered


def _public_decision(item: dict[str, Any]) -> dict[str, Any]:
    action = str(item.get("action") or "")
    reason = str(item.get("reason") or "")
    report = item.get("report") if isinstance(item.get("report"), dict) else {}
    if action == "canary":
        summary = f"回归通过，{item.get('rule_id')} 版本 {item.get('version')} 已挂为灰度，生效规则未替换"
    elif action == "rejected":
        summary = "回归未通过，新版本只保留为候选，未挂灰度"
    elif action == "reregister":
        summary = reason or "字段含义变化，需要重新注册"
    elif action == "record_only":
        summary = reason or "只记录，不修改规则"
    elif action == "optimize":
        summary = reason or "诊断为可以优化规则"
    else:
        summary = reason or action
    if report:
        summary += f"。原样本兼容 {report.get('original_compatibility')}，新样本覆盖 {report.get('anomaly_coverage')}"
    return {
        "event_id": item.get("event_id") or "",
        "action": action,
        "summary": summary,
        "rule_id": item.get("rule_id") or "",
        "version": item.get("version"),
    }


def _attach_canary(repository: RuleRepository, pipeline_id: str, standard_field: str, rule_id: str, version: int) -> None:
    pipeline = repository.get_pipeline(pipeline_id)
    for field in pipeline.get("fields") or []:
        if field.get("standard_field") == standard_field:
            field["canary_rule_id"] = rule_id
            field["canary_version"] = version
            field["canary_ratio"] = 0.2
    repository.save_pipeline(pipeline)


def _program_action(event: dict[str, Any]) -> str:
    if event.get("issue_type") == "semantic_change":
        return "reregister"
    if event.get("issue_type") in {"incomplete", "sporadic"} or event.get("raw_value") in (None, ""):
        return "record_only"
    return ""


def _rate(operator: str, params: dict[str, Any], samples: list[dict[str, Any]]) -> float:
    if not samples:
        return 1
    passed = 0
    for sample in samples:
        result = execute(operator, sample.get("value"), params)
        if sample.get("expect_failure"):
            passed += int(not result.ok)
        elif sample.get("expected") is not None:
            passed += int(result.ok and result.value == sample.get("expected"))
        else:
            passed += int(result.ok and result.value not in (None, ""))
    return passed / len(samples)


def _anomaly_rate(old_operator: str, old_params: dict[str, Any], new_operator: str, new_params: dict[str, Any], samples: list[dict[str, Any]]) -> float:
    if not samples:
        return 0
    passed = 0
    for sample in samples:
        old = execute(old_operator, sample.get("value"), old_params)
        new = execute(new_operator, sample.get("value"), new_params)
        expected = sample.get("expected")
        matches = new.ok and new.value not in (None, "") and (expected is None or new.value == expected)
        passed += int((not old.ok) and matches)
    return passed / len(samples)


def _false_rate(operator: str, params: dict[str, Any], samples: list[dict[str, Any]]) -> float:
    if not samples:
        return 0
    leaked = 0
    for sample in samples:
        result = execute(operator, sample.get("value"), params)
        leaked += int(result.ok)
    return leaked / len(samples)
