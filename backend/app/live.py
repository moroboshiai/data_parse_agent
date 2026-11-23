"""把控制台接到仓库里的真实智能体和产物文件。"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

from data_parsing.builder import build_pipeline
from data_parsing.learning import learn_from_events
from data_parsing.policies import RulePolicyError
from data_parsing.repository import RuleRepository
from data_parsing.runtime import ParsingEngine, write_jsonl
from enrichment.adapt import adapt_events
from enrichment.batch import run_batch
from enrichment.investigation import run_investigation
from enrichment.knowledge import KnowledgeBase
from enrichment.schemas import RISK_NAMES, STRATEGY_VERSION
from governance.runner import Orchestrator
from governance.store import GovernanceError, RunBusyError, delete_run as remove_run_record, load_run, runs_dir
from quality.analyze import run_analyze
from quality.diagnose import run_diagnose
from quality.profile_builder import build_profile_from_standard_schema, save_profile
from quality.store import baseline_path, read_json, save_baseline
from quality.timing import zone
from table_registration.config import find_repo_root, init_from_repo
from table_registration.graph import run_registration
from table_registration.llm import LlmClient
from table_registration.tools.candidate_store import (
    confirm_candidate,
    delete_candidate as remove_candidate_file,
    load_candidate,
    update_candidate_mappings,
)
from table_registration.tools.file_parser import parse_table
from table_registration.tools.mapping_memory import MappingMemory

from app.jobs import JobRunner


class LiveService:
    def __init__(self) -> None:
        self.root = _repo_root()
        self.jobs = JobRunner()
        init_from_repo(self.root)

    def meta(self) -> dict[str, Any]:
        return {"mode": "live", "repo_root": str(self.root)}

    def dashboard(self) -> dict[str, Any]:
        runs = self.list_runs()
        candidates = self.list_candidates()
        pipelines = self.list_pipelines()
        issues = _json_files(self.root / "data" / "quality" / "issues")
        return {
            "metrics": [
                {"key": "runs", "label": "进行中任务", "value": sum(1 for item in runs if item["stage"] != "done"), "hint": "data/governance/runs"},
                {"key": "candidates", "label": "待确认候选", "value": sum(1 for item in candidates if item["status"] != "confirmed"), "hint": "outputs/candidates"},
                {"key": "events", "label": "解析失败事件", "value": sum(item["event_count"] for item in pipelines), "hint": "data/rule_repository/events.json"},
                {"key": "issues", "label": "质检问题", "value": len(issues), "hint": "data/quality/issues"},
            ],
            "runs": runs[:8],
            "stages": ["intake", "register", "await_confirm", "build_pipeline", "parse", "init_profile", "quality_analyze", "enrich", "review", "done"],
        }

    def list_runs(self) -> list[dict[str, Any]]:
        folder = runs_dir(self.root)
        if not folder.is_dir():
            return []
        runs = []
        for path in sorted(folder.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            payload = _read(path)
            if payload:
                runs.append(_run_summary(payload))
        return runs

    def get_run(self, run_id: str) -> dict[str, Any]:
        try:
            return load_run(self.root, run_id)
        except GovernanceError as exc:
            raise KeyError(run_id) from exc

    def delete_run(self, run_id: str) -> dict[str, Any]:
        try:
            remove_run_record(self.root, run_id)
        except RunBusyError:
            raise
        except GovernanceError as exc:
            raise KeyError(run_id) from exc
        return {"deleted": True, "run_id": run_id}

    def start_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        sample = _existing(self.root, payload.get("sample_path"), "样本")
        standard = _existing(self.root, payload.get("standard_schema_path"), "规范表")
        source_name = str(payload.get("source_name") or "").strip()
        if not source_name:
            raise ValueError("来源名不能为空")
        input_path = str(payload.get("input_path") or "")
        if input_path:
            input_path = str(_existing(self.root, input_path, "解析输入"))
        knowledge = str(payload.get("knowledge_path") or "")
        if knowledge:
            knowledge = str(_existing(self.root, knowledge, "知识目录", directory=True))
        return self._orchestrator().start(
            sample_path=str(sample),
            standard_schema_path=str(standard),
            source_name=source_name,
            input_path=input_path,
            knowledge_path=knowledge,
        )

    def queue_step(self, run_id: str) -> dict[str, Any]:
        self.get_run(run_id)
        return self.jobs.start("governance-step", lambda: self._orchestrator().step(run_id))

    def queue_confirm(self, run_id: str) -> dict[str, Any]:
        self.get_run(run_id)
        return self.jobs.start("governance-confirm", lambda: self._orchestrator().confirm(run_id))

    def queue_resume(self, run_id: str) -> dict[str, Any]:
        self.get_run(run_id)
        return self.jobs.start("governance-resume", lambda: self._orchestrator().resume(run_id))

    def list_candidates(self) -> list[dict[str, Any]]:
        folder = self.root / "outputs" / "candidates"
        if not folder.is_dir():
            return []
        items = []
        for path in sorted(folder.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            document = _read(path)
            if document and document.get("candidate_id"):
                items.append(_candidate_summary(document, self.root))
        return items

    def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        path = self.root / "outputs" / "candidates" / f"{candidate_id}.json"
        if not path.is_file():
            raise KeyError(candidate_id)
        return _candidate_detail(load_candidate(path), self.root)

    def delete_candidate(self, candidate_id: str) -> dict[str, Any]:
        try:
            remove_candidate_file(self.root / "outputs" / "candidates", candidate_id)
        except FileNotFoundError as exc:
            raise KeyError(candidate_id) from exc
        return {"deleted": True, "candidate_id": candidate_id}

    def update_candidate(self, candidate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            document = update_candidate_mappings(self.root / "outputs" / "candidates", candidate_id, payload.get("mappings") or [])
        except FileNotFoundError as exc:
            raise KeyError(candidate_id) from exc
        return _candidate_detail(document, self.root)

    def queue_register(self, payload: dict[str, Any]) -> dict[str, Any]:
        sample = _existing(self.root, payload.get("sample"), "样本")
        standard = _existing(self.root, payload.get("standard"), "规范表")
        source_name = str(payload.get("source_name") or "source_table")
        schema = str(payload.get("source_schema") or "")
        schema_path = str(_existing(self.root, schema, "来源结构")) if schema else None

        def work() -> dict[str, Any]:
            state = run_registration(
                sample_path=str(sample),
                standard_schema_path=str(standard),
                source_schema_path=schema_path,
                source_name=source_name,
                repo_root=self.root,
            )
            if state.get("status") == "failed":
                raise ValueError("；".join(state.get("errors") or ["表注册失败"]))
            return {"candidate_path": state.get("candidate_path") or "", "status": state.get("status")}

        return self.jobs.start("register", work)

    def queue_confirm_candidate(self, candidate_id: str) -> dict[str, Any]:
        path = self.root / "outputs" / "candidates" / f"{candidate_id}.json"
        if not path.is_file():
            raise KeyError(candidate_id)

        def work() -> dict[str, Any]:
            document = confirm_candidate(path, MappingMemory(self.root / "data" / "mapping_memory.json"))
            return {"candidate_id": document.get("candidate_id"), "status": document.get("status")}

        return self.jobs.start("confirm-candidate", work)

    def list_pipelines(self) -> list[dict[str, Any]]:
        repository = self._repository()
        events = repository.list_events()
        counts: dict[str, int] = {}
        for event in events:
            key = str(event.get("pipeline_id") or "")
            counts[key] = counts.get(key, 0) + 1
        folder = self.root / "data" / "rule_repository" / "pipelines.json"
        if not folder.is_file():
            return []
        payload = _read(folder) or {}
        candidates = _load_candidates(self.root)
        items = []
        for item in payload.get("pipelines") or []:
            if not isinstance(item, dict):
                continue
            pipeline_id = str(item.get("pipeline_id") or "")
            summary = _mapping_summary(self.root, item, candidates)
            items.append(
                {
                    "pipeline_id": pipeline_id,
                    "status": item.get("status") or "",
                    "source_name": item.get("source_table") or "",
                    "source_type": item.get("source_type") or "",
                    "event_count": counts.get(pipeline_id, 0),
                    "step_count": len(item.get("fields") or []),
                    "source_field_count": summary["source_field_count"],
                    "mapped_field_count": summary["mapped_field_count"],
                    "unmapped_field_count": summary["unmapped_field_count"],
                }
            )
        return items

    def pipeline_preview(self, pipeline_id: str) -> dict[str, Any]:
        pipeline = self._repository().get_pipeline(pipeline_id)
        fields = [item for item in pipeline.get("fields") or [] if isinstance(item, dict)]
        rows = _jsonl_head(self.root / "outputs" / "parsed" / f"{pipeline_id}.jsonl", 20)
        rules = {str(item.get("rule_id")): item for item in self._repository().list_rules() if item.get("rule_id")}
        steps = [_field_step(item, rules) for item in fields]
        summary = _mapping_summary(self.root, pipeline)
        return {
            "pipeline_id": pipeline_id,
            "status": pipeline.get("status") or "",
            "source_type": pipeline.get("source_type") or "",
            "source_name": pipeline.get("source_table") or "",
            "source_field_count": summary["source_field_count"],
            "mapped_field_count": summary["mapped_field_count"],
            "unmapped_field_count": summary["unmapped_field_count"],
            "event_count": len(self._repository().list_events(pipeline_id=pipeline_id)),
            "field_steps": steps,
            "rows": rows,
            "learn_decisions": [item for item in pipeline.get("learn_decisions") or [] if isinstance(item, dict)],
            "rules": [
                {
                    "rule_id": rule_id,
                    "active_version": item.get("active_version"),
                    "operator": _rule_version(item).get("operator") or "",
                }
                for rule_id, item in rules.items()
                if item.get("source_table") == pipeline.get("source_table")
            ],
            "notice": pipeline.get("notice") or "发布与回滚会写入规则仓库。主控本身不会自动发布。",
            "preview_notice": _preview_notice(fields, rows),
        }

    def delete_pipeline(self, pipeline_id: str) -> dict[str, Any]:
        self._repository().delete_pipeline(pipeline_id)
        return {"deleted": True, "pipeline_id": pipeline_id}

    def pipeline_events(self, pipeline_id: str) -> dict[str, Any]:
        self._repository().get_pipeline(pipeline_id)
        events = self._repository().list_events(pipeline_id=pipeline_id)[:50]
        return {
            "pipeline_id": pipeline_id,
            "events": [
                {
                    "event_id": item.get("event_id"),
                    "field": item.get("field") or item.get("standard_field") or "",
                    "operator": item.get("operator") or "",
                    "message": item.get("message") or _event_message(item),
                    "resolution": item.get("resolution") or "未处理",
                }
                for item in events
            ],
        }

    def queue_build(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidate = _existing(self.root, payload.get("candidate"), "候选")
        sample = _existing(self.root, payload.get("sample"), "样本")
        source_type = str(payload.get("source_type") or "generic")

        def work() -> dict[str, Any]:
            pipeline = build_pipeline(
                candidate=load_candidate(candidate),
                sample_rows=parse_table(sample),
                source_type=source_type,
                llm=LlmClient(),
                repository=self._repository(),
            )
            return {"pipeline_id": pipeline.get("pipeline_id"), "status": pipeline.get("status")}

        return self.jobs.start("build", work)

    def queue_parse(self, payload: dict[str, Any]) -> dict[str, Any]:
        pipeline_id = str(payload.get("pipeline_id") or "")
        source = _existing(self.root, payload.get("input"), "解析输入")
        self._repository().get_pipeline(pipeline_id)

        def work() -> dict[str, Any]:
            repository = self._repository()
            result = ParsingEngine(repository).parse(parse_table(source), repository.get_pipeline(pipeline_id))
            output = self.root / "outputs" / "parsed" / f"{pipeline_id}.jsonl"
            write_jsonl(output, result["rows"])
            repository.add_events(result["events"])
            return {"output": str(output), "events": len(result["events"]), "rows": len(result["rows"])}

        return self.jobs.start("parse", work)

    def queue_learn(self, pipeline_id: str) -> dict[str, Any]:
        self._repository().get_pipeline(pipeline_id)

        def work() -> dict[str, Any]:
            return learn_from_events(repository=self._repository(), pipeline_id=pipeline_id, llm=LlmClient())

        return self.jobs.start("learn", work)

    def publish(self, pipeline_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._repository().get_pipeline(pipeline_id)
        rule_id = str(payload.get("rule_id") or "")
        version = int(payload.get("version") or 0)
        action = str(payload.get("action") or "publish")
        try:
            if action == "rollback":
                rule = self._repository().rollback(rule_id, version)
            else:
                rule = self._repository().publish(rule_id, version)
        except (RulePolicyError, KeyError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        return {"accepted": True, "rule_id": rule.get("rule_id"), "active_version": rule.get("active_version"), "message": "规则仓库已更新"}

    def quality_profiles(self) -> list[dict[str, Any]]:
        folder = self.root / "data" / "quality" / "profiles"
        profiles = []
        for path in _json_files(folder):
            payload = _read(path) or {}
            profiles.append(
                {
                    "source_id": payload.get("source_id") or path.stem,
                    "category": payload.get("category") or "",
                    "time_field": payload.get("time_field") or "",
                    "field_count": len(payload.get("fields") or []),
                    "profile_path": str(path.relative_to(self.root)),
                }
            )
        return profiles

    def quality_reports(self) -> list[dict[str, Any]]:
        reports = []
        for path in _json_files(self.root / "data" / "quality" / "reports"):
            payload = _read(path) or {}
            overview = payload.get("overview") or {}
            issues = payload.get("issues") or []
            reports.append(
                {
                    "report_id": payload.get("report_id") or path.stem,
                    "source_id": payload.get("source_id") or "",
                    "category": payload.get("category") or "",
                    "quality_status": payload.get("quality_status") or overview.get("quality_status") or "",
                    "window": (payload.get("time_range") or {}).get("start") or "",
                    "row_count": overview.get("total_count") or 0,
                    "issue_count": len(issues),
                    "issue_ids": [item.get("issue_id") for item in issues if isinstance(item, dict) and item.get("issue_id")],
                    "summary": payload.get("summary") or "",
                }
            )
        return reports

    def quality_baselines(self) -> list[dict[str, Any]]:
        sources: dict[str, dict[str, Any]] = {}
        for profile in self.quality_profiles():
            source_id = str(profile.get("source_id") or "")
            category = str(profile.get("category") or "")
            if source_id:
                sources[source_id] = _source_entry(source_id, category)
        metrics_root = self.root / "data" / "quality" / "metrics"
        if metrics_root.is_dir():
            for folder in sorted(metrics_root.iterdir()):
                if not folder.is_dir():
                    continue
                source_id = folder.name
                sample = next(iter(_json_files(folder)), None)
                payload = _read(sample) if sample else None
                category = str((payload or {}).get("category") or "")
                sources.setdefault(source_id, _source_entry(source_id, category))
        ordered = [self._source_baseline_view(source_id, item["category"]) for source_id, item in sources.items()]
        ordered.sort(key=lambda item: (0 if item["snapshots"] else 1, item["source_id"]))
        return ordered

    def quality_baseline(
        self,
        source_id: str = "",
        category: str = "",
        baseline: str = "",
        current: str = "",
    ) -> dict[str, Any]:
        sources = self.quality_baselines()
        selected = _pick_source(sources, source_id, category)
        if selected is None:
            return {
                "source_id": source_id,
                "category": category,
                "volume": 0,
                "updated_at": "",
                "baseline_id": "",
                "current_id": "",
                "notice": "还没有质量报告",
                "comparisons": [],
            }
        source_id = selected["source_id"]
        category = selected["category"]
        snapshots = selected["snapshots"]
        baseline_id = baseline or _default_baseline_id(snapshots)
        current_id = current or _default_current_id(snapshots)
        if not baseline_id or not current_id:
            return {
                "source_id": source_id,
                "category": category,
                "volume": 0,
                "updated_at": "",
                "baseline_id": baseline_id,
                "current_id": current_id,
                "notice": _empty_notice(selected, baseline_id, current_id),
                "comparisons": [],
            }
        if baseline_id == current_id:
            return {
                "source_id": source_id,
                "category": category,
                "volume": 0,
                "updated_at": "",
                "baseline_id": baseline_id,
                "current_id": current_id,
                "notice": "请选择与当前不同的基线",
                "comparisons": [],
            }
        base_payload, base_meta = self._load_snapshot(source_id, category, baseline_id)
        current_payload, current_meta = self._load_snapshot(source_id, category, current_id)
        notice = ""
        if not selected.get("has_saved_baseline"):
            notice = "该来源还没有正式基线，可用报告当基线或点设为基线"
        return {
            "source_id": source_id,
            "category": category,
            "volume": current_meta.get("volume") or 0,
            "updated_at": current_meta.get("updated_at") or "",
            "baseline_id": baseline_id,
            "current_id": current_id,
            "baseline_volume": base_meta.get("volume") or 0,
            "baseline_updated_at": base_meta.get("updated_at") or "",
            "notice": notice,
            "comparisons": _metric_comparisons(base_payload, current_payload),
        }

    def set_quality_baseline(self, source_id: str, category: str, snapshot_id: str) -> dict[str, Any]:
        payload, _meta = self._load_snapshot(source_id, category, snapshot_id)
        if snapshot_id == "saved":
            raise ValueError("请选择一份质量报告作为基线")
        target = baseline_path(self.root / "data" / "quality", source_id, category)
        save_baseline(
            target,
            {
                "source_id": source_id,
                "category": category,
                "metrics": payload.get("metrics") or {},
                "distributions": payload.get("distributions") or {},
                "total_count": payload.get("total_count") or payload.get("volume") or 0,
            },
        )
        return {"source_id": source_id, "category": category, "baseline_path": str(target), "snapshot_id": snapshot_id}

    def _source_baseline_view(self, source_id: str, category: str) -> dict[str, Any]:
        snapshots: list[dict[str, Any]] = []
        saved = baseline_path(self.root / "data" / "quality", source_id, category)
        if saved.is_file():
            payload = _read(saved) or {}
            snapshots.append(
                {
                    "id": "saved",
                    "kind": "baseline",
                    "label": "正式基线",
                    "volume": payload.get("volume") or 0,
                    "updated_at": payload.get("updated_at") or _mtime(saved),
                }
            )
        folder = self.root / "data" / "quality" / "metrics" / source_id
        reports = []
        for path in _json_files(folder):
            payload = _read(path) or {}
            reports.append(
                {
                    "id": path.stem,
                    "kind": "report",
                    "label": path.stem,
                    "volume": payload.get("total_count") or payload.get("volume") or 0,
                    "updated_at": payload.get("updated_at") or _mtime(path),
                }
            )
        reports.sort(key=lambda item: str(item.get("updated_at") or ""))
        snapshots.extend(reports)
        if not category and folder.is_dir():
            sample = next(iter(_json_files(folder)), None)
            category = str((_read(sample) or {}).get("category") or "") if sample else ""
        return {
            "source_id": source_id,
            "category": category,
            "has_saved_baseline": any(item["kind"] == "baseline" for item in snapshots),
            "snapshots": snapshots,
        }

    def _load_snapshot(self, source_id: str, category: str, snapshot_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if snapshot_id == "saved":
            path = baseline_path(self.root / "data" / "quality", source_id, category)
            payload = _read(path) if path.is_file() else None
            if payload is None:
                raise ValueError("没有正式基线")
            meta = {
                "volume": payload.get("volume") or 0,
                "updated_at": payload.get("updated_at") or _mtime(path),
            }
            return payload, meta
        path = self.root / "data" / "quality" / "metrics" / source_id / f"{snapshot_id}.json"
        payload = _read(path) if path.is_file() else None
        if payload is None:
            raise ValueError("没有找到这份质量报告")
        meta = {
            "volume": payload.get("total_count") or payload.get("volume") or 0,
            "updated_at": payload.get("updated_at") or _mtime(path),
        }
        return payload, meta

    def quality_issue(self, issue_id: str) -> dict[str, Any]:
        path = self.root / "data" / "quality" / "issues" / f"{issue_id}.json"
        if not path.is_file():
            raise KeyError(issue_id)
        issue = read_json(path)
        diagnosis = _matching(self.root / "data" / "quality" / "diagnoses", "issue_id", issue_id)
        task = _matching(self.root / "data" / "quality" / "tasks", "issue_id", issue_id)
        if diagnosis and task and "task" not in diagnosis:
            diagnosis = {**diagnosis, "task": task}
        return {
            "issue": _issue_view(issue),
            "diagnosis": _diagnosis_view(diagnosis) if diagnosis else None,
            "baseline": self.quality_baseline(str(issue.get("source_id") or ""), str(issue.get("category") or "")),
        }

    def queue_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        standard = _existing(self.root, payload.get("standard"), "规范表")
        source_id = str(payload.get("source_id") or "")

        def work() -> dict[str, Any]:
            profile = build_profile_from_standard_schema(standard, source_id=source_id)
            target = self.root / "data" / "quality" / "profiles" / f"{profile['source_id']}.json"
            save_profile(target, profile)
            return {"profile_path": str(target), "source_id": profile["source_id"], "field_count": len(profile.get("fields") or [])}

        return self.jobs.start("init-profile", work)

    def queue_analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = _existing(self.root, payload.get("profile"), "画像")
        source = _existing(self.root, payload.get("input"), "质检输入")

        def work() -> dict[str, Any]:
            report = run_analyze(
                profile_path=str(profile),
                input_path=str(source),
                llm=LlmClient(),
                output_dir=str(self.root / "data" / "quality"),
                start=str(payload.get("start") or ""),
                end=str(payload.get("end") or ""),
            )
            return {"report_id": report.get("report_id"), "quality_status": report.get("quality_status")}

        return self.jobs.start("analyze", work)

    def queue_diagnose(self, issue_id: str) -> dict[str, Any]:
        path = self.root / "data" / "quality" / "issues" / f"{issue_id}.json"
        if not path.is_file():
            raise KeyError(issue_id)

        def work() -> dict[str, Any]:
            result = run_diagnose(
                issue=read_json(path),
                llm=LlmClient(),
                output_dir=str(self.root / "data" / "quality"),
                repository=str(self.root / "data" / "rule_repository"),
            )
            task = result.get("task") or {}
            return {"issue_id": issue_id, "target_agent": task.get("target_agent") or ""}

        return self.jobs.start("diagnose", work)

    def enrichment_records(self) -> list[dict[str, Any]]:
        return self.enrichment_page()["records"]

    def enrichment_page(self, source_text: str = "") -> dict[str, Any]:
        folder = self.root / "data" / "enrichment" / STRATEGY_VERSION
        if not folder.is_dir():
            return {"records": [], "summary": _empty_enrichment_summary()}
        paths = sorted(folder.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        all_total = len(paths)
        wanted = _event_ids_from_input(self.root, source_text)
        if wanted is not None:
            paths = [path for path in paths if path.stem in wanted]
            payloads = [payload for path in paths if (payload := _read(path))]
            summary = _summarize_enrichment_records(payloads)
        else:
            payloads, summary = _load_enrichment_payloads(folder, paths)
        shown = _shown_records(payloads)
        summary["all_total"] = all_total
        events = _parsed_events(self.root) if any(not _has_event_content(item) for item in shown) else {}
        return {
            "records": [_record_view(item, events.get(str(item.get("event_id") or ""), {})) for item in shown],
            "summary": summary,
        }

    def investigation(self, event_id: str) -> dict[str, Any]:
        path = self.root / "data" / "enrichment" / "investigations" / f"{_safe_name(event_id)}.json"
        if not path.is_file():
            raise KeyError(event_id)
        return _investigation_view(_read(path) or {})

    def knowledge(self, directory: str = "") -> dict[str, Any]:
        root = _knowledge_root(self.root, directory)
        if not root.is_dir():
            return {"assets": [], "indicators": [], "history": [], "path": str(root)}
        base = KnowledgeBase(root)
        return {"assets": base.assets, "indicators": base.indicators, "history": base.history, "path": str(root)}

    def add_knowledge(self, kind: str, item: dict[str, Any], directory: str = "") -> dict[str, Any]:
        root, filename, key, match_keys = _knowledge_spec(self.root, directory, kind)
        stored = _normalize_knowledge_item(kind, item)
        items = _knowledge_items(root / filename, key)
        if _find_knowledge(items, stored, match_keys) is not None:
            raise ValueError("这条知识已存在")
        items.append(stored)
        _write_knowledge(root / filename, key, items)
        return {"kind": kind, "item": stored}

    def update_knowledge(self, kind: str, match: dict[str, Any], item: dict[str, Any], directory: str = "") -> dict[str, Any]:
        root, filename, key, match_keys = _knowledge_spec(self.root, directory, kind)
        items = _knowledge_items(root / filename, key)
        index = _find_knowledge(items, match, match_keys)
        if index is None:
            raise KeyError(kind)
        stored = _normalize_knowledge_item(kind, {**items[index], **item})
        duplicate = _find_knowledge(items, stored, match_keys)
        if duplicate is not None and duplicate != index:
            raise ValueError("更新后与已有知识冲突")
        items[index] = stored
        _write_knowledge(root / filename, key, items)
        return {"kind": kind, "item": stored}

    def delete_knowledge(self, kind: str, match: dict[str, Any], directory: str = "") -> dict[str, Any]:
        root, filename, key, match_keys = _knowledge_spec(self.root, directory, kind)
        items = _knowledge_items(root / filename, key)
        index = _find_knowledge(items, match, match_keys)
        if index is None:
            raise KeyError(kind)
        items.pop(index)
        _write_knowledge(root / filename, key, items)
        return {"kind": kind, "deleted": True}

    def queue_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        source = _existing(self.root, payload.get("input"), "富化输入")
        knowledge_text = str(payload.get("knowledge") or "").strip()
        knowledge = _existing(self.root, knowledge_text, "知识目录", directory=True) if knowledge_text else self.root / "data" / "enrichment_knowledge"

        def work() -> dict[str, Any]:
            records = run_batch(
                events=_jsonl_all(source),
                knowledge=KnowledgeBase(knowledge),
                llm=LlmClient(),
                output_dir=str(self.root / "data" / "enrichment"),
            )
            return {"count": len(records)}

        return self.jobs.start("enrich-batch", work)

    def preview_events(self, source_text: str, limit: int = 50) -> dict[str, Any]:
        events = adapt_events(_jsonl_all(_existing(self.root, source_text, "富化输入")))
        shown = []
        for index, event in enumerate(events[:limit], start=1):
            shown.append(
                {
                    "index": index,
                    "event_id": event.get("event_id") or "",
                    "event_type": event.get("event_type") or "",
                    "timestamp": event.get("timestamp") or "",
                    "src_ip": event.get("src_ip") or "",
                    "dst_ip": event.get("dst_ip") or "",
                    "domain": event.get("domain") or "",
                }
            )
        return {"count": len(events), "events": shown}

    def queue_one(self, payload: dict[str, Any]) -> dict[str, Any]:
        source = _existing(self.root, payload.get("input"), "富化输入")
        knowledge_text = str(payload.get("knowledge") or "").strip()
        knowledge = _existing(self.root, knowledge_text, "知识目录", directory=True) if knowledge_text else self.root / "data" / "enrichment_knowledge"
        events = adapt_events(_jsonl_all(source))
        chosen = _pick_event(events, str(payload.get("event_id") or "").strip(), int(payload.get("index") or 0))

        def work() -> dict[str, Any]:
            records = run_batch(
                events=[chosen],
                knowledge=KnowledgeBase(knowledge),
                llm=LlmClient(),
                output_dir=str(self.root / "data" / "enrichment"),
            )
            return _record_view(records[0] if records else {"event_id": chosen.get("event_id")})

        return self.jobs.start("enrich-one", work)

    def queue_investigate(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = _existing(self.root, payload.get("event"), "事件")
        knowledge = _existing(self.root, payload.get("knowledge"), "知识目录", directory=True)

        def work() -> dict[str, Any]:
            report = run_investigation(
                event=json.loads(event.read_text(encoding="utf-8")),
                knowledge=KnowledgeBase(knowledge),
                llm=LlmClient(),
                output_dir=str(self.root / "data" / "enrichment"),
            )
            return {"event_id": report.get("event_id"), "investigation_status": report.get("investigation_status")}

        return self.jobs.start("investigate", work)

    def _orchestrator(self) -> Orchestrator:
        init_from_repo(self.root)
        return Orchestrator(repo_root=self.root, work_root=self.root, llm=LlmClient())

    def _repository(self) -> RuleRepository:
        return RuleRepository(self.root / "data" / "rule_repository")


def _repo_root() -> Path:
    here = Path(__file__).resolve().parents[2]
    if (here / "configs" / "llm.yaml").is_file():
        return here
    return find_repo_root()


def _existing(root: Path, value: Any, label: str, *, directory: bool = False) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label}不能为空")
    path = Path(text)
    if not path.is_absolute():
        path = root / path
    if directory and not path.is_dir():
        raise ValueError(f"{label}不存在: {path}")
    if not directory and not path.is_file():
        raise ValueError(f"{label}不存在: {path}")
    return path


def _read(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _json_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)


def _jsonl_head(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            rows.append(item)
        if len(rows) >= limit:
            break
    return rows


def _jsonl_all(path: Path) -> list[dict[str, Any]]:
    return _jsonl_head(path, 100000)


def _run_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": item.get("run_id"),
        "source_name": item.get("source_name"),
        "category": item.get("category"),
        "stage": item.get("stage"),
        "status": item.get("status"),
        "blockers": item.get("blockers") or [],
        "activity": item.get("activity") or "",
        "updated_hint": "",
    }


def _candidate_summary(document: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    detail = _candidate_detail(document, root)
    return {
        "candidate_id": detail["candidate_id"],
        "status": detail["status"],
        "source_name": detail["source_name"],
        "standard_schema_id": detail["standard_schema_id"],
        "mapping_mode": detail["mapping_mode"],
        "mapping_count": len(detail["mappings"]),
        "error_count": len(detail["errors"]),
        "source_field_count": detail["source_field_count"],
        "mapped_field_count": detail["mapped_field_count"],
        "unmapped_field_count": detail["unmapped_field_count"],
    }


def _rules_view(item: dict[str, Any]) -> list[dict[str, Any]]:
    rules = []
    extraction = item.get("extraction_rule")
    cleaning = item.get("cleaning_rule")
    if isinstance(extraction, dict):
        rules.append(_rule_view("extraction", extraction))
    if isinstance(cleaning, dict):
        rules.append(_rule_view("cleaning", cleaning))
    return rules


def _rule_view(kind: str, rule: dict[str, Any]) -> dict[str, Any]:
    test = rule.get("test_result") if isinstance(rule.get("test_result"), dict) else {}
    previews = []
    for item in (test.get("previews") or [])[:5]:
        if isinstance(item, dict):
            previews.append({"input": item.get("input"), "output": item.get("output")})
    group = rule.get("group")
    return {
        "kind": kind,
        "rule_id": rule.get("rule_id") or "",
        "rule_type": rule.get("rule_type") or "",
        "operator": rule.get("operator") or "",
        "pattern": rule.get("pattern") or "",
        "group": group if isinstance(group, int) else None,
        "input_formats": [str(value) for value in rule.get("input_formats") or []],
        "output_format": rule.get("output_format") or "",
        "description": rule.get("description") or "",
        "passed": test.get("passed"),
        "previews": previews,
    }


def _candidate_detail(document: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    source = document.get("source_table") or {}
    mappings = []
    for item in document.get("mappings") or []:
        if not isinstance(item, dict):
            continue
        quality = item.get("quality") or {}
        extraction = item.get("extraction_rule") or {}
        cleaning = item.get("cleaning_rule") or {}
        validation = item.get("validation") or {}
        rules = _rules_view(item)
        test = (extraction or cleaning or {}).get("test_result") or {}
        errors = test.get("errors") or []
        mappings.append(
            {
                "source_field": item.get("source_field"),
                "target_field": item.get("target_field"),
                "confidence": item.get("confidence"),
                "direct_mapping": bool(quality.get("direct_mapping")),
                "needs_cleaning": bool(quality.get("needs_cleaning")),
                "needs_extraction": bool(quality.get("needs_extraction")),
                "validation_ok": bool(validation.get("ok")),
                "rule_id": rules[0]["rule_id"] if rules else "",
                "rules": rules,
                "test_message": (errors[0] if errors else quality.get("analysis") or item.get("explanation") or "")[:240],
            }
        )
    coverage = _candidate_coverage(root or Path("."), document)
    unmapped = _unmapped_view(document)
    return {
        "candidate_id": document.get("candidate_id"),
        "status": document.get("status"),
        "source_name": source.get("name") if isinstance(source, dict) else "",
        "source_table": source.get("sample_path") if isinstance(source, dict) else "",
        "standard_schema_id": document.get("standard_schema_id"),
        "mapping_mode": document.get("mapping_mode"),
        "errors": document.get("errors") or [],
        "mappings": mappings,
        **coverage,
        **unmapped,
    }


def _load_candidates(root: Path) -> list[dict[str, Any]]:
    items = []
    for path in _json_files(root / "outputs" / "candidates"):
        payload = _read(path)
        if payload:
            items.append(payload)
    return items


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _field_coverage(source_count: int, mapped_count: int) -> dict[str, int]:
    mapped_count = max(_as_int(mapped_count), 0)
    source_count = max(_as_int(source_count), mapped_count)
    return {
        "source_field_count": source_count,
        "mapped_field_count": mapped_count,
        "unmapped_field_count": max(source_count - mapped_count, 0),
    }


def _csv_field_count(root: Path, sample_path: str) -> int:
    if not sample_path:
        return 0
    path = Path(sample_path)
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        return 0
    try:
        first = path.read_text(encoding="utf-8-sig").splitlines()[:1]
    except OSError:
        return 0
    if not first:
        return 0
    try:
        return len(next(csv.reader(StringIO(first[0]))))
    except StopIteration:
        return 0


def _mapped_source_fields(items: list[Any], source_key: str, target_key: str) -> set[str]:
    mapped: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        source_field = str(item.get(source_key) or "").strip()
        target_field = str(item.get(target_key) or "").strip()
        if source_field and target_field:
            mapped.add(source_field)
    return mapped


def _unmapped_view(document: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for item in document.get("unmapped_fields") or []:
        if not isinstance(item, dict):
            continue
        source_field = str(item.get("source_field") or "").strip()
        reason = str(item.get("reason") or "").strip() or "未给出原因"
        evidence = [str(value).strip() for value in item.get("evidence") or [] if str(value).strip()]
        rows.append({"source_field": source_field, "reason": reason, "evidence": evidence})
    groups: dict[str, dict[str, Any]] = {}
    for item in rows:
        group = groups.setdefault(
            item["reason"],
            {"reason": item["reason"], "count": 0, "fields": [], "items": []},
        )
        group["count"] += 1
        if item["source_field"]:
            group["fields"].append(item["source_field"])
        group["items"].append(item)
    overview = sorted(groups.values(), key=lambda item: (-int(item["count"]), str(item["reason"])))
    return {"unmapped_fields": rows, "unmapped_overview": overview}


def _candidate_coverage(root: Path, document: dict[str, Any]) -> dict[str, int]:
    source = document.get("source_table") if isinstance(document.get("source_table"), dict) else {}
    mapped = _mapped_source_fields(document.get("mappings") or [], "source_field", "target_field")
    source_count = _as_int(source.get("field_count"))
    if not source_count:
        source_count = _csv_field_count(root, str(source.get("sample_path") or ""))
    if not source_count:
        source_count = len(
            {
                str(item.get("source_field") or "").strip()
                for item in document.get("mappings") or []
                if isinstance(item, dict) and str(item.get("source_field") or "").strip()
            }
        )
    return _field_coverage(source_count, len(mapped))


def _candidate_for_pipeline(
    pipeline: dict[str, Any],
    mapped: set[str],
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    source_table = str(pipeline.get("source_table") or "").strip()
    named: list[dict[str, Any]] = []
    scored: list[tuple[int, dict[str, Any]]] = []
    for payload in candidates:
        source = payload.get("source_table") if isinstance(payload.get("source_table"), dict) else {}
        name = str(source.get("name") or "").strip()
        mapping_sources = {
            str(item.get("source_field") or "").strip()
            for item in payload.get("mappings") or []
            if isinstance(item, dict) and str(item.get("source_field") or "").strip()
        }
        if source_table and name == source_table:
            named.append(payload)
            continue
        overlap = len(mapped & mapping_sources)
        if overlap:
            scored.append((overlap, payload))
    if named:
        confirmed = [item for item in named if item.get("status") == "confirmed"]
        return (confirmed or named)[0]
    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]
    return None


def _mapping_summary(
    root: Path,
    pipeline: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    mapped = _mapped_source_fields(pipeline.get("fields") or [], "source_field", "standard_field")
    candidate = _candidate_for_pipeline(
        pipeline,
        mapped,
        candidates if candidates is not None else _load_candidates(root),
    )
    source_count = _candidate_coverage(root, candidate)["source_field_count"] if candidate else 0
    return _field_coverage(source_count, len(mapped))


def _field_step(item: dict[str, Any], rules: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    rule_ids = [str(rule_id) for rule_id in item.get("rule_ids") or [] if rule_id]
    if not rule_ids and item.get("rule_id"):
        rule_ids = [str(item["rule_id"])]
    operators: list[str] = []
    versions: list[str] = []
    for rule_id in rule_ids:
        version = _rule_version((rules or {}).get(rule_id) or {})
        if version.get("operator"):
            operators.append(str(version["operator"]))
        if version.get("version") is not None:
            versions.append(str(version["version"]))
    return {
        "source_field": item.get("source_field") or "",
        "field": item.get("standard_field") or item.get("field") or "",
        "operator": "、".join(operators) or item.get("operator") or "passthrough",
        "rule_id": "、".join(rule_ids) or "—",
        "active_version": "、".join(versions) or (str(item["active_version"]) if item.get("active_version") else "—"),
        "canary_version": item.get("canary_version") if item.get("canary_version") not in (None, "") else "—",
    }


def _rule_version(rule: dict[str, Any]) -> dict[str, Any]:
    versions = [item for item in rule.get("versions") or [] if isinstance(item, dict)]
    active = rule.get("active_version")
    if active is not None:
        matched = next((item for item in versions if item.get("version") == active), None)
        if matched:
            return matched
    return versions[-1] if versions else {}


def _event_message(item: dict[str, Any]) -> str:
    error = str(item.get("error") or "")
    raw = item.get("raw_value")
    if raw not in (None, "") and error:
        return f"{error}：{raw}"
    if error:
        return error
    return json.dumps(item, ensure_ascii=False)[:180]


def _preview_notice(fields: list[dict[str, Any]], rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "还没有解析结果。"
    if any(value not in (None, "") for row in rows for value in row.values()):
        return ""
    sources = [str(item.get("source_field") or "") for item in fields if item.get("source_field")]
    shown = "、".join(sources[:8])
    return f"解析结果全是空值。Pipeline 只读取源字段 {shown}。当前结果文件的输入表没有这些列。"


def _issue_view(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "issue_id": issue.get("issue_id"),
        "title": issue.get("issue_title") or issue.get("title") or issue.get("issue_id"),
        "severity": issue.get("severity") or "",
        "field": issue.get("field_name") or issue.get("field") or "",
        "dimension": issue.get("dimension") or "",
        "metric": issue.get("rule_id") or issue.get("metric") or "",
        "value": issue.get("abnormal_rate") if issue.get("abnormal_rate") is not None else issue.get("value"),
        "threshold": issue.get("threshold") if issue.get("threshold") is not None else "",
        "description": issue.get("issue_description") or "",
    }


def _diagnosis_view(diagnosis: dict[str, Any]) -> dict[str, Any]:
    task = diagnosis.get("task") or {}
    verified = diagnosis.get("verified_causes") or diagnosis.get("verified") or []
    unverified = diagnosis.get("unverified_causes") or diagnosis.get("unverified") or []
    return {
        "summary": diagnosis.get("diagnosis_summary") or diagnosis.get("summary") or "",
        "verified": [_text(item) for item in verified],
        "unverified": [_text(item) for item in unverified],
        "task": {
            "task_id": task.get("task_id") or "",
            "target_agent": task.get("target_agent") or "",
            "description": task.get("task_description") or task.get("description") or "",
            "verification_metrics": task.get("verification_plan") or task.get("verification_metrics") or [],
        },
    }


def _text(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("statement") or item.get("summary") or item)
    return str(item)


def _pick_event(events: list[dict[str, Any]], event_id: str, index: int) -> dict[str, Any]:
    if event_id:
        found = next((item for item in events if item.get("event_id") == event_id), None)
        if found:
            return found
        raise ValueError("没有找到这条事件")
    if 1 <= index <= len(events):
        return events[index - 1]
    raise ValueError("请选择一条事件")


def _has_event_content(record: dict[str, Any]) -> bool:
    return any(record.get(field) for field in ("event_type", "src_ip", "dst_ip", "domain", "timestamp"))


def _parsed_events(root: Path) -> dict[str, dict[str, Any]]:
    folder = root / "outputs" / "parsed"
    found: dict[str, dict[str, Any]] = {}
    if not folder.is_dir():
        return found
    for path in folder.glob("*.jsonl"):
        for event in adapt_events(_jsonl_all(path)):
            found.setdefault(str(event.get("event_id") or ""), event)
    return found


_APPLIED_LABELS = {"auto_accepted", "needs_review", "investigation_required"}
_ENRICH_SUMMARY: dict[str, Any] = {"key": None, "value": None}


def _empty_enrichment_summary() -> dict[str, Any]:
    return {
        "total": 0,
        "all_total": 0,
        "labeled": 0,
        "unlabeled": 0,
        "investigation_required": 0,
        "labels": [{"name": name, "count": 0} for name in RISK_NAMES],
    }


def _event_ids_from_input(root: Path, source_text: str) -> set[str] | None:
    text = str(source_text or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        return None
    return {str(item.get("event_id") or "") for item in adapt_events(_jsonl_all(path)) if item.get("event_id")}


def _summarize_enrichment_records(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {name: 0 for name in RISK_NAMES}
    extras: dict[str, int] = {}
    labeled = 0
    unlabeled = 0
    investigations = 0
    for record in payloads:
        names: set[str] = set()
        for item in record.get("labels") or []:
            if not isinstance(item, dict) or item.get("status") not in _APPLIED_LABELS:
                continue
            name = str(item.get("name") or "").strip()
            if name:
                names.add(name)
        if names:
            labeled += 1
            for name in names:
                if name in counts:
                    counts[name] += 1
                else:
                    extras[name] = extras.get(name, 0) + 1
        else:
            unlabeled += 1
        if record.get("investigation_status") == "investigation_required":
            investigations += 1
    labels = [{"name": name, "count": counts[name]} for name in RISK_NAMES]
    labels.extend(
        {"name": name, "count": extras[name]}
        for name in sorted(extras, key=lambda item: (-extras[item], item))
    )
    return {
        "total": len(payloads),
        "all_total": len(payloads),
        "labeled": labeled,
        "unlabeled": unlabeled,
        "investigation_required": investigations,
        "labels": labels,
    }


def _record_is_labeled(record: dict[str, Any]) -> bool:
    for item in record.get("labels") or []:
        if not isinstance(item, dict) or item.get("status") not in _APPLIED_LABELS:
            continue
        if str(item.get("name") or "").strip():
            return True
    return False


def _shown_records(payloads: list[dict[str, Any]], limit: int = 40) -> list[dict[str, Any]]:
    labeled = [item for item in payloads if _record_is_labeled(item)]
    unlabeled = [item for item in payloads if not _record_is_labeled(item)]
    return [*labeled, *unlabeled][:limit]


def _load_enrichment_payloads(folder: Path, paths: list[Path]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    newest = paths[0].stat().st_mtime if paths else 0
    key = (str(folder), len(paths), newest)
    cached = _ENRICH_SUMMARY.get("payloads")
    if _ENRICH_SUMMARY["key"] == key and isinstance(cached, list):
        return cached, _ENRICH_SUMMARY["value"]
    payloads = [payload for path in paths if (payload := _read(path))]
    summary = _summarize_enrichment_records(payloads)
    _ENRICH_SUMMARY["key"] = key
    _ENRICH_SUMMARY["value"] = summary
    _ENRICH_SUMMARY["payloads"] = payloads
    return payloads, summary


def _summarize_enrichment_files(folder: Path, paths: list[Path]) -> dict[str, Any]:
    return _load_enrichment_payloads(folder, paths)[1]


def _record_view(record: dict[str, Any], event: dict[str, Any] | None = None) -> dict[str, Any]:
    source = event or {}
    def value(field: str) -> str:
        return str(record.get(field) or source.get(field) or "")

    return {
        "event_id": record.get("event_id"),
        "event_type": value("event_type"),
        "timestamp": value("timestamp"),
        "src_ip": value("src_ip"),
        "dst_ip": value("dst_ip"),
        "domain": value("domain"),
        "facts": record.get("facts") or [],
        "labels": [item for item in record.get("labels") or [] if item.get("status") in {"auto_accepted", "needs_review", "investigation_required"}],
        "investigation_status": record.get("investigation_status") or "not_required",
    }


def _investigation_view(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": report.get("event_id"),
        "investigation_status": report.get("investigation_status") or "",
        "recommendation": report.get("recommendation") or "",
        "facts": report.get("facts") or [],
        "labels": report.get("labels") or [],
        "missing_evidence": report.get("missing_evidence") or [],
        "decisions": report.get("decisions") or [],
    }


def _matching(folder: Path, key: str, value: str) -> dict[str, Any] | None:
    for path in _json_files(folder):
        payload = _read(path)
        if payload and payload.get(key) == value:
            return payload
    return None


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value) or "event"


def display_paths(root: Path, value: Any) -> Any:
    """把返回给前端的仓库内绝对路径换成相对路径。"""
    if isinstance(value, dict):
        return {key: display_paths(root, item) for key, item in value.items()}
    if isinstance(value, list):
        return [display_paths(root, item) for item in value]
    if isinstance(value, str):
        return _relative_text(root, value)
    return value


def _relative_text(root: Path, text: str) -> str:
    base = root.resolve()
    stripped = text.strip()
    path = Path(stripped)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(base).as_posix()
        except ValueError:
            return stripped
    prefixes = []
    for item in (str(base), base.as_posix(), str(root), root.as_posix()):
        if item and item not in prefixes:
            prefixes.append(item)
    prefixes.sort(key=len, reverse=True)
    updated = text
    changed = False
    for prefix in prefixes:
        updated, replaced = _strip_prefix(updated, prefix)
        changed = changed or replaced
    if not changed:
        if "\\" in text and not any(char.isspace() for char in text):
            return text.replace("\\", "/")
        return text
    return updated.replace("\\", "/")


def _strip_prefix(text: str, prefix: str) -> tuple[str, bool]:
    parts: list[str] = []
    start = 0
    changed = False
    while True:
        index = text.find(prefix, start)
        if index < 0:
            parts.append(text[start:])
            break
        end = index + len(prefix)
        if end < len(text) and text[end] not in "\\/":
            parts.append(text[start:end])
            start = end
            continue
        parts.append(text[start:index])
        if end < len(text) and text[end] in "\\/":
            end += 1
        start = end
        changed = True
    return "".join(parts), changed


def _source_entry(source_id: str, category: str) -> dict[str, Any]:
    return {"source_id": source_id, "category": category, "has_saved_baseline": False, "snapshots": []}


def _pick_source(sources: list[dict[str, Any]], source_id: str, category: str) -> dict[str, Any] | None:
    if source_id:
        matches = [item for item in sources if item.get("source_id") == source_id]
        if category:
            matches = [item for item in matches if item.get("category") == category] or matches
        return matches[0] if matches else None
    with_snapshots = [item for item in sources if item.get("snapshots")]
    return (with_snapshots or sources or [None])[0]


def _default_baseline_id(snapshots: list[dict[str, Any]]) -> str:
    saved = next((item["id"] for item in snapshots if item.get("kind") == "baseline"), "")
    if saved:
        return saved
    reports = [item for item in snapshots if item.get("kind") == "report"]
    return str(reports[0]["id"]) if reports else ""


def _default_current_id(snapshots: list[dict[str, Any]]) -> str:
    reports = [item for item in snapshots if item.get("kind") == "report"]
    if not reports:
        return ""
    baseline_id = _default_baseline_id(snapshots)
    if len(reports) == 1:
        return "" if reports[0]["id"] == baseline_id else str(reports[0]["id"])
    current = reports[-1]
    if current["id"] == baseline_id and len(reports) > 1:
        return str(reports[-2]["id"])
    return str(current["id"])


def _empty_notice(source: dict[str, Any], baseline_id: str, current_id: str) -> str:
    if not source.get("snapshots"):
        return "还没有质量报告"
    if not source.get("has_saved_baseline") and not baseline_id:
        return "该来源还没有正式基线，可用报告当基线或点设为基线"
    if baseline_id and not current_id:
        return "请选择与当前不同的基线"
    return "还没有质量报告"


def _scalar_metrics(payload: dict[str, Any]) -> dict[str, float]:
    metrics = payload.get("metrics") or {}
    result: dict[str, float] = {}
    for key, value in metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        result[str(key)] = float(value)
    return result


def _metric_comparisons(baseline: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    left = _scalar_metrics(baseline)
    right = _scalar_metrics(current)
    rows = []
    for key in sorted(set(left) | set(right)):
        base = left.get(key)
        observed = right.get(key)
        delta = None
        if base is not None and observed is not None:
            delta = observed - base
        rows.append({"metric": key, "baseline": base, "current": observed, "delta": delta})
    return rows


_KNOWLEDGE_FILES = {
    "assets": ("assets.json", "assets", ("ip",)),
    "indicators": ("intel.json", "indicators", ("indicator_type", "value", "source")),
    "history": ("history.json", "records", ("indicator_type", "value")),
}


def _knowledge_root(root: Path, directory: str = "") -> Path:
    text = str(directory or "").strip()
    if text:
        return _existing(root, text, "知识目录", directory=True)
    return root / "data" / "enrichment_knowledge"


def _knowledge_spec(root: Path, directory: str, kind: str) -> tuple[Path, str, str, tuple[str, ...]]:
    spec = _KNOWLEDGE_FILES.get(kind)
    if spec is None:
        raise ValueError("知识类型只能是资产、情报或历史")
    folder = _knowledge_root(root, directory)
    folder.mkdir(parents=True, exist_ok=True)
    return folder, spec[0], spec[1], spec[2]


def _knowledge_items(path: Path, key: str) -> list[dict[str, Any]]:
    payload = _read(path) if path.is_file() else None
    items = (payload or {}).get(key) if payload else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _write_knowledge(path: Path, key: str, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({key: items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _find_knowledge(items: list[dict[str, Any]], match: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    wanted = tuple(str(match.get(key) or "").strip().lower() for key in keys)
    if not any(wanted):
        return None
    for index, item in enumerate(items):
        current = tuple(str(item.get(key) or "").strip().lower() for key in keys)
        if current == wanted:
            return index
    return None


def _normalize_knowledge_item(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    stored = {key: value for key, value in item.items() if value is not None}
    if kind == "assets":
        ip = str(stored.get("ip") or "").strip()
        if not ip:
            raise ValueError("资产需要地址")
        name = str(stored.get("name") or stored.get("asset_name") or "").strip()
        importance = str(stored.get("importance") or "").strip()
        if importance:
            key_asset = importance == "重点"
        elif stored.get("is_key_asset") is not None:
            key_asset = bool(stored.get("is_key_asset"))
        else:
            key_asset = False
        importance = "重点" if key_asset else "普通"
        stored.update(
            {
                "ip": ip,
                "name": name or ip,
                "asset_name": str(stored.get("asset_name") or name or ip),
                "importance": "重点" if key_asset else "普通",
                "is_internal": True if stored.get("is_internal") is None else bool(stored.get("is_internal")),
                "is_key_asset": key_asset,
                "asset_level": stored.get("asset_level") or ("critical" if key_asset else "normal"),
            }
        )
        return stored
    indicator_type = str(stored.get("indicator_type") or "").strip()
    value = str(stored.get("value") or "").strip()
    if indicator_type not in {"ip", "domain"} or not value:
        raise ValueError("需要类型和值")
    stored["indicator_type"] = indicator_type
    stored["value"] = value
    if kind == "indicators":
        stored["source"] = str(stored.get("source") or "").strip() or "osint_feed"
        stored["threat_status"] = str(stored.get("threat_status") or "suspicious")
        stored["confidence"] = str(stored.get("confidence") or "medium")
    return stored


def _mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, zone("Asia/Shanghai")).isoformat()
    except OSError:
        return ""
