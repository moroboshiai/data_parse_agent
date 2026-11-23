"""样本抽样。注册阶段只截取分析用样本，不改原始文件。"""

from __future__ import annotations

from typing import Any


def limit_samples(
    rows: list[dict[str, Any]],
    *,
    max_rows: int,
    max_fields: int,
) -> tuple[list[dict[str, Any]], dict[str, list[Any]], list[str]]:
    notices: list[str] = []
    if not rows:
        return [], {}, notices
    fields = list(rows[0].keys())
    if len(fields) > max_fields:
        notices.append(f"字段超过分析上限，已保留前 {max_fields} 个字段")
        fields = fields[:max_fields]
    limited = [{field: row.get(field) for field in fields} for row in rows]
    if len(limited) > max_rows:
        notices.append(f"样本超过分析上限，已抽样前 {max_rows} 行")
        limited = limited[:max_rows]
    samples = {field: [row.get(field) for row in limited] for field in fields}
    return limited, samples, notices


def representative_values(values: list[Any], limit: int = 5) -> list[Any]:
    picked: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value in (None, ""):
            continue
        marker = str(value)
        if marker in seen:
            continue
        seen.add(marker)
        picked.append(value)
        if len(picked) >= limit:
            break
    return picked
