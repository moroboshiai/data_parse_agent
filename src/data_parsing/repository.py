"""JSON 规则仓库。版本只追加，检索按数据源范围分层。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from data_parsing.policies import RULE_STATUSES, RulePolicyError, assert_can_activate, assert_operator


class RuleRepository:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save_issue(self, issue: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            issues = self._read("issues.json", "issues")
            current = _match_issue(issues, issue)
            if current is None:
                stored = dict(issue)
                stored["issue_id"] = stored.get("issue_id") or _next_id(issues, "issue_id", "issue")
                issues.append(stored)
                current = stored
            else:
                current.update({key: value for key, value in issue.items() if key != "issue_id"})
            self._write("issues.json", "issues", issues)
            return dict(current)

    def list_issues(self, **filters: Any) -> list[dict[str, Any]]:
        return [dict(item) for item in self._read("issues.json", "issues") if _match(item, filters)]

    def create_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            rules = self._read("rules.json", "rules")
            rule = {
                "rule_id": payload.get("rule_id") or _next_id(rules, "rule_id", "rule"),
                "standard_field": payload["standard_field"],
                "source_type": payload.get("source_type") or "",
                "source_table": payload.get("source_table") or "",
                "source_field": payload.get("source_field") or "",
                "pipeline_id": payload.get("pipeline_id") or "",
                "rule_type": payload.get("rule_type") or "extraction",
                "active_version": None,
                "status": "discovered",
                "versions": [],
            }
            rules.append(rule)
            self._write("rules.json", "rules", rules)
            return dict(rule)

    def get_rule(self, rule_id: str) -> dict[str, Any]:
        for rule in self._read("rules.json", "rules"):
            if rule["rule_id"] == rule_id:
                return dict(rule)
        raise KeyError(f"找不到规则: {rule_id}")

    def list_rules(self, **filters: Any) -> list[dict[str, Any]]:
        return [dict(item) for item in self._read("rules.json", "rules") if _match(item, filters)]

    def append_version(self, rule_id: str, version: dict[str, Any]) -> dict[str, Any]:
        operator = assert_operator(str(version.get("operator") or ""))
        status = str(version.get("status") or "candidate")
        if status not in RULE_STATUSES:
            raise RulePolicyError(f"未知规则状态: {status}")
        test_status = str(version.get("test_status") or "pending")
        if status in {"validated", "canary", "active"} and test_status != "passed":
            raise RulePolicyError("未通过验证的规则不得自动成为生产规则")
        with self._lock:
            rules = self._read("rules.json", "rules")
            rule = _find(rules, "rule_id", rule_id)
            number = (rule["versions"][-1]["version"] + 1) if rule["versions"] else 1
            stored = {
                "version": number,
                "operator": operator,
                "params": dict(version.get("params") or {}),
                "test_status": test_status,
                "status": status,
                "created_from": version.get("created_from") or "manual",
                "test_report": dict(version.get("test_report") or {}),
            }
            if status == "active":
                assert_can_activate(stored)
                _deprecate_active(rule)
                rule["active_version"] = number
                rule["status"] = "active"
            elif status == "validated" and rule["status"] != "active":
                rule["status"] = "validated"
            elif status == "canary" and rule["status"] not in {"active", "canary"}:
                rule["status"] = "canary"
            rule["versions"].append(stored)
            self._write("rules.json", "rules", rules)
            return dict(rule)

    def version_of(self, rule_id: str, version: int | None = None) -> dict[str, Any]:
        rule = self.get_rule(rule_id)
        number = rule["active_version"] if version is None else version
        for item in rule["versions"]:
            if item["version"] == number:
                return item
        raise KeyError(f"找不到规则版本: {rule_id}@{number}")

    def lookup(
        self,
        *,
        standard_field: str,
        source_table: str = "",
        source_type: str = "",
        pipeline_id: str = "",
    ) -> dict[str, Any] | None:
        ranked: list[tuple[int, dict[str, Any]]] = []
        for rule in self.list_rules(standard_field=standard_field):
            if rule.get("status") != "active" or not rule.get("active_version"):
                continue
            rank = _rank(rule, source_table=source_table, source_type=source_type, pipeline_id=pipeline_id)
            if rank is not None:
                ranked.append((rank, rule))
        if not ranked:
            return None
        ranked.sort(key=lambda item: item[0])
        return ranked[0][1]

    def activate(self, rule_id: str, version: int) -> dict[str, Any]:
        return self._switch(rule_id, version, allowed={"validated", "canary", "active"})

    def publish(self, rule_id: str, version: int, *, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self.version_of(rule_id, version)
        if current["status"] != "canary":
            raise RulePolicyError("只有灰度版本可以发布")
        if metrics and float(metrics.get("canary_failure_rate", 0)) > float(metrics.get("active_failure_rate", 0)):
            raise RulePolicyError("灰度指标差于当前生效规则，拒绝发布")
        return self._switch(rule_id, version, allowed={"canary"})

    def rollback(self, rule_id: str, version: int) -> dict[str, Any]:
        return self._switch(rule_id, version, allowed={"deprecated", "validated", "canary", "active"})

    def save_pipeline(self, pipeline: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            pipelines = self._read("pipelines.json", "pipelines")
            stored = dict(pipeline)
            stored["pipeline_id"] = stored.get("pipeline_id") or _next_id(pipelines, "pipeline_id", "pipeline")
            replaced = False
            for index, item in enumerate(pipelines):
                if item["pipeline_id"] == stored["pipeline_id"] and item.get("version") == stored.get("version"):
                    pipelines[index] = stored
                    replaced = True
            if not replaced:
                pipelines.append(stored)
            self._write("pipelines.json", "pipelines", pipelines)
            return stored

    def delete_pipeline(self, pipeline_id: str) -> None:
        if not str(pipeline_id).strip() or any(char in pipeline_id for char in "/\\"):
            raise KeyError(f"找不到 Pipeline: {pipeline_id}")
        with self._lock:
            pipelines = self._read("pipelines.json", "pipelines")
            kept = [item for item in pipelines if item.get("pipeline_id") != pipeline_id]
            if len(kept) == len(pipelines):
                raise KeyError(f"找不到 Pipeline: {pipeline_id}")
            self._write("pipelines.json", "pipelines", kept)

    def get_pipeline(self, pipeline_id: str, version: str | None = None) -> dict[str, Any]:
        matches = [item for item in self._read("pipelines.json", "pipelines") if item["pipeline_id"] == pipeline_id]
        if version is not None:
            matches = [item for item in matches if item.get("version") == version]
        if not matches:
            raise KeyError(f"找不到 Pipeline: {pipeline_id}")
        return dict(matches[-1])

    def add_samples(self, samples: list[dict[str, Any]]) -> None:
        with self._lock:
            current = self._read("samples.json", "samples")
            current.extend(samples)
            self._write("samples.json", "samples", current)

    def list_samples(self, **filters: Any) -> list[dict[str, Any]]:
        return [dict(item) for item in self._read("samples.json", "samples") if _match(item, filters)]

    def add_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self._lock:
            current = self._read("events.json", "events")
            stored = []
            for event in events:
                item = dict(event)
                item["event_id"] = item.get("event_id") or _next_id(current, "event_id", "event")
                item.setdefault("resolution", "")
                current.append(item)
                stored.append(item)
            self._write("events.json", "events", current)
            return stored

    def list_events(self, **filters: Any) -> list[dict[str, Any]]:
        return [dict(item) for item in self._read("events.json", "events") if _match(item, filters)]

    def resolve_event(self, event_id: str, resolution: str) -> None:
        with self._lock:
            events = self._read("events.json", "events")
            _find(events, "event_id", event_id)["resolution"] = resolution
            self._write("events.json", "events", events)

    def _switch(self, rule_id: str, version: int, *, allowed: set[str]) -> dict[str, Any]:
        with self._lock:
            rules = self._read("rules.json", "rules")
            rule = _find(rules, "rule_id", rule_id)
            target = next((item for item in rule["versions"] if item["version"] == version), None)
            if target is None:
                raise KeyError(f"找不到规则版本: {rule_id}@{version}")
            if target["status"] not in allowed:
                raise RulePolicyError(f"版本状态 {target['status']} 不能切换为生效")
            assert_can_activate(target)
            _deprecate_active(rule)
            target["status"] = "active"
            rule["active_version"] = version
            rule["status"] = "active"
            self._write("rules.json", "rules", rules)
            return dict(rule)

    def _read(self, name: str, key: str) -> list[dict[str, Any]]:
        path = self.root / name
        if not path.is_file():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get(key, [])
        if not isinstance(items, list):
            return []
        return items

    def _write(self, name: str, key: str, items: list[dict[str, Any]]) -> None:
        path = self.root / name
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({key: items}, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def _match(item: dict[str, Any], filters: dict[str, Any]) -> bool:
    return all(item.get(key) == value for key, value in filters.items())


def _find(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any]:
    for item in items:
        if item.get(key) == value:
            return item
    raise KeyError(f"找不到 {key}: {value}")


def _next_id(items: list[dict[str, Any]], key: str, prefix: str) -> str:
    numbers = []
    for item in items:
        text = str(item.get(key) or "")
        if text.startswith(prefix + "_"):
            try:
                numbers.append(int(text.split("_")[-1]))
            except ValueError:
                continue
    return f"{prefix}_{max(numbers, default=0) + 1:03d}"


def _deprecate_active(rule: dict[str, Any]) -> None:
    for item in rule["versions"]:
        if item["status"] == "active":
            item["status"] = "deprecated"


def _match_issue(issues: list[dict[str, Any]], issue: dict[str, Any]) -> dict[str, Any] | None:
    for item in issues:
        if (
            item.get("standard_field") == issue.get("standard_field")
            and item.get("source_field") == issue.get("source_field")
            and item.get("issue_type") == issue.get("issue_type")
            and item.get("source_table") == issue.get("source_table")
        ):
            return item
    return None


def _rank(rule: dict[str, Any], *, source_table: str, source_type: str, pipeline_id: str) -> int | None:
    if pipeline_id and rule.get("pipeline_id") == pipeline_id and rule.get("source_table") == source_table:
        return 0
    if source_table and rule.get("source_table") == source_table and not rule.get("pipeline_id"):
        return 1
    if source_type and rule.get("source_type") == source_type and not rule.get("source_table") and not rule.get("pipeline_id"):
        return 2
    if not rule.get("source_table") and not rule.get("source_type") and not rule.get("pipeline_id"):
        return 3
    return None
