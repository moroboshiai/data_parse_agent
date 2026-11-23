"""已确认映射的复用库。只有确认后的映射会写进来。"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MappingMemory:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        records = payload.get("records") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            return []
        return [item for item in records if isinstance(item, dict)]

    def lookup(self, schema_id: str, source_field: str) -> list[dict[str, Any]]:
        return [
            dict(item)
            for item in self.load()
            if item.get("standard_schema_id") == schema_id and item.get("source_field") == source_field
        ]

    def replace_source(self, schema_id: str, source_field: str, targets: list[str]) -> None:
        with self._lock:
            records = [
                item
                for item in self.load()
                if not (
                    item.get("standard_schema_id") == schema_id and item.get("source_field") == source_field
                )
            ]
            confirmed_at = datetime.now(timezone.utc).isoformat()
            for target in targets:
                if not target:
                    continue
                records.append(
                    {
                        "standard_schema_id": schema_id,
                        "source_field": source_field,
                        "target_field": target,
                        "confirmed_at": confirmed_at,
                    }
                )
            self._write(records)

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"records": records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
