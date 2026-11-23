"""固定解析引擎。Pipeline 配置决定顺序，引擎只负责装载和调用算子。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from data_parsing.operators.registry import execute, normalize_ipv4_field
from data_parsing.repository import RuleRepository


def use_canary(pipeline_id: str, row_index: int, ratio: float) -> bool:
    if ratio <= 0:
        return False
    if ratio >= 1:
        return True
    digest = hashlib.sha256(f"{pipeline_id}:{row_index}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100 < int(ratio * 100)


class ParsingEngine:
    def __init__(self, repository: RuleRepository) -> None:
        self.repository = repository

    def parse(self, rows: list[dict[str, Any]], pipeline: dict[str, Any]) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        events: list[dict[str, Any]] = []
        parsed: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            output: dict[str, Any] = {}
            for field in pipeline.get("fields") or []:
                standard_field = field["standard_field"]
                source_field = field["source_field"]
                value = row.get(source_field)
                lane, specs = _specs(self.repository, pipeline, field, index)
                metric = metrics.setdefault(standard_field, _blank_metric())
                metric["total"] += 1
                metric[lane]["total"] += 1
                if value in (None, ""):
                    output[standard_field] = None
                    metric["empty"] += 1
                    continue
                current, error = _run_chain(value, specs)
                if not error:
                    current = normalize_ipv4_field(standard_field, current)
                output[standard_field] = current
                if error:
                    metric["failure"] += 1
                    metric[lane]["failure"] += 1
                    events.append(
                        {
                            "pipeline_id": pipeline["pipeline_id"],
                            "standard_field": standard_field,
                            "source_field": source_field,
                            "issue_type": "extraction_failure" if "提取" in error or "未" in error else "execution_failure",
                            "raw_value": value,
                            "error": error,
                            "operator": specs[-1]["operator"] if specs else "",
                            "lane": lane,
                            "current_rule_id": specs[-1]["rule_id"] if specs else "",
                            "current_rule_version": specs[-1]["version"] if specs else None,
                            "row_index": index,
                        }
                    )
                else:
                    metric["success"] += 1
                    metric[lane]["success"] += 1
            parsed.append(output)
        return {"rows": parsed, "events": events, "metrics": metrics}


def failure_rates(metrics: dict[str, Any]) -> dict[str, float]:
    def rate(lane: str) -> float:
        failure = success = 0
        for item in metrics.values():
            bucket = item.get(lane) or {}
            failure += int(bucket.get("failure") or 0)
            success += int(bucket.get("success") or 0)
        total = failure + success
        return failure / total if total else 0

    return {"canary_failure_rate": rate("canary"), "active_failure_rate": rate("active")}


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    target.write_text(text, encoding="utf-8")
    return target


def _specs(repository: RuleRepository, pipeline: dict[str, Any], field: dict[str, Any], row_index: int):
    ratio = float(field.get("canary_ratio") or 0)
    if field.get("canary_rule_id") and use_canary(pipeline["pipeline_id"], row_index, ratio):
        rule_id = field["canary_rule_id"]
        version = field.get("canary_version")
        return "canary", [_spec(repository, rule_id, version)]
    specs = []
    for rule_id in field.get("rule_ids") or []:
        specs.append(_spec(repository, rule_id, None))
    return "active", [item for item in specs if item]


def _spec(repository: RuleRepository, rule_id: str, version: int | None) -> dict[str, Any] | None:
    try:
        rule = repository.get_rule(rule_id)
        if version is None:
            version = rule.get("active_version")
        if version is None:
            current = next((item for item in rule["versions"] if item["status"] in {"validated", "canary"}), None)
        else:
            current = next((item for item in rule["versions"] if item["version"] == version), None)
    except KeyError:
        return {"rule_id": rule_id, "version": version, "operator": "missing", "params": {}}
    if current is None:
        return {"rule_id": rule_id, "version": version, "operator": "missing", "params": {}}
    return {
        "rule_id": rule_id,
        "version": current["version"],
        "operator": current["operator"],
        "params": current.get("params") or {},
    }


def _run_chain(value: Any, specs: list[dict[str, Any]]) -> tuple[Any, str]:
    if not specs:
        result = execute("passthrough", value, {})
        return result.value, ""
    current = value
    for spec in specs:
        result = execute(spec["operator"], current, spec.get("params") or {})
        if not result.ok:
            return result.value, result.error or "规则执行失败"
        current = result.value
    return current, ""


def _blank_metric() -> dict[str, Any]:
    return {
        "total": 0,
        "success": 0,
        "failure": 0,
        "empty": 0,
        "active": {"total": 0, "success": 0, "failure": 0},
        "canary": {"total": 0, "success": 0, "failure": 0},
    }
