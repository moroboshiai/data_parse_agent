"""治理运行记录。同一来源和规范类型复用一条记录。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
STOP_STAGES = {"await_confirm", "review", "done"}


class GovernanceError(ValueError):
    pass


class RunBusyError(GovernanceError):
    """任务正在执行，不能删除运行记录。"""


def make_run_id(source_name: str, category: str) -> str:
    raw = f"{source_name}__{category}"
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in raw)
    return cleaned or "run"


def runs_dir(work_root: Path) -> Path:
    return work_root / "data" / "governance" / "runs"


def run_path(work_root: Path, run_id: str) -> Path:
    return runs_dir(work_root) / f"{run_id}.json"


def load_run(work_root: Path, run_id: str) -> dict[str, Any]:
    path = run_path(work_root, run_id)
    if not path.is_file():
        raise GovernanceError(f"找不到治理任务: {run_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise GovernanceError(f"治理任务格式错误: {run_id}")
    return payload


def save_run(work_root: Path, run: dict[str, Any]) -> Path:
    path = run_path(work_root, str(run["run_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def delete_run(work_root: Path, run_id: str) -> None:
    folder = runs_dir(work_root).resolve()
    target = run_path(work_root, run_id).resolve()
    if target.parent != folder:
        raise GovernanceError(f"非法运行编号: {run_id}")
    if not target.is_file():
        raise GovernanceError(f"找不到治理任务: {run_id}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and payload.get("activity"):
        raise RunBusyError("任务正在执行，结束后再删除")
    target.unlink()


def new_run(
    *,
    run_id: str,
    source_name: str,
    category: str,
    sample_path: str,
    standard_schema_path: str,
    input_path: str,
    knowledge_path: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "source_name": source_name,
        "category": category,
        "stage": "intake",
        "status": "running",
        "sample_path": sample_path,
        "input_path": input_path,
        "standard_schema_path": standard_schema_path,
        "knowledge_path": knowledge_path,
        "candidate_path": "",
        "pipeline_id": "",
        "parsed_path": "",
        "profile_path": "",
        "parse_event_count": 0,
        "parse_events_learned": False,
        "issues": [],
        "issues_diagnosed": False,
        "enrichment_count": 0,
        "enrichment_empty": False,
        "blockers": [],
        "decisions": [],
        "artifacts": [],
        "history": [],
    }


def remember(run: dict[str, Any], stage: str, action: str, detail: str = "") -> None:
    run.setdefault("history", []).append(
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "action": action,
            "detail": detail,
        }
    )


def add_artifact(run: dict[str, Any], kind: str, path: str, **extra: Any) -> None:
    item = {"kind": kind, "path": path}
    item.update(extra)
    run.setdefault("artifacts", []).append(item)
