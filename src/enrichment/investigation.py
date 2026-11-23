"""单条调查。模型规划查询，程序校验后执行，事实仍由规则从证据生成。"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from enrichment.adapt import adapt_event
from enrichment.entities import extract_entities
from enrichment.knowledge import KnowledgeBase
from enrichment.policy import apply_policy
from enrichment.rules import screen
from enrichment.schemas import STRATEGY_VERSION, InvestigationPlan, InvestigationSummary
from enrichment.skill_runtime import EnrichmentSkills
from enrichment.store import save_report
from enrichment.tools import TOOL_CATALOG, execute_action, validate_action
from table_registration.llm import LlmError


class InvestigationState(TypedDict, total=False):
    event: dict[str, Any]
    entities: dict[str, list[str]]
    evidence: list[dict[str, Any]]
    executed: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    rounds: int
    max_rounds: int
    max_calls: int
    stop: bool
    budget_exhausted: bool
    model_failed: bool
    report: dict[str, Any]
    output_dir: str
    strategy_version: str


def run_investigation(
    *,
    event: dict[str, Any],
    knowledge: KnowledgeBase,
    llm: Any,
    output_dir: str,
    max_rounds: int = 3,
    max_calls: int = 6,
    strategy_version: str = STRATEGY_VERSION,
) -> dict[str, Any]:
    graph = _graph(knowledge, EnrichmentSkills(llm))
    state = graph.invoke(
        {
            "event": event,
            "entities": {"ips": [], "domains": []},
            "evidence": [],
            "executed": [],
            "decisions": [],
            "rounds": 0,
            "max_rounds": max_rounds,
            "max_calls": max_calls,
            "stop": False,
            "budget_exhausted": False,
            "model_failed": False,
            "report": {},
            "output_dir": output_dir,
            "strategy_version": strategy_version,
        }
    )
    return dict(state.get("report") or {})


def _graph(knowledge: KnowledgeBase, skills: EnrichmentSkills):
    graph = StateGraph(InvestigationState)

    def prepare(state: InvestigationState) -> dict[str, Any]:
        event = adapt_event(state.get("event") or {}, index=1)
        if not event:
            return {"stop": True, "model_failed": True, "event": {}}
        return {"event": event, "entities": extract_entities(event)}

    def plan(state: InvestigationState) -> dict[str, Any]:
        if state.get("stop") or not state.get("event"):
            return {"stop": True}
        payload = {
            "event": state.get("event"),
            "entities": state.get("entities"),
            "evidence": state.get("evidence") or [],
            "executed": state.get("executed") or [],
            "tools": TOOL_CATALOG,
            "remaining_rounds": int(state.get("max_rounds") or 0) - int(state.get("rounds") or 0),
            "remaining_calls": int(state.get("max_calls") or 0) - len(state.get("executed") or []),
        }
        try:
            result = skills.run("investigation-planning", payload, InvestigationPlan)
        except (LlmError, ValidationError):
            return {"stop": True, "model_failed": True}
        return {
            "stop": result.stop,
            "decisions": [*list(state.get("decisions") or []), {"round": int(state.get("rounds") or 0) + 1, "reasoning_summary": result.reasoning_summary, "proposed": [item.model_dump() for item in result.actions]}],
        }

    def execute(state: InvestigationState) -> dict[str, Any]:
        if state.get("stop") or not state.get("event"):
            return {"stop": True}
        proposal = (state.get("decisions") or [])[-1]
        actions = list(proposal.get("proposed") or [])
        executed = list(state.get("executed") or [])
        evidence = list(state.get("evidence") or [])
        outcomes = []
        for action in actions:
            if len(executed) >= int(state.get("max_calls") or 0):
                outcomes.append(_outcome(action, False, "超过调用预算"))
                continue
            accepted, reason, arguments = validate_action(
                action,
                entities=state.get("entities") or {"ips": [], "domains": []},
                evidence=evidence,
                executed=executed,
            )
            if not accepted:
                outcomes.append(_outcome(action, False, reason))
                continue
            found = execute_action(knowledge, str(action.get("tool")), arguments)
            evidence = _merge(evidence, found)
            executed.append({"tool": action.get("tool"), "arguments": arguments})
            outcomes.append(_outcome(action, True, "已执行"))
        rounds = int(state.get("rounds") or 0) + 1
        exhausted = rounds >= int(state.get("max_rounds") or 0) or len(executed) >= int(state.get("max_calls") or 0)
        ran = any(item["accepted"] for item in outcomes)
        decisions = list(state.get("decisions") or [])
        decisions[-1] = {**proposal, "outcomes": outcomes}
        return {
            "evidence": evidence,
            "executed": executed,
            "decisions": decisions,
            "rounds": rounds,
            "budget_exhausted": exhausted,
            "stop": (not ran) or exhausted,
        }

    def summarize(state: InvestigationState) -> dict[str, Any]:
        event = state.get("event") or {}
        if not event:
            report = {"event_id": "", "investigation_status": "needs_review", "facts": [], "labels": [], "evidence": [], "missing_evidence": [], "recommendation": "事件缺少 event_id", "decisions": []}
            return {"report": report}
        screened = screen(state.get("evidence") or [])
        summary = InvestigationSummary()
        model_failed = bool(state.get("model_failed"))
        if not model_failed:
            try:
                summary = skills.run(
                    "investigation-summary",
                    {"event": event, "evidence": state.get("evidence") or [], "facts": screened["facts"], "candidate_labels": [item["name"] for item in screened["candidates"] if not item["deterministic"]]},
                    InvestigationSummary,
                )
            except (LlmError, ValidationError):
                model_failed = True
        record = apply_policy(
            event_id=str(event.get("event_id") or ""),
            facts=screened["facts"],
            evidence=state.get("evidence") or [],
            candidates=screened["candidates"],
            judgement={"event_id": event.get("event_id"), "labels": [item.model_dump() for item in summary.labels]},
            model_failed=model_failed,
            strategy_version=state.get("strategy_version") or STRATEGY_VERSION,
        )
        needs_review = any(item["status"] == "needs_review" for item in record["labels"])
        if needs_review or model_failed:
            status = "needs_review"
        elif state.get("budget_exhausted"):
            status = "budget_exhausted"
        else:
            status = "completed"
        recommendation = summary.recommendation
        if model_failed:
            recommendation = "模型不可用，仅保留确定性查询结果"
        report = {
            "event_id": record["event_id"],
            "strategy_version": record["strategy_version"],
            "investigation_status": status,
            "facts": record["facts"],
            "labels": record["labels"],
            "evidence": record["evidence"],
            "missing_evidence": [] if model_failed else list(summary.missing_evidence),
            "recommendation": recommendation,
            "decisions": state.get("decisions") or [],
        }
        save_report(state.get("output_dir") or "", report)
        return {"report": report, "model_failed": model_failed}

    graph.add_node("prepare", prepare)
    graph.add_node("plan", plan)
    graph.add_node("execute", execute)
    graph.add_node("summarize", summarize)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "plan")
    graph.add_edge("plan", "execute")
    graph.add_conditional_edges("execute", lambda state: "summarize" if state.get("stop") else "plan", {"summarize": "summarize", "plan": "plan"})
    graph.add_edge("summarize", END)
    return graph.compile()


def _merge(current: list[dict[str, Any]], found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {item["evidence_id"] for item in current}
    merged = list(current)
    for item in found:
        if item["evidence_id"] not in seen:
            seen.add(item["evidence_id"])
            merged.append(item)
    return merged


def _outcome(action: dict[str, Any], accepted: bool, reason: str) -> dict[str, Any]:
    return {"tool": action.get("tool"), "arguments": action.get("arguments") or {}, "accepted": accepted, "reason": reason}
