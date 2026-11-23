"""主控只把复核阶段的路由交给模型。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from table_registration.skill_runtime import SkillRuntime


class ReviewChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action: str = ""
    reason: str = ""


class GovernanceSkills:
    def __init__(self, llm: Any) -> None:
        root = Path(__file__).resolve().parent / "skills"
        self.runtime = SkillRuntime(llm, skills_root=root)
        self.llm = llm

    def choose_review(self, payload: dict[str, Any]) -> ReviewChoice:
        system = self.runtime.system_prompt("governance-routing")
        user = json.dumps(payload, ensure_ascii=False, indent=2)
        return self.llm.complete_json(system, user, ReviewChoice)
