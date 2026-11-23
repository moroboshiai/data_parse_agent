"""示例数据。确认和继续只改进程内副本。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from governance.store import RunBusyError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
STAGES = (
    "intake",
    "register",
    "await_confirm",
    "build_pipeline",
    "parse",
    "init_profile",
    "quality_analyze",
    "enrich",
    "review",
    "done",
)


class DemoStore:
    def __init__(self) -> None:
        self.candidates = _load("candidates.json")["candidates"]
        self.pipelines = _load("pipelines.json")["pipelines"]
        self.quality = _load("quality.json")
        self.enrichment = _load("enrichment.json")
        self.runs = _load("runs.json")["runs"]

    def dashboard(self) -> dict[str, Any]:
        pending = [item for item in self.candidates if item["status"] != "confirmed"]
        active_runs = [item for item in self.runs if item["stage"] != "done"]
        events = sum(len(item.get("events") or []) for item in self.pipelines)
        issues = self.quality["issues"]
        return {
            "metrics": [
                {"key": "runs", "label": "进行中任务", "value": len(active_runs), "hint": "未到 done 的治理运行"},
                {"key": "candidates", "label": "待确认候选", "value": len(pending), "hint": "pending_review / pending_confirm"},
                {"key": "events", "label": "解析失败事件", "value": events, "hint": "示例 Pipeline 中的 events"},
                {"key": "issues", "label": "质检问题", "value": len(issues), "hint": "当前报告中的问题单"},
            ],
            "runs": [_run_summary(item) for item in self.runs],
            "stages": list(STAGES),
        }

    def list_runs(self) -> list[dict[str, Any]]:
        return [_run_summary(item) for item in self.runs]

    def get_run(self, run_id: str) -> dict[str, Any]:
        return deepcopy(_find(self.runs, "run_id", run_id))

    def delete_run(self, run_id: str) -> dict[str, Any]:
        run = _find(self.runs, "run_id", run_id)
        if run.get("activity"):
            raise RunBusyError("任务正在执行，结束后再删除")
        self.runs = [item for item in self.runs if item.get("run_id") != run_id]
        return {"deleted": True, "run_id": run_id}

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_name = str(payload.get("source_name") or "").strip()
        standard = str(payload.get("standard_schema_path") or "").strip()
        sample = str(payload.get("sample_path") or "").strip()
        if not source_name or not standard or not sample:
            raise ValueError("来源名、样本和规范表不能为空")
        category = _category(standard)
        run_id = f"{_safe(source_name)}__{_safe(category)}"
        existing = next((item for item in self.runs if item["run_id"] == run_id), None)
        if existing is not None:
            return deepcopy(existing)
        candidate_id = f"demo-{_safe(source_name)}"
        run = {
            "run_id": run_id,
            "source_name": source_name,
            "category": category,
            "stage": "await_confirm",
            "status": "awaiting_confirm",
            "sample_path": sample,
            "input_path": str(payload.get("input_path") or sample),
            "standard_schema_path": standard,
            "knowledge_path": str(payload.get("knowledge_path") or ""),
            "candidate_path": f"outputs/candidates/{candidate_id}.json",
            "pipeline_id": "",
            "parsed_path": "",
            "profile_path": "",
            "parse_event_count": 0,
            "enrichment_count": 0,
            "blockers": ["等待确认候选映射"],
            "artifacts": [{"kind": "candidate", "path": f"outputs/candidates/{candidate_id}.json", "status": "pending_confirm"}],
            "history": [
                {"stage": "intake", "action": "start", "detail": source_name},
                {"stage": "register", "action": "registered", "detail": "静态示例：已生成待确认候选"},
            ],
        }
        self.runs.insert(0, run)
        return deepcopy(run)

    def confirm_run(self, run_id: str) -> dict[str, Any]:
        run = _find(self.runs, "run_id", run_id)
        if run["stage"] != "await_confirm":
            raise ValueError("当前阶段不能确认候选")
        pipeline_id = run["pipeline_id"] or f"pipeline_{_safe(run['source_name'])}"
        run["stage"] = "review"
        run["status"] = "review"
        run["pipeline_id"] = pipeline_id
        run["parsed_path"] = f"outputs/parsed/{pipeline_id}.jsonl"
        run["profile_path"] = f"data/quality/profiles/{run['category']}.json"
        run["parse_event_count"] = 1 if run["category"] == "dns_log" else 0
        run["enrichment_count"] = 1 if run.get("knowledge_path") else 0
        if run.get("knowledge_path"):
            run["blockers"] = []
        else:
            run["blockers"] = ["未提供知识目录，富化已跳过"]
        run["artifacts"] = [
            *(run.get("artifacts") or []),
            {"kind": "pipeline", "path": pipeline_id, "status": "active"},
            {"kind": "parsed", "path": run["parsed_path"], "events": run["parse_event_count"]},
            {"kind": "profile", "path": run["profile_path"]},
        ]
        run["history"] = [
            *(run.get("history") or []),
            {"stage": "await_confirm", "action": "confirm", "detail": "静态示例：确认后停在复核"},
        ]
        return deepcopy(run)

    def resume_run(self, run_id: str) -> dict[str, Any]:
        run = _find(self.runs, "run_id", run_id)
        if run["stage"] == "done":
            return deepcopy(run)
        if run["stage"] != "review":
            raise ValueError("当前阶段请使用确认，或等待到达复核")
        run["stage"] = "done"
        run["status"] = "done"
        run["blockers"] = []
        run["history"] = [
            *(run.get("history") or []),
            {"stage": "review", "action": "finish", "detail": "静态示例：结束运行，不发布解析规则"},
        ]
        return deepcopy(run)

    def list_candidates(self) -> list[dict[str, Any]]:
        rows = []
        for item in self.candidates:
            coverage = _mapping_coverage(item.get("mappings") or [])
            rows.append(
                {
                    "candidate_id": item["candidate_id"],
                    "status": item["status"],
                    "source_name": item["source_name"],
                    "standard_schema_id": item["standard_schema_id"],
                    "mapping_mode": item["mapping_mode"],
                    "mapping_count": len(item["mappings"]),
                    "error_count": len(item["errors"]),
                    **coverage,
                }
            )
        return rows

    def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        item = deepcopy(_find(self.candidates, "candidate_id", candidate_id))
        for mapping in item.get("mappings") or []:
            if isinstance(mapping, dict) and "rules" not in mapping:
                mapping["rules"] = _demo_rules(mapping)
        item.update(_mapping_coverage(item.get("mappings") or []))
        item.update(_unmapped_view(item.get("unmapped_fields") or []))
        return item

    def update_candidate(self, candidate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        item = _find(self.candidates, "candidate_id", candidate_id)
        mappings = item.get("mappings") or []
        for edit in payload.get("mappings") or []:
            index = int(edit.get("index"))
            if index < 0 or index >= len(mappings):
                raise ValueError(f"映射序号超出范围: {index}")
            row = mappings[index]
            source_field = str(edit.get("source_field") or "").strip()
            target_field = str(edit.get("target_field") or "").strip()
            if not source_field or not target_field:
                raise ValueError("来源字段和规范字段不能为空")
            row["source_field"] = source_field
            row["target_field"] = target_field
            rules = [rule for rule in edit.get("rules") or [] if isinstance(rule, dict)]
            if rules:
                row["rule_id"] = str(rules[0].get("rule_id") or "")
                row["rules"] = rules
        return self.get_candidate(candidate_id)

    def delete_candidate(self, candidate_id: str) -> dict[str, Any]:
        _find(self.candidates, "candidate_id", candidate_id)
        self.candidates = [item for item in self.candidates if item.get("candidate_id") != candidate_id]
        return {"deleted": True, "candidate_id": candidate_id}

    def list_pipelines(self) -> list[dict[str, Any]]:
        return [
            {
                "pipeline_id": item["pipeline_id"],
                "status": item["status"],
                "source_name": item["source_name"],
                "source_type": item["source_type"],
                "event_count": len(item.get("events") or []),
                "step_count": len(item.get("field_steps") or []),
                "source_field_count": len(item.get("field_steps") or []),
                "mapped_field_count": len(item.get("field_steps") or []),
                "unmapped_field_count": 0,
            }
            for item in self.pipelines
        ]

    def pipeline_preview(self, pipeline_id: str) -> dict[str, Any]:
        item = _find(self.pipelines, "pipeline_id", pipeline_id)
        return {
            "pipeline_id": item["pipeline_id"],
            "status": item["status"],
            "source_type": item["source_type"],
            "source_name": item.get("source_name") or "",
            "source_field_count": len(item.get("field_steps") or []),
            "mapped_field_count": len(item.get("field_steps") or []),
            "unmapped_field_count": 0,
            "event_count": len(item.get("events") or []),
            "field_steps": item["field_steps"],
            "rows": item["preview"],
            "learn_decisions": item["learn_decisions"],
            "rules": item["rules"],
            "notice": "发布与回滚须人工执行。主控不会自动 publish。",
        }

    def pipeline_events(self, pipeline_id: str) -> dict[str, Any]:
        item = _find(self.pipelines, "pipeline_id", pipeline_id)
        return {"pipeline_id": pipeline_id, "events": item.get("events") or []}

    def delete_pipeline(self, pipeline_id: str) -> dict[str, Any]:
        _find(self.pipelines, "pipeline_id", pipeline_id)
        self.pipelines = [item for item in self.pipelines if item.get("pipeline_id") != pipeline_id]
        return {"deleted": True, "pipeline_id": pipeline_id}

    def quality_profiles(self) -> list[dict[str, Any]]:
        return deepcopy(self.quality["profiles"])

    def quality_reports(self) -> list[dict[str, Any]]:
        return deepcopy(self.quality["reports"])

    def quality_issue(self, issue_id: str) -> dict[str, Any]:
        issue = _find(self.quality["issues"], "issue_id", issue_id)
        diagnosis = next((item for item in self.quality["diagnoses"] if item["issue_id"] == issue_id), None)
        return {"issue": deepcopy(issue), "diagnosis": deepcopy(diagnosis), "baseline": deepcopy(self.quality["baseline"])}

    def quality_baselines(self) -> list[dict[str, Any]]:
        baseline = deepcopy(self.quality["baseline"])
        reports = [item for item in self.quality["reports"] if item.get("source_id") == baseline.get("source_id")]
        snapshots = [
            {
                "id": "saved",
                "kind": "baseline",
                "label": "正式基线",
                "volume": baseline.get("volume") or 0,
                "updated_at": baseline.get("updated_at") or "",
            }
        ]
        for item in reports:
            snapshots.append(
                {
                    "id": item.get("report_id") or "",
                    "kind": "report",
                    "label": item.get("report_id") or "",
                    "volume": item.get("row_count") or 0,
                    "updated_at": item.get("window") or "",
                }
            )
        return [
            {
                "source_id": baseline.get("source_id") or "",
                "category": baseline.get("category") or "",
                "has_saved_baseline": True,
                "snapshots": snapshots,
            }
        ]

    def quality_baseline(self, source_id: str = "", category: str = "", baseline: str = "", current: str = "") -> dict[str, Any]:
        payload = deepcopy(self.quality["baseline"])
        payload["baseline_id"] = baseline or "saved"
        payload["current_id"] = current or (self.quality["reports"][0].get("report_id") if self.quality.get("reports") else "")
        payload["baseline_volume"] = payload.get("volume") or 0
        payload["baseline_updated_at"] = payload.get("updated_at") or ""
        payload["notice"] = ""
        if source_id:
            payload["source_id"] = source_id
        if category:
            payload["category"] = category
        return payload

    def set_quality_baseline(self, source_id: str, category: str, snapshot_id: str) -> dict[str, Any]:
        return {"source_id": source_id, "category": category, "baseline_path": "", "snapshot_id": snapshot_id, "message": "静态演示不写入基线文件"}

    def enrichment_records(self) -> list[dict[str, Any]]:
        return deepcopy(self.enrichment["records"])

    def enrichment_page(self) -> dict[str, Any]:
        records = self.enrichment_records()
        summary = _enrichment_summary(records)
        summary["all_total"] = summary["total"]
        applied = {"auto_accepted", "needs_review", "investigation_required"}

        def labeled(record: dict[str, Any]) -> bool:
            return any(
                isinstance(item, dict)
                and item.get("status") in applied
                and str(item.get("name") or "").strip()
                for item in record.get("labels") or []
            )

        ordered = [item for item in records if labeled(item)] + [item for item in records if not labeled(item)]
        return {"records": ordered, "summary": summary}

    def investigation(self, event_id: str) -> dict[str, Any]:
        return deepcopy(_find(self.enrichment["investigations"], "event_id", event_id))

    def knowledge(self) -> dict[str, Any]:
        payload = deepcopy(self.enrichment["knowledge"])
        payload.setdefault("path", "demo")
        return payload

    def add_knowledge(self, kind: str, item: dict[str, Any], directory: str = "") -> dict[str, Any]:
        items = self._knowledge_list(kind)
        items.append(dict(item))
        return {"kind": kind, "item": dict(item)}

    def update_knowledge(self, kind: str, match: dict[str, Any], item: dict[str, Any], directory: str = "") -> dict[str, Any]:
        items = self._knowledge_list(kind)
        index = self._knowledge_index(kind, match)
        items[index] = {**items[index], **item}
        return {"kind": kind, "item": dict(items[index])}

    def delete_knowledge(self, kind: str, match: dict[str, Any], directory: str = "") -> dict[str, Any]:
        items = self._knowledge_list(kind)
        items.pop(self._knowledge_index(kind, match))
        return {"kind": kind, "deleted": True}

    def _knowledge_list(self, kind: str) -> list[dict[str, Any]]:
        mapping = {"assets": "assets", "indicators": "indicators", "history": "history"}
        key = mapping.get(kind)
        if key is None:
            raise ValueError("知识类型只能是资产、情报或历史")
        return self.enrichment["knowledge"].setdefault(key, [])

    def _knowledge_index(self, kind: str, match: dict[str, Any]) -> int:
        items = self._knowledge_list(kind)
        keys = {"assets": ("ip",), "indicators": ("indicator_type", "value", "source"), "history": ("indicator_type", "value")}[kind]
        wanted = tuple(str(match.get(key) or "") for key in keys)
        for index, item in enumerate(items):
            if tuple(str(item.get(key) or "") for key in keys) == wanted:
                return index
        raise KeyError(kind)


def _load(name: str) -> dict[str, Any]:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"示例文件格式错误: {name}")
    return payload


def _demo_rules(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    rule_id = str(mapping.get("rule_id") or "")
    if not rule_id:
        return []
    kind = "cleaning" if mapping.get("needs_cleaning") else "extraction"
    return [
        {
            "kind": kind,
            "rule_id": rule_id,
            "rule_type": "normalize_datetime" if kind == "cleaning" else "regex",
            "operator": "normalize_datetime" if kind == "cleaning" else "",
            "pattern": "",
            "group": None if kind == "cleaning" else 1,
            "input_formats": [],
            "output_format": "",
            "description": mapping.get("test_message") or "",
            "passed": mapping.get("validation_ok"),
            "previews": [],
        }
    ]


def _enrichment_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    applied = {"auto_accepted", "needs_review", "investigation_required"}
    counts: dict[str, int] = {}
    labeled = 0
    unlabeled = 0
    investigations = 0
    for record in records:
        names = {
            str(item.get("name") or "").strip()
            for item in record.get("labels") or []
            if isinstance(item, dict)
            and item.get("status") in applied
            and str(item.get("name") or "").strip()
        }
        if names:
            labeled += 1
            for name in names:
                counts[name] = counts.get(name, 0) + 1
        else:
            unlabeled += 1
        if record.get("investigation_status") == "investigation_required":
            investigations += 1
    return {
        "total": len(records),
        "labeled": labeled,
        "unlabeled": unlabeled,
        "investigation_required": investigations,
        "labels": [{"name": name, "count": counts[name]} for name in sorted(counts, key=lambda item: (-counts[item], item))],
    }


def _unmapped_view(raw: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for item in raw or []:
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


def _mapping_coverage(mappings: list[dict[str, Any]], source_count: int = 0) -> dict[str, int]:
    mapped = {
        str(item.get("source_field") or "").strip()
        for item in mappings or []
        if isinstance(item, dict)
        and str(item.get("source_field") or "").strip()
        and str(item.get("target_field") or "").strip()
    }
    mapped_count = len(mapped)
    source_count = max(int(source_count or 0), mapped_count)
    return {
        "source_field_count": source_count,
        "mapped_field_count": mapped_count,
        "unmapped_field_count": max(source_count - mapped_count, 0),
    }


def _find(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any]:
    for item in items:
        if item.get(key) == value:
            return item
    raise KeyError(value)


def _run_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": item["run_id"],
        "source_name": item["source_name"],
        "category": item["category"],
        "stage": item["stage"],
        "status": item["status"],
        "blockers": item.get("blockers") or [],
        "activity": item.get("activity") or "",
        "updated_hint": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


def _category(standard_path: str) -> str:
    name = Path(standard_path).name.lower()
    if "dns" in name:
        return "dns_log"
    if "flow" in name:
        return "flow_log"
    if "alarm" in name:
        return "alarm_event"
    return "generic"


def _safe(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned or "item"
