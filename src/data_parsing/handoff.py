"""把表注册结果拆成问题模板和初始规则。模板描述问题，规则描述解法。"""

from __future__ import annotations

from typing import Any

from data_parsing.operators.registry import execute
from data_parsing.repository import RuleRepository

_CLEANING_TYPES = {
    "normalize_datetime": "normalization",
    "normalize_time": "normalization",
    "convert_type": "type_conversion",
    "trim": "redundancy",
    "collapse_whitespace": "redundancy",
    "lower": "canonicalization",
    "upper": "canonicalization",
    "replace": "canonicalization",
}


def issue_templates_from_mappings(
    mappings: list[dict[str, Any]],
    samples: dict[str, list[Any]],
    *,
    source_table: str,
    source_type: str,
    standard_schema_id: str,
) -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    for mapping in mappings:
        quality = mapping.get("quality") or {}
        needs_extraction = bool(quality.get("needs_extraction"))
        needs_cleaning = bool(quality.get("needs_cleaning"))
        if quality.get("direct_mapping") or not (needs_extraction or needs_cleaning):
            continue
        values = [value for value in samples.get(mapping["source_field"], []) if value not in (None, "")][:5]
        if needs_extraction:
            templates.append(
                _template(
                    mapping,
                    issue_type=_extraction_type(quality),
                    description=quality.get("analysis") or quality.get("extraction_goal") or "需要提取字段内容",
                    samples=values,
                    rule=mapping.get("extraction_rule"),
                    passed=_passed(mapping, "extraction"),
                    source_table=source_table,
                    source_type=source_type,
                    standard_schema_id=standard_schema_id,
                )
            )
        if needs_cleaning:
            rule = mapping.get("cleaning_rule") or {}
            templates.append(
                _template(
                    mapping,
                    issue_type=_CLEANING_TYPES.get(str(rule.get("operator") or ""), "normalization"),
                    description=quality.get("cleaning_goal") or quality.get("analysis") or "需要清洗字段格式",
                    samples=values,
                    rule=rule,
                    passed=_passed(mapping, "cleaning"),
                    source_table=source_table,
                    source_type=source_type,
                    standard_schema_id=standard_schema_id,
                )
            )
    return templates[: _limit(mappings)]


def seed_repository(
    repository: RuleRepository,
    candidate: dict[str, Any],
    samples: dict[str, list[Any]],
    *,
    source_type: str,
) -> list[dict[str, Any]]:
    if candidate.get("status") != "confirmed":
        raise ValueError("只有已确认的注册结果可以导入解析规则仓库")
    source_table = str((candidate.get("source_table") or {}).get("name") or "")
    templates = candidate.get("issue_templates") or issue_templates_from_mappings(
        candidate.get("mappings") or [],
        samples,
        source_table=source_table,
        source_type=source_type,
        standard_schema_id=str(candidate.get("standard_schema_id") or ""),
    )
    stored = []
    for template in templates:
        template["source_type"] = source_type or template.get("source_type") or ""
        template["source_table"] = source_table
        issue = repository.save_issue(template)
        if template.get("initial_rule_status") == "candidate" and template.get("operator"):
            rule = _seed_rule(repository, template, samples)
            issue["rule_id"] = rule["rule_id"]
            repository.save_issue(issue)
        stored.append(issue)
    return stored


def _template(
    mapping: dict[str, Any],
    *,
    issue_type: str,
    description: str,
    samples: list[Any],
    rule: dict[str, Any] | None,
    passed: bool,
    source_table: str,
    source_type: str,
    standard_schema_id: str,
) -> dict[str, Any]:
    operator, params = _operator_from_rule(rule or {}, issue_type)
    return {
        "standard_field": mapping["target_field"],
        "source_field": mapping["source_field"],
        "source_table": source_table,
        "source_type": source_type,
        "standard_schema_id": standard_schema_id,
        "issue_type": issue_type,
        "issue_description": description,
        "sample_values": samples,
        "suggested_strategy": operator,
        "operator": operator if passed else "",
        "params": params if passed else {},
        "initial_rule_status": "candidate" if passed and operator else "discovered",
        "discovered_from": "table_registration",
        "status": "discovered",
    }


def _operator_from_rule(rule: dict[str, Any], issue_type: str) -> tuple[str, dict[str, Any]]:
    if rule.get("pattern"):
        return "extract_regex", {"pattern": rule["pattern"], "group": int(rule.get("group") or 1)}
    operator = str(rule.get("operator") or "")
    if operator == "normalize_datetime":
        operator = "normalize_time"
    params = {
        key: rule.get(key)
        for key in ("input_formats", "output_format", "expression", "old", "new", "target")
        if rule.get(key) not in (None, "", [])
    }
    if operator == "normalize_time" and rule.get("expression") and "output_format" not in params:
        params["output_format"] = rule["expression"]
    if not operator:
        operator = "extract_ip" if issue_type in {"extraction", "composite_split"} else "trim"
        if not rule:
            return "", {}
    return operator, params


def _seed_rule(repository: RuleRepository, template: dict[str, Any], samples: dict[str, list[Any]]) -> dict[str, Any]:
    rule = repository.create_rule(
        {
            "standard_field": template["standard_field"],
            "source_type": template.get("source_type") or "",
            "source_table": template.get("source_table") or "",
            "source_field": template.get("source_field") or "",
            "rule_type": template["issue_type"],
        }
    )
    report = _preview(template["operator"], template.get("params") or {}, samples.get(template["source_field"], []))
    repository.append_version(
        rule["rule_id"],
        {
            "operator": template["operator"],
            "params": template.get("params") or {},
            "test_status": "passed" if report["passed"] else "failed",
            "status": "validated" if report["passed"] else "candidate",
            "created_from": "table_registration",
            "test_report": report,
        },
    )
    if report["passed"]:
        repository.add_samples(_sample_records(rule["rule_id"], template, report))
    return repository.get_rule(rule["rule_id"])


def _preview(operator: str, params: dict[str, Any], values: list[Any]) -> dict[str, Any]:
    previews = []
    errors = []
    for value in values:
        if value in (None, ""):
            continue
        result = execute(operator, value, params)
        previews.append({"input": value, "output": result.value, "ok": result.ok})
        if not result.ok:
            errors.append(result.error)
    return {"passed": bool(previews) and not errors, "errors": errors, "previews": previews[:8]}


def _sample_records(rule_id: str, template: dict[str, Any], report: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for item in report["previews"]:
        if not item["ok"]:
            continue
        records.append(
            {
                "rule_id": rule_id,
                "standard_field": template["standard_field"],
                "kind": "original",
                "value": item["input"],
                "expected": item["output"],
                "expect_failure": False,
            }
        )
    if records and template["issue_type"] in {"extraction", "composite_split"}:
        records.append(
            {
                "rule_id": rule_id,
                "standard_field": template["standard_field"],
                "kind": "counterexample",
                "value": "不是有效值",
                "expected": None,
                "expect_failure": True,
            }
        )
    return records


def _extraction_type(quality: dict[str, Any]) -> str:
    text = f"{quality.get('extraction_goal') or ''}{quality.get('analysis') or ''}"
    if "拆分" in text:
        return "composite_split"
    return "extraction"


def _passed(mapping: dict[str, Any], kind: str) -> bool:
    result = (mapping.get("validation") or {}).get(kind) or {}
    return bool(result.get("passed"))


def _limit(mappings: list[dict[str, Any]]) -> int:
    return max(len(mappings) * 2, 1)
