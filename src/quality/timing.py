"""时间解析。格式列表来自画像或规则，不在这里假定某种日志的时间字段。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo


def zone(name: str) -> tzinfo:
    selected = name or "Asia/Shanghai"
    try:
        return ZoneInfo(selected)
    except Exception:
        if selected in {"Asia/Shanghai", "Asia/Chongqing", "PRC"}:
            return timezone(timedelta(hours=8), selected)
        return timezone.utc


def parse_time(value: Any, formats: list[str] | None, timezone_name: str) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    selected = formats or ["iso8601"]
    current = zone(timezone_name)
    if "iso8601" in selected:
        parsed = _from_iso(text, current)
        if parsed is not None:
            return parsed
    if "YYYY-MM-DD HH:MM:SS" in selected:
        parsed = _strptime(text, "%Y-%m-%d %H:%M:%S", current)
        if parsed is not None:
            return parsed
    if "YYYY-MM-DD" in selected:
        parsed = _strptime(text, "%Y-%m-%d", current)
        if parsed is not None:
            return parsed
    if "YYYYMMDDHH" in selected and re.fullmatch(r"\d{10}", text):
        parsed = _strptime(text, "%Y%m%d%H", current)
        if parsed is not None:
            return parsed
    if "YYYY/M/D" in selected:
        matched = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", text)
        if matched:
            year, month, day = (int(part) for part in matched.groups())
            try:
                return datetime(year, month, day, tzinfo=current)
            except ValueError:
                return None
    return None


def parse_bound(value: str | None, timezone_name: str, *, is_end: bool = False) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        parsed = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=zone(timezone_name))
        return parsed + timedelta(days=1) if is_end else parsed
    return parse_time(text, ["iso8601", "YYYY-MM-DD HH:MM:SS", "YYYY-MM-DD"], timezone_name)


def in_window(moment: datetime, start: datetime | None, end: datetime | None) -> bool:
    if start is not None and moment < start:
        return False
    if end is not None and moment >= end:
        return False
    return True


def partition_matches(moment: datetime, text: str, timezone_name: str) -> bool | None:
    """识别分区格式后比较。无法识别时返回 None，避免把未知口径当成错误。"""

    raw = str(text).strip()
    if not raw:
        return None
    local = moment.astimezone(zone(timezone_name))
    if re.fullmatch(r"\d{10}", raw):
        return local.strftime("%Y%m%d%H") == raw
    matched = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", raw)
    if matched:
        year, month, day = (int(part) for part in matched.groups())
        return (local.year, local.month, local.day) == (year, month, day)
    return None


def _from_iso(text: str, current: tzinfo) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=current)
    return parsed


def _strptime(text: str, pattern: str, current: tzinfo) -> datetime | None:
    try:
        return datetime.strptime(text, pattern).replace(tzinfo=current)
    except ValueError:
        return None
