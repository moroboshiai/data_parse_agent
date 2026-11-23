"""按数据类型加载规则。同名规则里，数据源专属配置覆盖类型通用配置。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def default_rules_root() -> Path:
    return Path(__file__).resolve().parent


def load_rules(category: str, source_id: str, root: str | Path | None = None) -> list[dict[str, Any]]:
    base = Path(root) if root is not None else default_rules_root()
    folder = base / category
    found: list[dict[str, Any]] = []
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload = payload.get("rules") or []
            if isinstance(payload, list):
                found.extend(item for item in payload if isinstance(item, dict))
    return select_rules(found, category, source_id)


def select_rules(rules: list[dict[str, Any]], category: str, source_id: str) -> list[dict[str, Any]]:
    chosen: dict[str, dict[str, Any]] = {}
    rank: dict[str, int] = {}
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        rule_category = str(rule.get("category") or "")
        if rule_category not in {category, "*", ""}:
            continue
        scope = rule.get("scope") or {}
        scoped = str(scope.get("source_id") or "")
        if scoped not in {"", source_id}:
            continue
        specificity = 1 if scoped and scoped == source_id else 0
        rule_id = str(rule.get("rule_id") or "")
        if not rule_id:
            continue
        if specificity >= rank.get(rule_id, -1):
            chosen[rule_id] = rule
            rank[rule_id] = specificity
    return list(chosen.values())
