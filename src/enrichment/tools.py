"""调查工具白名单。模型可以提议查询，程序决定是否执行。"""

from __future__ import annotations

import json
from typing import Any

from enrichment.knowledge import KnowledgeBase

ALLOWED_TOOLS = ("asset_lookup", "history_search", "threat_intel_lookup")
ALLOWED_RANGES = {"1d", "7d", "30d"}
TOOL_CATALOG = [
    {"name": "asset_lookup", "arguments": ["ip"], "description": "查询 IP 对应的资产"},
    {"name": "threat_intel_lookup", "arguments": ["ip 或 domain"], "description": "查询 IP 或域名的威胁情报"},
    {"name": "history_search", "arguments": ["ip 或 domain", "time_range"], "description": "查询 IP 或域名的历史出现记录"},
]


def validate_action(
    action: dict[str, Any],
    *,
    entities: dict[str, list[str]],
    evidence: list[dict[str, Any]],
    executed: list[dict[str, Any]],
) -> tuple[bool, str, dict[str, str]]:
    tool = str(action.get("tool") or "")
    arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
    if tool not in ALLOWED_TOOLS:
        return False, "工具不在白名单中", {}
    if tool == "asset_lookup":
        ip = str(arguments.get("ip") or "").strip()
        if not ip:
            return False, "缺少 ip", {}
        if not _known("ip", ip, entities, evidence):
            return False, "查询对象不在当前事件或已有证据中", {}
        normalized = {"ip": ip}
    else:
        ip = str(arguments.get("ip") or "").strip()
        domain = str(arguments.get("domain") or "").strip().lower()
        if bool(ip) == bool(domain):
            return False, "需要且只能指定 ip 或 domain", {}
        if ip and not _known("ip", ip, entities, evidence):
            return False, "查询对象不在当前事件或已有证据中", {}
        if domain and not _known("domain", domain, entities, evidence):
            return False, "查询对象不在当前事件或已有证据中", {}
        normalized = {"ip": ip} if ip else {"domain": domain}
        if tool == "history_search":
            time_range = str(arguments.get("time_range") or "").strip()
            if time_range and time_range not in ALLOWED_RANGES:
                return False, "查询范围不在允许范围内", {}
            if time_range:
                normalized["time_range"] = time_range
    if _key(tool, normalized) in {_key(item["tool"], item["arguments"]) for item in executed}:
        return False, "重复查询", {}
    return True, "", normalized


def execute_action(knowledge: KnowledgeBase, tool: str, arguments: dict[str, str]) -> list[dict[str, Any]]:
    if tool == "asset_lookup":
        return knowledge.lookup_asset(arguments["ip"])
    kind = "ip" if arguments.get("ip") else "domain"
    value = arguments.get("ip") or arguments.get("domain") or ""
    if tool == "threat_intel_lookup":
        return knowledge.lookup_intel(kind, value)
    return knowledge.lookup_history(kind, value)


def _known(kind: str, value: str, entities: dict[str, list[str]], evidence: list[dict[str, Any]]) -> bool:
    pool = entities["ips"] if kind == "ip" else entities["domains"]
    if value in pool:
        return True
    for item in evidence:
        subject = item.get("subject") or {}
        if subject.get("type") == kind and str(subject.get("value") or "") == value:
            return True
    return False


def _key(tool: str, arguments: dict[str, str]) -> str:
    return tool + ":" + json.dumps(arguments, ensure_ascii=False, sort_keys=True)
