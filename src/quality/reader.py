"""按行读取 CSV 或 JSONL。调用方逐行消费，不在这里累积全部记录。"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def iter_rows(path: str | Path) -> Iterator[dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"质检输入不存在: {source}")
    suffix = source.suffix.lower()
    if suffix == ".jsonl":
        yield from _jsonl(source)
        return
    if suffix == ".csv":
        yield from _csv(source)
        return
    if suffix == ".json":
        yield from _json(source)
        return
    raise ValueError(f"不支持的质检输入格式: {suffix or '未知'}")


def _jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding=_detect(path), newline="") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            item = json.loads(text)
            if isinstance(item, dict):
                yield item


def _csv(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding=_detect(path), newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            row = {
                str(key).strip(): value.strip() if isinstance(value, str) else value
                for key, value in raw.items()
                if key
            }
            if any(str(value).strip() for value in row.values()):
                yield row


def _json(path: Path) -> Iterator[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding=_detect(path)))
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        payload = payload["rows"]
    if not isinstance(payload, list):
        raise ValueError("JSON 输入必须是对象数组")
    for item in payload:
        if isinstance(item, dict):
            yield item


def _detect(path: Path) -> str:
    sample = path.read_bytes()[:65536]
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "utf-8"
