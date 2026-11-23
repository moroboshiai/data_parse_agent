"""按阶段调度表注册、解析、质检和富化。人工确认和规则发布不能自动越过。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from data_parsing.builder import build_pipeline
from data_parsing.learning import learn_from_events
from data_parsing.repository import RuleRepository
from data_parsing.runtime import ParsingEngine, write_jsonl
from enrichment.batch import run_batch
from enrichment.knowledge import KnowledgeBase
from governance.policy import resolve_review_action
from governance.skills import GovernanceSkills
from governance.store import STOP_STAGES, GovernanceError, add_artifact, load_run, make_run_id, new_run, remember, save_run
from quality.analyze import run_analyze
from quality.diagnose import run_diagnose
from quality.profile_builder import build_profile_from_standard_schema, save_profile
from table_registration.graph import run_registration
from table_registration.llm import LlmClient, LlmError
from table_registration.tools.candidate_store import confirm_candidate, load_candidate
from table_registration.tools.file_parser import parse_table
from table_registration.tools.mapping_memory import MappingMemory


class Orchestrator:
    def __init__(self, *, repo_root: str | Path, work_root: str | Path | None = None, llm: Any | None = None) -> None:
        self.repo_root = Path(repo_root)
        self.work_root = Path(work_root) if work_root is not None else self.repo_root
        self.llm = llm if llm is not None else LlmClient()
        self.skills = GovernanceSkills(self.llm)

    def start(
        self,
        *,
        sample_path: str,
        standard_schema_path: str,
        source_name: str,
        input_path: str = "",
        knowledge_path: str = "",
    ) -> dict[str, Any]:
        category = _category(standard_schema_path)
        run_id = make_run_id(source_name, category)
        existing = _read_if_exists(self.work_root, run_id)
        if existing is not None:
            if input_path:
                existing["input_path"] = input_path
            if knowledge_path:
                existing["knowledge_path"] = knowledge_path
            pipeline = _matching_pipeline(self._repository_root(), source_name, category)
            candidate = _confirmed_candidate(existing.get("candidate_path") or "")
            if candidate is not None and pipeline is not None:
                existing["stage"] = "parse"
                existing["status"] = "running"
                existing["blockers"] = []
                existing["pipeline_id"] = pipeline["pipeline_id"]
                remember(existing, "parse", "reuse", "已有确认候选和 Pipeline，从解析继续")
            save_run(self.work_root, existing)
            return existing
        run = new_run(
            run_id=run_id,
            source_name=source_name,
            category=category,
            sample_path=str(Path(sample_path)),
            standard_schema_path=str(Path(standard_schema_path)),
            input_path=str(Path(input_path)) if input_path else str(Path(sample_path)),
            knowledge_path=str(Path(knowledge_path)) if knowledge_path else "",
        )
        remember(run, "intake", "start", source_name)
        save_run(self.work_root, run)
        return run

    def status(self, run_id: str) -> dict[str, Any]:
        run = load_run(self.work_root, run_id)
        return {
            "run_id": run["run_id"],
            "stage": run["stage"],
            "status": run["status"],
            "blockers": run.get("blockers") or [],
            "candidate_path": run.get("candidate_path") or "",
            "pipeline_id": run.get("pipeline_id") or "",
            "parsed_path": run.get("parsed_path") or "",
            "profile_path": run.get("profile_path") or "",
        }

    def step(self, run_id: str) -> dict[str, Any]:
        run = load_run(self.work_root, run_id)
        stage = str(run.get("stage") or "")
        if stage == "done":
            return run
        if stage == "await_confirm":
            return self._hold(run, "等待确认候选映射")
        if stage == "intake":
            run["stage"] = "register"
            stage = "register"
        run["activity"] = _activity(stage)
        save_run(self.work_root, run)
        try:
            if stage == "register":
                self._register(run)
            elif stage == "build_pipeline":
                self._build(run)
            elif stage == "parse":
                self._parse(run)
            elif stage == "init_profile":
                self._init_profile(run)
            elif stage == "quality_analyze":
                self._analyze(run)
            elif stage == "enrich":
                self._enrich(run)
            elif stage == "review":
                self._review(run)
            else:
                raise GovernanceError(f"未知阶段: {stage}")
        except (OSError, ValueError, KeyError, ValidationError, LlmError, GovernanceError) as exc:
            run["status"] = "blocked"
            run["blockers"] = [str(exc)]
            remember(run, stage, "error", str(exc))
        run.pop("activity", None)
        save_run(self.work_root, run)
        return run

    def run(self, run_id: str) -> dict[str, Any]:
        run = load_run(self.work_root, run_id)
        for _ in range(len(STOP_STAGES) + 8):
            if run.get("status") == "blocked" or run.get("stage") in STOP_STAGES:
                return run
            before = run.get("stage")
            run = self.step(run_id)
            if run.get("stage") == before and run.get("status") == "blocked":
                return run
        return run

    def confirm(self, run_id: str) -> dict[str, Any]:
        run = load_run(self.work_root, run_id)
        if run.get("stage") != "await_confirm":
            raise GovernanceError("当前阶段不能确认候选")
        document = confirm_candidate(run["candidate_path"], MappingMemory(self._memory_path()))
        run["status"] = "running"
        run["blockers"] = []
        run["stage"] = "build_pipeline"
        add_artifact(run, "candidate", run["candidate_path"], status=document.get("status"))
        remember(run, "await_confirm", "confirm", run["candidate_path"])
        save_run(self.work_root, run)
        return self.run(run_id)

    def resume(self, run_id: str) -> dict[str, Any]:
        run = load_run(self.work_root, run_id)
        if run.get("stage") == "review" and run.get("status") != "blocked":
            for _ in range(4):
                run = self.step(run_id)
                if run.get("stage") != "review" or run.get("status") == "blocked":
                    return run
            return run
        return self.run(run_id)

    def _register(self, run: dict[str, Any]) -> None:
        state = run_registration(
            sample_path=run["sample_path"],
            standard_schema_path=run["standard_schema_path"],
            source_name=run["source_name"],
            llm=self.llm,
            memory_path=self._memory_path(),
            candidate_dir=self.work_root / "outputs" / "candidates",
            repo_root=self.repo_root,
        )
        if state.get("status") == "failed" or not state.get("candidate_path"):
            run["stage"] = "register"
            run["status"] = "blocked"
            run["blockers"] = list(state.get("errors") or ["表注册失败"])
            remember(run, "register", "failed", "；".join(run["blockers"]))
            return
        run["candidate_path"] = str(state["candidate_path"])
        run["stage"] = "await_confirm"
        run["status"] = "awaiting_confirm"
        run["blockers"] = ["等待确认候选映射"]
        add_artifact(run, "candidate", run["candidate_path"], status=state.get("status"))
        remember(run, "register", "registered", run["candidate_path"])

    def _build(self, run: dict[str, Any]) -> None:
        candidate = load_candidate(run["candidate_path"])
        if candidate.get("status") != "confirmed":
            run["stage"] = "await_confirm"
            run["status"] = "awaiting_confirm"
            run["blockers"] = ["只有已确认的注册结果可以构建 Pipeline"]
            remember(run, "build_pipeline", "blocked", run["blockers"][0])
            return
        pipeline = build_pipeline(
            candidate=candidate,
            sample_rows=parse_table(run["sample_path"]),
            source_type=run["category"],
            llm=self.llm,
            repository=self._repository(),
        )
        run["pipeline_id"] = str(pipeline.get("pipeline_id") or "")
        run["stage"] = "parse"
        run["status"] = "running"
        run["blockers"] = []
        add_artifact(run, "pipeline", run["pipeline_id"], status=pipeline.get("status"))
        remember(run, "build_pipeline", "built", run["pipeline_id"])

    def _parse(self, run: dict[str, Any]) -> None:
        repository = self._repository()
        pipeline = repository.get_pipeline(run["pipeline_id"])
        source = run.get("input_path") or run["sample_path"]
        result = ParsingEngine(repository).parse(parse_table(source), pipeline)
        output = self.work_root / "outputs" / "parsed" / f"{run['pipeline_id']}.jsonl"
        write_jsonl(output, result["rows"])
        repository.add_events(result["events"])
        run["parsed_path"] = str(output)
        run["parse_event_count"] = len(result["events"])
        run["parse_events_learned"] = False
        run["stage"] = "init_profile"
        run["status"] = "running"
        run["blockers"] = []
        add_artifact(run, "parsed", run["parsed_path"], events=run["parse_event_count"])
        remember(run, "parse", "parsed", run["parsed_path"])

    def _init_profile(self, run: dict[str, Any]) -> None:
        path = self.work_root / "data" / "quality" / "profiles" / f"{run['category']}.json"
        if not path.is_file():
            profile = build_profile_from_standard_schema(
                run["standard_schema_path"],
                source_id=run["category"],
                category=run["category"],
            )
            save_profile(path, profile)
            remember(run, "init_profile", "created", str(path))
        else:
            remember(run, "init_profile", "reused", str(path))
        run["profile_path"] = str(path)
        run["stage"] = "quality_analyze"
        run["status"] = "running"
        run["blockers"] = []
        add_artifact(run, "profile", run["profile_path"])

    def _analyze(self, run: dict[str, Any]) -> None:
        report = run_analyze(
            profile_path=run["profile_path"],
            input_path=run["parsed_path"],
            llm=self.llm,
            output_dir=str(self.work_root / "data" / "quality"),
        )
        issues = [item for item in report.get("issues") or [] if isinstance(item, dict)]
        run["issues"] = issues
        run["issues_diagnosed"] = False
        run["stage"] = "enrich"
        run["status"] = "running"
        run["blockers"] = []
        add_artifact(run, "quality_report", str(report.get("report_id") or ""), issue_count=len(issues))
        remember(run, "quality_analyze", "analyzed", str(report.get("quality_status") or ""))

    def _enrich(self, run: dict[str, Any]) -> None:
        knowledge_path = str(run.get("knowledge_path") or "")
        if not knowledge_path or not Path(knowledge_path).is_dir():
            knowledge_path = str(self.work_root / "data" / "enrichment_knowledge")
        knowledge = KnowledgeBase(knowledge_path)
        records = run_batch(
            events=_load_jsonl(run["parsed_path"]),
            knowledge=knowledge,
            llm=self.llm,
            output_dir=str(self.work_root / "data" / "enrichment"),
        )
        visible = [item for item in records if _has_enrichment(item)]
        empty = not visible
        run["enrichment_count"] = len(records)
        run["enrichment_empty"] = empty
        run["stage"] = "review"
        run["status"] = "review"
        if knowledge.is_empty and visible:
            run["blockers"] = []
            detail = f"无知识数据，模型已打标签 count={len(visible)}"
        elif knowledge.is_empty:
            run["blockers"] = ["没有知识数据，模型未能给出标签"]
            detail = run["blockers"][0]
        elif empty:
            run["blockers"] = ["富化结果没有命中资产或情报"]
            detail = run["blockers"][0]
        else:
            run["blockers"] = []
            detail = f"count={len(records)}"
        add_artifact(run, "enrichment", str(self.work_root / "data" / "enrichment"), count=len(records))
        remember(run, "enrich", "enriched", detail)

    def _review(self, run: dict[str, Any]) -> None:
        has_events = int(run.get("parse_event_count") or 0) > 0 and not run.get("parse_events_learned")
        high = [item for item in run.get("issues") or [] if item.get("severity") == "high" and not run.get("issues_diagnosed")]
        proposed = ""
        reason = ""
        try:
            choice = self.skills.choose_review(
                {
                    "allowed_actions": ["learn", "diagnose", "finish"],
                    "has_parse_events": has_events,
                    "high_issue_count": len(high),
                    "enrichment_empty": bool(run.get("enrichment_empty")),
                    "instruction": "只从 allowed_actions 中选择。不要发布规则。",
                }
            )
            proposed = choice.action
            reason = choice.reason
        except (LlmError, ValidationError):
            proposed = ""
        action, rejected = resolve_review_action(proposed, has_events=has_events, has_high_issues=bool(high))
        run.setdefault("decisions", []).append({"accepted": action, "rejected": rejected, "reason": reason})
        if action == "learn":
            summary = learn_from_events(repository=self._repository(), pipeline_id=run["pipeline_id"], llm=self.llm)
            run["parse_events_learned"] = True
            add_artifact(run, "learn", run["pipeline_id"], decisions=len(summary.get("decisions") or []))
            remember(run, "review", "learn", run["pipeline_id"])
            return
        if action == "diagnose":
            output = str(self.work_root / "data" / "quality")
            for issue in high[:3]:
                run_diagnose(issue=issue, llm=self.llm, output_dir=output, repository=str(self._repository_root()))
            run["issues_diagnosed"] = True
            remember(run, "review", "diagnose", str(len(high[:3])))
            return
        run["stage"] = "done"
        run["status"] = "done"
        run["blockers"] = []
        remember(run, "review", "finish", "")

    def _hold(self, run: dict[str, Any], reason: str) -> dict[str, Any]:
        run["status"] = "awaiting_confirm"
        run["blockers"] = [reason]
        save_run(self.work_root, run)
        return run

    def _repository(self) -> RuleRepository:
        return RuleRepository(self._repository_root())

    def _repository_root(self) -> Path:
        return self.work_root / "data" / "rule_repository"

    def _memory_path(self) -> Path:
        return self.work_root / "data" / "mapping_memory.json"


def _has_enrichment(record: dict[str, Any]) -> bool:
    if record.get("facts"):
        return True
    return any(item.get("status") in {"auto_accepted", "needs_review", "investigation_required"} for item in record.get("labels") or [])


def _activity(stage: str) -> str:
    labels = {
        "register": "正在表注册，字段映射可能需要数分钟",
        "build_pipeline": "正在构建解析管道",
        "parse": "正在解析数据",
        "init_profile": "正在生成质量画像",
        "quality_analyze": "正在分析数据质量",
        "enrich": "正在富化",
        "review": "正在复核",
    }
    return labels.get(stage, "正在执行")


def _category(path: str) -> str:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise GovernanceError("规范表必须是 JSON 对象")
    category = str(payload.get("category_alias") or payload.get("id") or "").strip()
    if not category:
        raise GovernanceError("规范表缺少 category_alias")
    return category


def _read_if_exists(work_root: Path, run_id: str) -> dict[str, Any] | None:
    try:
        return load_run(work_root, run_id)
    except GovernanceError:
        return None


def _confirmed_candidate(path: str) -> dict[str, Any] | None:
    if not path or not Path(path).is_file():
        return None
    document = load_candidate(path)
    if document.get("status") != "confirmed":
        return None
    return document


def _matching_pipeline(repository_root: Path, source_name: str, category: str) -> dict[str, Any] | None:
    path = repository_root / "pipelines.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("pipelines") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return None
    matched = [
        item
        for item in items
        if isinstance(item, dict) and item.get("source_table") == source_name and item.get("standard_schema_id") == category
    ]
    return dict(matched[-1]) if matched else None


def _load_jsonl(path: str) -> list[dict[str, Any]]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            rows.append(item)
    return rows
