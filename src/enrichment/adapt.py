"""把解析 JSONL 适配成富化事件。补事件编号，并把整数 IPv4 转成点分形式。"""

from __future__ import annotations

import hashlib
from ipaddress import IPv4Address
from typing import Any

_EMPTY = {"", "none", "null", "nan"}
_TIME_FIELDS = ("timestamp", "recv_time", "first_pkt_time", "last_pkt_time")
_FLOW_HINTS = ("src_port", "dst_port", "proto_4", "next_hop_ip", "recv_time", "session_total_bytes")


def adapt_events(rows: list[Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    index = 0
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        index += 1
        event = adapt_event(raw, index=index)
        if event:
            events.append(event)
    return events


def adapt_event(raw: dict[str, Any], *, index: int = 1) -> dict[str, Any] | None:
    src_ip = _ipv4(raw.get("src_ip"))
    dst_ip = _ipv4(raw.get("dst_ip"))
    domain = _text(raw.get("domain"))
    timestamp = _timestamp(raw)
    query_type = _text(raw.get("dns_query_type"))
    response_code = _text(raw.get("response_code")) or _text(raw.get("dns_res_code"))
    if not any((src_ip, dst_ip, domain, timestamp, query_type, response_code)):
        return None
    event_id = _text(raw.get("event_id")) or _event_id(index, src_ip, dst_ip, timestamp, domain, raw)
    event: dict[str, Any] = {
        "event_id": event_id,
        "event_type": _text(raw.get("event_type")) or _event_type(raw, domain),
    }
    shown_time = timestamp or _text(raw.get("time"))
    if shown_time:
        event["timestamp"] = shown_time
    if src_ip:
        event["src_ip"] = src_ip
    if dst_ip:
        event["dst_ip"] = dst_ip
    if domain:
        event["domain"] = domain
    if query_type:
        event["dns_query_type"] = query_type
    if response_code:
        event["response_code"] = response_code
    return event


def _event_type(raw: dict[str, Any], domain: str) -> str:
    if domain or _text(raw.get("dns_query_type")) or _text(raw.get("dns_res_code")):
        return "dns"
    if any(_text(raw.get(field)) for field in _FLOW_HINTS):
        return "flow_log"
    return "parsed"


def _timestamp(raw: dict[str, Any]) -> str:
    for field in _TIME_FIELDS:
        value = _text(raw.get(field))
        if value:
            return value
    return ""


def _event_id(index: int, src_ip: str, dst_ip: str, timestamp: str, domain: str, raw: dict[str, Any]) -> str:
    identity = "|".join(
        (
            src_ip,
            dst_ip,
            timestamp,
            domain,
            _text(raw.get("src_port")),
            _text(raw.get("dst_port")),
            _text(raw.get("proto_4")),
        )
    )
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:8]
    return f"parsed_{index:06d}_{digest}"


def _ipv4(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if text.isdigit():
        number = int(text)
        if 0 <= number <= 0xFFFFFFFF:
            return str(IPv4Address(number))
        return ""
    parts = text.split(".")
    if len(parts) != 4 or any(not part.isdigit() for part in parts):
        return ""
    numbers = [int(part) for part in parts]
    if any(part > 255 for part in numbers):
        return ""
    return ".".join(str(part) for part in numbers)


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in _EMPTY:
        return ""
    return text
