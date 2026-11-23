"""按任务类型加载 Skill。流程分支仍由 LangGraph 决定。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

TASK_SKILLS = {
    "normalize_source_schema": "source-schema-normalization",
    "map_from_sample": "sample-based-field-mapping",
    "map_from_schema": "schema-based-field-mapping",
    "map_with_sample_assist": "sample-assisted-mapping",
    "analyze_field_quality": "field-quality-analysis",
    "generate_extraction_rule": "extraction-rule-generation",
    "generate_cleaning_rule": "cleaning-rule-generation",
    "describe_schema_registration": "source-schema-registration",
}


class SkillSelectionError(KeyError):
    pass


def select_skill(task_type: str) -> str:
    try:
        return TASK_SKILLS[task_type]
    except KeyError as exc:
        raise SkillSelectionError(f"没有与任务对应的 Skill: {task_type}") from exc


def available_skills(root: Path | None = None) -> list[str]:
    base = root or default_skills_root()
    return sorted(path.name for path in base.iterdir() if (path / "SKILL.md").is_file())


def default_skills_root() -> Path:
    return Path(__file__).resolve().parent / "skills"


class SkillRuntime:
    def __init__(self, llm: Any, skills_root: Path | None = None) -> None:
        self.llm = llm
        self.root = skills_root or default_skills_root()

    def system_prompt(self, skill_name: str) -> str:
        skill_dir = self.root / skill_name
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        schema_path = skill_dir / "schemas" / "output.json"
        schema = schema_path.read_text(encoding="utf-8") if schema_path.is_file() else ""
        parts = [f"SKILL: {skill_name}", text.strip(), "只输出一个 JSON 对象，不要输出额外说明。"]
        if schema:
            parts.append("输出必须符合下面的 JSON Schema：\n" + schema.strip())
        return "\n\n".join(parts)

    def run(
        self,
        task_type: str,
        payload: dict[str, Any],
        model: type[BaseModel],
        normalizer=None,
    ) -> BaseModel:
        skill_name = select_skill(task_type)
        system = self.system_prompt(skill_name)
        user = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        return self.llm.complete_json(system, user, model, payload_normalizer=normalizer)
