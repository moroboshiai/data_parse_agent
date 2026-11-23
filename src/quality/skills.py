"""按名称调用质检 Skill。Skill 不执行检测。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from table_registration.skill_runtime import SkillRuntime


class QualitySkills:
    def __init__(self, llm: Any) -> None:
        root = Path(__file__).resolve().parent / "skills"
        self.runtime = SkillRuntime(llm, skills_root=root)
        self.llm = llm

    def run(self, skill_name: str, payload: dict[str, Any], model: type[BaseModel]) -> BaseModel:
        system = self.runtime.system_prompt(skill_name)
        user = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        return self.llm.complete_json(system, user, model)
