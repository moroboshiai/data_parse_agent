"""从标准化字段提取可关联实体。不扫描自由文本，也不调用模型。"""

from __future__ import annotations

import re
from typing import Any

_IPV4 = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
_DOMAIN = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$")


def extract_entities(event: dict[str, Any]) -> dict[str, list[str]]:
    ips: list[str] = []
    for field in ("src_ip", "dst_ip"):
        value = _ipv4(event.get(field))
        if value and value not in ips:
            ips.append(value)
    domains: list[str] = []
    domain = _domain(event.get("domain"))
    if domain:
        domains.append(domain)
    return {"ips": ips, "domains": domains}


def _ipv4(value: Any) -> str:
    text = str(value or "").strip()
    if not _IPV4.match(text):
        return ""
    parts = [int(item) for item in text.split(".")]
    if any(part > 255 for part in parts):
        return ""
    return text


def _domain(value: Any) -> str:
    text = str(value or "").strip().lower().rstrip(".")
    if not text or " " in text or not _DOMAIN.match(text):
        return ""
    return text
