"""样本是否存在、可读、有有效行和字段。"""

from __future__ import annotations

from typing import Any

from table_registration.rules.engine import check_sample_required
from table_registration.tools.file_parser import SampleReadError, parse_table
from table_registration.tools.sample import limit_samples


def validate_sample(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    read_error = None
    rows = list(state.get("sample_rows") or [])
    path = state.get("sample_path") or ""
    if not rows and path:
        try:
            rows = parse_table(path)
        except SampleReadError as exc:
            read_error = str(exc)
    problems = check_sample_required(rows, read_error)
    if problems:
        return {"status": "failed", "errors": problems}
    limited, samples, notices = limit_samples(
        rows,
        max_rows=deps.rules.max_sample_rows,
        max_fields=deps.rules.max_fields,
    )
    source_path = path
    return {
        "sample_rows": limited,
        "source_samples": samples,
        "source_table": {
            "name": state.get("source_name") or "source_table",
            "source_type": "file",
            "sample_path": source_path,
            "field_count": len(samples),
        },
        "notices": notices,
        "status": "running",
    }
