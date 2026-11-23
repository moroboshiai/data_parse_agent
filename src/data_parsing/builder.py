"""根据已确认注册结果构建 Pipeline 配置。不生成 Python 脚本。"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from data_parsing.handoff import seed_repository
from data_parsing.operators.registry import execute
from data_parsing.planner import (
    decision_record,
    inventory,
    planner_payload,
    resolve_actions,
    seeded_rule_id,
)
from data_parsing.policies import RulePolicyError, assert_operator
from data_parsing.repository import RuleRepository
from data_parsing.runtime import ParsingEngine
from data_parsing.schemas import PipelinePlan, ReuseOpinion, RuleDraft
from data_parsing.skill_runtime import ParsingSkills
from table_registration.llm import LlmError


class BuilderState(TypedDict, total=False):
    candidate: dict[str, Any]
    sample_rows: list[dict[str, Any]]
    samples: dict[str, list[Any]]
    source_type: str
    issues: list[dict[str, Any]]
    field_facts: list[dict[str, Any]]
    plan_actions: list[dict[str, Any]]
    field_steps: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    pipeline: dict[str, Any]
    metrics: dict[str, Any]
    errors: list[str]
    replan_count: int
    needs_replan: bool
    test_failures: int
    status: str


def build_pipeline(
    *,
    candidate: dict[str, Any],
    sample_rows: list[dict[str, Any]],
    source_type: str,
    llm: Any,
    repository: RuleRepository,
) -> dict[str, Any]:
    graph = _graph(ParsingSkills(llm), repository)
    state = graph.invoke(
        {
            "candidate": candidate,
            "sample_rows": sample_rows,
            "samples": _columns(sample_rows),
            "source_type": source_type,
            "issues": [],
            "field_facts": [],
            "plan_actions": [],
            "field_steps": [],
            "decisions": [],
            "pipeline": {},
            "metrics": {},
            "errors": [],
            "replan_count": 0,
            "needs_replan": False,
            "test_failures": 0,
            "status": "running",
        }
    )
    if state.get("status") == "failed" or not state.get("pipeline"):
        raise ValueError("；".join(state.get("errors") or ["Pipeline 构建失败"]))
    return state["pipeline"]


def _graph(skills: ParsingSkills, repository: RuleRepository):
    graph = StateGraph(BuilderState)

    def check(state: BuilderState) -> dict[str, Any]:
        if state["candidate"].get("status") != "confirmed":
            return {"status": "failed", "errors": ["只有已确认的注册结果可以构建 Pipeline"]}
        return {}

    def seed(state: BuilderState) -> dict[str, Any]:
        if state.get("status") == "failed":
            return {}
        issues = seed_repository(
            repository,
            state["candidate"],
            state["samples"],
            source_type=state["source_type"],
        )
        return {"issues": issues}

    def inspect(state: BuilderState) -> dict[str, Any]:
        if state.get("status") == "failed":
            return {}
        source_table = _source_table(state)
        facts = inventory(
            mappings=state["candidate"].get("mappings") or [],
            issues=state.get("issues") or [],
            repository=repository,
            source_table=source_table,
            source_type=state["source_type"],
            metrics=state.get("metrics") or {},
            replan=int(state.get("replan_count") or 0) > 0,
        )
        return {"field_facts": facts, "needs_replan": False}

    def plan(state: BuilderState) -> dict[str, Any]:
        if state.get("status") == "failed":
            return {}
        facts = state.get("field_facts") or []
        replan_count = int(state.get("replan_count") or 0)
        payload = planner_payload(
            facts,
            source_table=_source_table(state),
            source_type=state["source_type"],
            replan_count=replan_count,
        )
        try:
            result = skills.run("pipeline-planning", payload, PipelinePlan)
            proposed = [item.model_dump() for item in result.actions]
        except (LlmError, ValidationError):
            proposed = []
        actions = resolve_actions(facts, proposed)
        decisions = list(state.get("decisions") or [])
        for fact, action in zip(facts, actions):
            decisions.append(decision_record(fact, action, replan_count=replan_count))
        return {"plan_actions": actions, "decisions": decisions}

    def apply(state: BuilderState) -> dict[str, Any]:
        if state.get("status") == "failed":
            return {}
        previous = {(item["source_field"], item["standard_field"]): item for item in state.get("field_steps") or []}
        facts = {(item["source_field"], item["standard_field"]): item for item in state.get("field_facts") or []}
        steps = []
        errors: list[str] = []
        results: dict[tuple[str, str], str] = {}
        source_table = _source_table(state)
        for action in state.get("plan_actions") or []:
            key = (action["source_field"], action["standard_field"])
            fact = facts.get(key) or {}
            kept = previous.get(key)
            try:
                step, result = _apply_action(
                    action["action"],
                    fact,
                    kept,
                    repository=repository,
                    skills=skills,
                    values=state["samples"].get(action["source_field"], []),
                    source_table=source_table,
                    source_type=state["source_type"],
                )
            except (LlmError, ValidationError, RulePolicyError, ValueError) as exc:
                errors.append(f"{action['source_field']} 规则处理失败: {exc}")
                step = _field_step(action["source_field"], action["standard_field"], (kept or {}).get("rule_ids") or [])
                result = "failed"
            steps.append(step)
            results[key] = result
        replan_count = int(state.get("replan_count") or 0)
        decisions = []
        for item in state.get("decisions") or []:
            updated = dict(item)
            if updated.get("replan_count") == replan_count:
                key = (updated["observation"]["source_field"], updated["observation"]["standard_field"])
                updated["execution_result"] = results.get(key, updated.get("execution_result") or "")
            decisions.append(updated)
        return {"field_steps": steps, "errors": errors, "decisions": decisions, "status": "running"}

    def test(state: BuilderState) -> dict[str, Any]:
        if state.get("status") == "failed":
            return {}
        pipeline = _draft_pipeline(state)
        parsed = ParsingEngine(repository).parse(state["sample_rows"], pipeline)
        failures = sum(int(item["failure"]) for item in parsed["metrics"].values())
        flags = {item["action"] for item in state.get("plan_actions") or []}
        blocked = failures > 0 or bool(state.get("errors"))
        replan_count = int(state.get("replan_count") or 0)
        needs_replan = (
            "return_to_registration" not in flags
            and "human_review" not in flags
            and blocked
            and replan_count == 0
        )
        return {
            "pipeline": pipeline,
            "metrics": parsed["metrics"],
            "test_failures": failures,
            "needs_replan": needs_replan,
            "replan_count": replan_count + (1 if needs_replan else 0),
        }

    def save(state: BuilderState) -> dict[str, Any]:
        if state.get("status") == "failed":
            return {}
        pipeline = dict(state.get("pipeline") or _draft_pipeline(state))
        pipeline["decisions"] = list(state.get("decisions") or [])
        flags = {item["action"] for item in state.get("plan_actions") or []}
        blocked = int(state.get("test_failures") or 0) > 0 or bool(state.get("errors"))
        if "return_to_registration" in flags:
            status = "needs_reregister"
        elif "human_review" in flags or blocked:
            status = "human_review"
        else:
            status = "active"
            for field in pipeline.get("fields") or []:
                for rule_id in field.get("rule_ids") or []:
                    rule = repository.get_rule(rule_id)
                    if rule.get("status") != "active":
                        version = rule["versions"][-1]["version"]
                        repository.activate(rule_id, version)
        pipeline["status"] = status
        repository.save_pipeline(pipeline)
        return {"pipeline": pipeline, "status": status, "errors": list(state.get("errors") or [])}

    graph.add_node("check", check)
    graph.add_node("seed", seed)
    graph.add_node("inspect", inspect)
    graph.add_node("plan", plan)
    graph.add_node("apply", apply)
    graph.add_node("test", test)
    graph.add_node("save", save)
    graph.add_edge(START, "check")
    graph.add_conditional_edges(
        "check",
        lambda state: "end" if state.get("status") == "failed" else "seed",
        {"seed": "seed", "end": END},
    )
    graph.add_edge("seed", "inspect")
    graph.add_edge("inspect", "plan")
    graph.add_edge("plan", "apply")
    graph.add_edge("apply", "test")
    graph.add_conditional_edges(
        "test",
        lambda state: "inspect" if state.get("needs_replan") else "save",
        {"inspect": "inspect", "save": "save"},
    )
    graph.add_edge("save", END)
    return graph.compile()


def _apply_action(
    action: str,
    fact: dict[str, Any],
    previous: dict[str, Any] | None,
    *,
    repository: RuleRepository,
    skills: ParsingSkills,
    values: list[Any],
    source_table: str,
    source_type: str,
) -> tuple[dict[str, Any], str]:
    source_field = str(fact.get("source_field") or (previous or {}).get("source_field") or "")
    standard_field = str(fact.get("standard_field") or (previous or {}).get("standard_field") or "")
    kept = list((previous or {}).get("rule_ids") or [])
    if action == "passthrough":
        return _field_step(source_field, standard_field, []), "success"
    if action == "human_review":
        return _field_step(source_field, standard_field, kept), "human_review"
    if action == "return_to_registration":
        return _field_step(source_field, standard_field, kept), "return_to_registration"
    if action == "use_existing":
        rule_id = str(fact.get("specific_rule_id") or "")
        if not rule_id:
            raise ValueError("没有本表规则")
        return _field_step(source_field, standard_field, [rule_id]), "success"
    rule_ids: list[str] = []
    issues = list(fact.get("issues") or []) or [{}]
    if action == "use_seeded":
        for issue, seeded in zip(issues, fact.get("seeded_rule_ids") or [fact.get("seeded_rule_id") or ""]):
            if not seeded:
                seeded = seeded_rule_id(repository, issue) if issue else ""
            if seeded:
                rule_ids.append(str(seeded))
        if not rule_ids:
            raise ValueError("没有可使用的注册规则")
        return _field_step(source_field, standard_field, _ordered(repository, rule_ids)), "success"
    if action == "reuse_generic":
        generic_id = str(fact.get("generic_rule_id") or "")
        if not generic_id:
            raise ValueError("没有通用规则")
        for issue in issues:
            rule_id = _reuse_generic(issue, repository, skills, values, generic_id)
            if rule_id:
                rule_ids.append(rule_id)
        if not rule_ids:
            raise ValueError("通用规则不可复用")
        return _field_step(source_field, standard_field, _ordered(repository, rule_ids)), "success"
    for issue in issues:
        rule_id = _generate_rule(issue, repository, skills, values, source_table, source_type)
        if rule_id:
            rule_ids.append(rule_id)
    if not rule_ids:
        if kept:
            return _field_step(source_field, standard_field, kept), "failed"
        raise ValueError("新规则未通过样本测试")
    return _field_step(source_field, standard_field, _ordered(repository, rule_ids)), "success"


def _reuse_generic(issue: dict[str, Any], repository: RuleRepository, skills: ParsingSkills, values: list[Any], generic_id: str) -> str:
    generic = repository.get_rule(generic_id)
    opinion = skills.run(
        "rule-reuse-analysis",
        {"issue": issue, "rule": generic, "samples": values[:5]},
        ReuseOpinion,
    )
    version = repository.version_of(generic["rule_id"])
    if opinion.reuse and _passed(version["operator"], version.get("params") or {}, values):
        return str(generic["rule_id"])
    raise ValueError("通用规则不可复用")


def _generate_rule(
    issue: dict[str, Any],
    repository: RuleRepository,
    skills: ParsingSkills,
    values: list[Any],
    source_table: str,
    source_type: str,
) -> str:
    draft = skills.run(
        "rule-generation",
        {"issue": issue, "samples": [value for value in values if value not in (None, "")][:5]},
        RuleDraft,
    )
    operator = assert_operator(draft.operator)
    passed = _passed(operator, draft.params, values)
    rule = repository.create_rule(
        {
            "standard_field": issue.get("standard_field") or draft.standard_field,
            "source_type": source_type,
            "source_table": source_table,
            "source_field": issue.get("source_field") or draft.source_field,
            "rule_type": draft.rule_type or issue.get("issue_type") or "extraction",
        }
    )
    repository.append_version(
        rule["rule_id"],
        {
            "operator": operator,
            "params": draft.params,
            "test_status": "passed" if passed else "failed",
            "status": "validated" if passed else "candidate",
            "created_from": "pipeline_builder",
            "test_report": {"passed": passed},
        },
    )
    if not passed:
        raise ValueError("新规则未通过样本测试")
    repository.add_samples(_records(rule["rule_id"], rule["standard_field"], operator, draft.params, values))
    return str(rule["rule_id"])


def _ordered(repository: RuleRepository, rule_ids: list[str]) -> list[str]:
    def key(rule_id: str) -> int:
        rule = repository.get_rule(rule_id)
        return 0 if rule.get("rule_type") in {"extraction", "composite_split"} else 1

    return sorted(dict.fromkeys(rule_ids), key=key)


def _passed(operator: str, params: dict[str, Any], values: list[Any]) -> bool:
    checked = [value for value in values if value not in (None, "")]
    if not checked:
        return False
    return all(execute(operator, value, params).ok for value in checked)


def _records(rule_id: str, standard_field: str, operator: str, params: dict[str, Any], values: list[Any]) -> list[dict[str, Any]]:
    records = []
    for value in values:
        if value in (None, ""):
            continue
        result = execute(operator, value, params)
        if result.ok:
            records.append(
                {
                    "rule_id": rule_id,
                    "standard_field": standard_field,
                    "kind": "original",
                    "value": value,
                    "expected": result.value,
                    "expect_failure": False,
                }
            )
    if records:
        records.append(
            {
                "rule_id": rule_id,
                "standard_field": standard_field,
                "kind": "counterexample",
                "value": "不是有效值",
                "expected": None,
                "expect_failure": True,
            }
        )
    return records


def _field_step(source_field: str, standard_field: str, rule_ids: list[str]) -> dict[str, Any]:
    return {
        "source_field": source_field,
        "standard_field": standard_field,
        "rule_ids": rule_ids,
        "canary_rule_id": "",
        "canary_version": None,
        "canary_ratio": 0,
    }


def _draft_pipeline(state: BuilderState) -> dict[str, Any]:
    source_table = _source_table(state)
    return {
        "pipeline_id": f"pipeline_{source_table or state['candidate'].get('candidate_id')}",
        "version": "1.0.0",
        "source_table": source_table,
        "source_type": state["source_type"],
        "standard_schema_id": state["candidate"].get("standard_schema_id") or "",
        "status": "candidate",
        "fields": state.get("field_steps") or [],
    }


def _source_table(state: BuilderState) -> str:
    return str((state["candidate"].get("source_table") or {}).get("name") or "")


def _columns(rows: list[dict[str, Any]]) -> dict[str, list[Any]]:
    columns: dict[str, list[Any]] = {}
    for row in rows:
        for key, value in row.items():
            columns.setdefault(key, []).append(value)
    return columns
