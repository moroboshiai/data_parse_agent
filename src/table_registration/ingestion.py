"""接入阶段只执行已确认规则，不参与表注册。"""

from __future__ import annotations

from typing import Any

from table_registration.tools.cleaning_executor import CleaningError, apply_cleaning
from table_registration.tools.regex_executor import apply_extraction


class IngestionError(PermissionError):
    pass


def apply_confirmed_rules(candidate: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    if candidate.get("status") != "confirmed":
        raise IngestionError("仅已确认规则可在接入阶段执行")
    outputs: list[dict[str, Any]] = []
    errors: list[str] = []
    for row in rows:
        converted: dict[str, Any] = {}
        for rule in candidate.get("mappings") or []:
            value = row.get(rule["source_field"])
            extraction = rule.get("extraction_rule")
            if extraction:
                value, error = apply_extraction(extraction, value)
                if error:
                    errors.append(f"{rule['source_field']}: {error}")
            cleaning = rule.get("cleaning_rule")
            if cleaning and value is not None:
                try:
                    value = apply_cleaning(cleaning, value)
                except CleaningError as exc:
                    errors.append(f"{rule['source_field']}: {exc}")
                    value = None
            converted[rule["target_field"]] = value
        outputs.append(converted)
    return {"rows": outputs, "errors": errors}
