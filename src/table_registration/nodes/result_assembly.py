"""汇总候选映射规则。这里不再调用模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from data_parsing.handoff import issue_templates_from_mappings
from table_registration.schemas.candidate_rule import CandidateDocument
from table_registration.tools.candidate_store import save_candidate


def result_assembly(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    if state.get("status") == "failed":
        return {}
    qualities = {
        (item["source_field"], item["target_field"]): item for item in state.get("field_quality_results") or []
    }
    extractions = {
        (item["source_field"], item["target_field"]): item for item in state.get("extraction_rules") or []
    }
    cleanings = {
        (item["source_field"], item["target_field"]): item for item in state.get("cleaning_rules") or []
    }
    status = _status(state)
    mappings = []
    for item in state.get("final_mappings") or []:
        key = (item["source_field"], item["target_field"])
        quality = qualities.get(key) or {}
        extraction = extractions.get(key)
        cleaning = cleanings.get(key)
        validation = {
            "ok": _pair_ok(quality, extraction, cleaning),
            "extraction": None if extraction is None else extraction.get("test_result"),
            "cleaning": None if cleaning is None else cleaning.get("test_result"),
        }
        mappings.append(
            {
                "source_field": item["source_field"],
                "target_field": item["target_field"],
                "explanation": item.get("explanation") or "",
                "confidence": item.get("confidence") or "low",
                "evidence": list(item.get("evidence") or []),
                "basis": list(item.get("evidence") or []),
                "quality": quality,
                "extraction_rule": extraction,
                "cleaning_rule": cleaning,
                "validation": validation,
                "status": status,
                "version": deps.rules.rule_version,
            }
        )
    if any(not item["validation"]["ok"] for item in mappings):
        status = "pending_review"
        for item in mappings:
            item["status"] = status
    skipped = _cleaning_skip_notices(mappings)
    document = {
        "candidate_id": uuid4().hex,
        "status": status,
        "source_table": state.get("source_table") or {},
        "standard_schema_id": str((state.get("standard_schema") or {}).get("id") or ""),
        "mapping_mode": state.get("mapping_mode") or "",
        "mappings": mappings,
        "unmapped_fields": [
            {
                "source_field": item["source_field"],
                "reason": item.get("reason") or "",
                "evidence": list(item.get("evidence") or []),
            }
            for item in state.get("unmapped_fields") or []
        ],
        "errors": list(state.get("errors") or []),
        "notices": [*list(state.get("notices") or []), *skipped],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    document["issue_templates"] = issue_templates_from_mappings(
        mappings,
        state.get("source_samples") or {},
        source_table=str((state.get("source_table") or {}).get("name") or ""),
        source_type="",
        standard_schema_id=document["standard_schema_id"],
    )
    checked = CandidateDocument.model_validate(document).model_dump()
    path = save_candidate(deps.candidate_dir, checked)
    return {
        "candidate_rules": checked["mappings"],
        "candidate_document": checked,
        "candidate_path": str(path),
        "notices": skipped,
        "status": status,
    }


def _cleaning_skip_notices(mappings: list[dict[str, Any]]) -> list[str]:
    notices = []
    for item in mappings:
        reason = str((item.get("quality") or {}).get("cleaning_skipped_reason") or "").strip()
        if reason:
            notices.append(f"{item.get('source_field')}：{reason}")
    return notices


def _status(state: dict[str, Any]) -> str:
    if state.get("errors") or state.get("validation_results"):
        return "pending_review"
    return "pending_confirm"


def _pair_ok(quality: dict[str, Any], extraction: dict[str, Any] | None, cleaning: dict[str, Any] | None) -> bool:
    if not quality:
        return False
    if quality.get("needs_extraction"):
        if not extraction or not (extraction.get("test_result") or {}).get("passed"):
            return False
    elif extraction:
        return False
    if quality.get("needs_cleaning"):
        if not cleaning or not (cleaning.get("test_result") or {}).get("passed"):
            return False
    elif cleaning:
        return False
    return True
