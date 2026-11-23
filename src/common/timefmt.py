"""时间格式归一化。同时接受 Python strftime 与规范表里的 Java 风格格式。"""

from __future__ import annotations

import re
from datetime import datetime

_JAVA_TOKENS = (
    ("yyyy", "%Y"),
    ("yy", "%y"),
    ("SSS", ""),
    ("MM", "%m"),
    ("dd", "%d"),
    ("HH", "%H"),
    ("hh", "%I"),
    ("mm", "%M"),
    ("ss", "%S"),
    ("XXX", "%z"),
    ("XX", "%z"),
)
_ISO_HINT = re.compile(r"(?:T|\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$)")
_TZ_SUFFIX = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$")


def to_strftime(pattern: str) -> str:
    """把 yyyy-MM-dd HH:mm:ss 转成 %Y-%m-%d %H:%M:%S。已是 strftime 的格式原样返回。"""
    text = pattern.strip()
    if not text or "%" in text:
        return text
    text = re.sub(r"'([^']*)'", lambda match: match.group(1), text)
    for token, replacement in _JAVA_TOKENS:
        text = text.replace(token, replacement)
    return re.sub(r"\.(?=%|$)", "", text)


def parse_clock(text: str, formats: list[str]) -> datetime:
    raw = text.strip()
    parsed = _from_iso(raw)
    if parsed is not None:
        return parsed
    seen: list[str] = []
    for item in formats:
        fmt = to_strftime(str(item or ""))
        if fmt and "%" in fmt and fmt not in seen:
            seen.append(fmt)
    candidates = [raw]
    stripped = _TZ_SUFFIX.sub("", raw).strip()
    if stripped and stripped not in candidates:
        candidates.append(stripped)
    for fmt in seen:
        for candidate in candidates:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    raise ValueError(f"无法按输入格式解析时间: {text}")


def format_clock(parsed: datetime, output_format: str) -> str:
    fmt = to_strftime(output_format) or "%Y-%m-%d %H:%M:%S"
    if "%" not in fmt:
        fmt = "%Y-%m-%d %H:%M:%S"
    if parsed.tzinfo is not None and "%z" not in fmt and "%Z" not in fmt:
        parsed = parsed.replace(tzinfo=None)
    return parsed.strftime(fmt)


def _from_iso(text: str) -> datetime | None:
    if not _ISO_HINT.search(text):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
