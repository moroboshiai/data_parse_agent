"""批量富化。实体查询和规则先执行，只有定不了的候选才问模型。"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from enrichment.adapt import adapt_events
from enrichment.entities import extract_entities
from enrichment.knowledge import KnowledgeBase
from enrichment.policy import apply_policy
from enrichment.rules import screen
from enrichment.schemas import RISK_NAMES, STRATEGY_VERSION, ClassificationResult
from enrichment.skill_runtime import EnrichmentSkills
from enrichment.store import save_records
from table_registration.llm import LlmError


class BatchState(TypedDict, total=False):
    events: list[dict[str, Any]]
    contexts: list[dict[str, Any]]
    judgements: list[dict[str, Any]]
    model_failed: bool
    records: list[dict[str, Any]]
    output_dir: str
    strategy_version: str


def run_batch(
    *,
    events: list[dict[str, Any]],
    knowledge: KnowledgeBase,
    llm: Any,
    output_dir: str,
    strategy_version: str = STRATEGY_VERSION,
) -> list[dict[str, Any]]:
    graph = _graph(knowledge, EnrichmentSkills(llm))
    state = graph.invoke(
        {
            "events": events,
            "contexts": [],
            "judgements": [],
            "model_failed": False,
            "records": [],
            "output_dir": output_dir,
            "strategy_version": strategy_version,
        }
    )
    return list(state.get("records") or [])


def _graph(knowledge: KnowledgeBase, skills: EnrichmentSkills):
    graph = StateGraph(BatchState)

    def validate(state: BatchState) -> dict[str, Any]:
        return {"events": adapt_events(list(state.get("events") or []))}

    def prepare(state: BatchState) -> dict[str, Any]:
        contexts = []
        ips: list[str] = []
        domains: list[str] = []
        extracted = []
        for event in state.get("events") or []:
            entities = extract_entities(event)
            extracted.append(entities)
            for ip in entities["ips"]:
                if ip not in ips:
                    ips.append(ip)
            for domain in entities["domains"]:
                if domain not in domains:
                    domains.append(domain)
        if knowledge.is_empty:
            for event, entities in zip(state.get("events") or [], extracted):
                contexts.append(
                    {
                        "event": event,
                        "entities": entities,
                        "evidence": [],
                        "facts": [],
                        "candidates": _content_candidates(),
                        "needs_model": True,
                        "knowledge_free": True,
                    }
                )
            return {"contexts": contexts}
        ip_evidence = {ip: knowledge.evidence_for_ip(ip) for ip in ips}
        domain_evidence = {domain: knowledge.evidence_for_domain(domain) for domain in domains}
        for event, entities in zip(state.get("events") or [], extracted):
            evidence = _dedupe(
                [item for ip in entities["ips"] for item in ip_evidence.get(ip, [])]
                + [item for domain in entities["domains"] for item in domain_evidence.get(domain, [])]
            )
            result = screen(evidence)
            contexts.append({"event": event, "entities": entities, "evidence": evidence, "knowledge_free": False, **result})
        return {"contexts": contexts}

    def classify(state: BatchState) -> dict[str, Any]:
        pending = [item for item in state.get("contexts") or [] if item.get("needs_model")]
        if not pending:
            return {"judgements": [], "model_failed": False}
        judgements: list[dict[str, Any]] = []
        failed = False
        for chunk in _chunks(pending, 20):
            payload = {
                "events": [
                    {
                        "event": item["event"],
                        "evidence": item["evidence"],
                        "facts": item["facts"],
                        "label_without_knowledge": bool(item.get("knowledge_free")),
                        "candidate_labels": [candidate["name"] for candidate in item["candidates"] if not candidate["deterministic"]],
                    }
                    for item in chunk
                ]
            }
            try:
                result = skills.run("security-label-classification", payload, ClassificationResult)
            except (LlmError, ValidationError):
                failed = True
                continue
            judgements.extend(item.model_dump() for item in result.judgements)
        return {"judgements": judgements, "model_failed": failed and not judgements}

    def decide(state: BatchState) -> dict[str, Any]:
        by_event = {item["event_id"]: item for item in state.get("judgements") or []}
        records = []
        for item in state.get("contexts") or []:
            record = apply_policy(
                event_id=item["event"]["event_id"],
                facts=item["facts"],
                evidence=item["evidence"],
                candidates=item["candidates"],
                judgement=by_event.get(item["event"]["event_id"]),
                model_failed=bool(state.get("model_failed")),
                strategy_version=state.get("strategy_version") or STRATEGY_VERSION,
            )
            records.append(_with_event(record, item["event"]))
        return {"records": records}

    def persist(state: BatchState) -> dict[str, Any]:
        save_records(state.get("output_dir") or "", state.get("records") or [], state.get("strategy_version") or STRATEGY_VERSION)
        return {}

    graph.add_node("validate", validate)
    graph.add_node("prepare", prepare)
    graph.add_node("classify", classify)
    graph.add_node("decide", decide)
    graph.add_node("persist", persist)
    graph.add_edge(START, "validate")
    graph.add_edge("validate", "prepare")
    graph.add_edge("prepare", "classify")
    graph.add_edge("classify", "decide")
    graph.add_edge("decide", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


def _with_event(record: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    for field in ("event_type", "timestamp", "src_ip", "dst_ip", "domain"):
        record[field] = str(event.get(field) or "")
    return record


def _content_candidates() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "evidence_ids": [],
            "deterministic": False,
            "confidence": "low",
            "status": "needs_review",
            "reason": "没有知识数据，由模型根据事件内容判断",
            "knowledge_free": True,
        }
        for name in RISK_NAMES
    ]


def _chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _dedupe(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in evidence:
        if item["evidence_id"] in seen:
            continue
        seen.add(item["evidence_id"])
        found.append(item)
    return found
