"""质检结果按类型分开存放，不覆盖输入数据。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from quality.timing import zone


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"文件不存在: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"文件不是 JSON 对象: {source}")
    return payload


def save_report(root: str | Path, report: dict[str, Any]) -> Path:
    return write_json(Path(root) / "reports" / f"{_safe(report['report_id'])}.json", report)


def save_metrics(root: str | Path, report_id: str, inspection: dict[str, Any]) -> Path:
    source_id = _safe(str(inspection.get("source_id") or "source"))
    return write_json(Path(root) / "metrics" / source_id / f"{_safe(report_id)}.json", inspection)


def save_issue(root: str | Path, issue: dict[str, Any]) -> Path:
    return write_json(Path(root) / "issues" / f"{_safe(issue['issue_id'])}.json", issue)


def save_diagnosis(root: str | Path, diagnosis: dict[str, Any]) -> Path:
    return write_json(Path(root) / "diagnoses" / f"{_safe(diagnosis['diagnosis_id'])}.json", diagnosis)


def save_task(root: str | Path, task: dict[str, Any]) -> Path:
    return write_json(Path(root) / "tasks" / f"{_safe(task['task_id'])}.json", task)


def baseline_path(root: str | Path, source_id: str, category: str) -> Path:
    return Path(root) / "baselines" / f"{_safe(source_id)}__{_safe(category)}.json"


def load_baseline(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    source = Path(path)
    if not source.is_file():
        return None
    payload = json.loads(source.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def save_baseline(path: str | Path, inspection: dict[str, Any]) -> Path:
    payload = {
        "source_id": inspection.get("source_id"),
        "category": inspection.get("category"),
        "metrics": inspection.get("metrics") or {},
        "distributions": inspection.get("distributions") or {},
        "volume": inspection.get("total_count") or 0,
        "updated_at": datetime.now(zone("Asia/Shanghai")).isoformat(),
    }
    return write_json(Path(path), payload)


def _safe(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned or "item"
