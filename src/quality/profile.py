"""读取质量画像。画像描述数据源约束，不包含检测逻辑。"""

from __future__ import annotations

import json
from pathlib import Path

from quality.schemas import QualityProfile


def load_profile(path: str | Path) -> QualityProfile:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"质量画像不存在: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("质量画像必须是 JSON 对象")
    return QualityProfile.model_validate(payload)
