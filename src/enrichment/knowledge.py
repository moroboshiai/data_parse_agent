"""只读本地资产、情报和历史知识。查询结果带稳定证据编号。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from enrichment.schemas import Evidence, Subject


class KnowledgeBase:
    def __init__(self, root: str | Path) -> None:
        base = Path(root)
        self.assets = _records(base / "assets.json", "assets")
        self.indicators = _records(base / "intel.json", "indicators")
        self.history = _records(base / "history.json", "records")

    @property
    def is_empty(self) -> bool:
        return not self.assets and not self.indicators and not self.history

    def evidence_for_ip(self, ip: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for asset in self.assets:
            if str(asset.get("ip") or "") == ip:
                found.append(_evidence("asset", "ip", ip, asset, "asset_database", "ev_asset_"))
        found.extend(self._intel("ip", ip))
        found.extend(self._history("ip", ip))
        return found

    def evidence_for_domain(self, domain: str) -> list[dict[str, Any]]:
        return [*self._intel("domain", domain), *self._history("domain", domain)]

    def lookup_asset(self, ip: str) -> list[dict[str, Any]]:
        return [item for item in self.evidence_for_ip(ip) if item["evidence_type"] == "asset"]

    def lookup_intel(self, kind: Literal["ip", "domain"], value: str) -> list[dict[str, Any]]:
        source = self.evidence_for_ip(value) if kind == "ip" else self.evidence_for_domain(value)
        return [item for item in source if item["evidence_type"] == "threat_intel"]

    def lookup_history(self, kind: Literal["ip", "domain"], value: str) -> list[dict[str, Any]]:
        source = self.evidence_for_ip(value) if kind == "ip" else self.evidence_for_domain(value)
        return [item for item in source if item["evidence_type"] == "history"]

    def _intel(self, kind: Literal["ip", "domain"], value: str) -> list[dict[str, Any]]:
        found = []
        for item in self.indicators:
            if str(item.get("indicator_type") or "") == kind and str(item.get("value") or "").lower() == value.lower():
                found.append(_evidence("threat_intel", kind, value, item, str(item.get("source") or "threat_intel"), "ev_intel_"))
        return found

    def _history(self, kind: Literal["ip", "domain"], value: str) -> list[dict[str, Any]]:
        found = []
        for item in self.history:
            if str(item.get("indicator_type") or "") == kind and str(item.get("value") or "").lower() == value.lower():
                found.append(_evidence("history", kind, value, item, "history_store", "ev_history_"))
        return found


def _records(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _evidence(
    kind: Literal["asset", "threat_intel", "history"],
    subject_type: Literal["ip", "domain"],
    value: str,
    result: dict[str, Any],
    source: str,
    prefix: str,
) -> dict[str, Any]:
    slug = value.replace("/", "_")
    evidence = Evidence(
        evidence_id=f"{prefix}{subject_type}_{slug}",
        evidence_type=kind,
        subject=Subject(type=subject_type, value=value),
        result={key: item for key, item in result.items() if key != "source"},
        source=source,
        retrieved_at=str(result.get("last_seen") or result.get("first_seen") or ""),
    )
    return evidence.model_dump()
