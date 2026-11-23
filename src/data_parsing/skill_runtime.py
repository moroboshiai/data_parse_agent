"""按名称加载解析 Skill。是否采纳结果由程序决定。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from table_registration.skill_runtime import SkillRuntime


class ParsingSkills:
    def __init__(self, llm: Any) -> None:
        root = Path(__file__).resolve().parent / "skills"
        self.runtime = SkillRuntime(llm, skills_root=root)
        self.llm = llm

    def run(self, skill_name: str, payload: dict[str, Any], model: type[BaseModel]) -> BaseModel:
        system = self.runtime.system_prompt(skill_name)
        user = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        return self.llm.complete_json(system, user, model, payload_normalizer=_drop_activation)


def _drop_activation(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("status", "active", "active_version", "test_status"):
        payload.pop(key, None)
    return payload
