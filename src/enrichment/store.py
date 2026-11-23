"""按事件和策略版本覆盖保存富化结果，不改解析后的原始事件。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def save_records(directory: str | Path, records: list[dict[str, Any]], strategy_version: str) -> list[Path]:
    root = Path(directory) / strategy_version
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for record in records:
        path = root / f"{_safe(record['event_id'])}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        written.append(path)
    return written


def save_report(directory: str | Path, report: dict[str, Any]) -> Path:
    root = Path(directory) / "investigations"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{_safe(report['event_id'])}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def count_records(directory: str | Path, strategy_version: str) -> int:
    root = Path(directory) / strategy_version
    if not root.is_dir():
        return 0
    return len(list(root.glob("*.json")))


def _safe(event_id: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in event_id)
    return cleaned or "event"
