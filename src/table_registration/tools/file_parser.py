"""读取 CSV、JSON 和 Excel 样本。"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


class SampleReadError(ValueError):
    pass


def read_text_auto(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SampleReadError("样本文件无法读取")


def parse_table(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        raise SampleReadError("样本文件不存在或无法读取")
    suffix = source.suffix.lower()
    try:
        if suffix == ".csv":
            return _parse_csv(source)
        if suffix == ".json":
            return _parse_json(source)
        if suffix in {".xlsx", ".xlsm"}:
            return _parse_xlsx(source)
    except SampleReadError:
        raise
    except OSError as exc:
        raise SampleReadError("样本文件无法读取") from exc
    except (json.JSONDecodeError, csv.Error, ValueError) as exc:
        raise SampleReadError(f"样本文件无法解析: {exc}") from exc
    raise SampleReadError(f"不支持的样本格式: {suffix or '未知'}")


def _parse_csv(path: Path) -> list[dict[str, Any]]:
    text = read_text_auto(path)
    reader = csv.reader(text.splitlines())
    try:
        header = next(reader)
    except StopIteration as exc:
        raise SampleReadError("样本没有有效字段") from exc
    header = [str(cell).strip() for cell in header]
    if any(not name for name in header):
        raise SampleReadError("字段名称不能为空")
    if len(header) != len(set(header)):
        raise SampleReadError("字段标识不能重复")
    rows: list[dict[str, Any]] = []
    for raw in reader:
        if not any(str(cell).strip() for cell in raw):
            continue
        padded = raw + [""] * (len(header) - len(raw))
        rows.append({name: padded[index].strip() for index, name in enumerate(header)})
    return rows


def _parse_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(read_text_auto(path))
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        payload = payload["rows"]
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise SampleReadError("JSON 样本必须是对象数组")
    return _ordered_rows(payload)


def _parse_xlsx(path: Path) -> list[dict[str, Any]]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        iterator = sheet.iter_rows(values_only=True)
        header_row = next(iterator, None)
        if not header_row:
            raise SampleReadError("样本没有有效字段")
        header = ["" if cell is None else str(cell).strip() for cell in header_row]
        while header and not header[-1]:
            header.pop()
        if any(not name for name in header):
            raise SampleReadError("字段名称不能为空")
        if len(header) != len(set(header)):
            raise SampleReadError("字段标识不能重复")
        rows: list[dict[str, Any]] = []
        for raw in iterator:
            values = list(raw[: len(header)])
            if not any(value not in (None, "") for value in values):
                continue
            rows.append({header[index]: values[index] if index < len(values) else None for index in range(len(header))})
        return rows
    finally:
        workbook.close()


def _ordered_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields: list[str] = []
    for row in rows:
        for key in row:
            name = str(key).strip()
            if name and name not in fields:
                fields.append(name)
    if any(not str(key).strip() for row in rows for key in row):
        raise SampleReadError("字段名称不能为空")
    return [{field: row.get(field) for field in fields} for row in rows]
