"""按字段并发做质量分析。未映射字段不会进入这里。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from table_registration.llm import LlmError
from table_registration.rules.engine import normalize_quality_decision, skip_unsupported_cleaning
from table_registration.schemas.quality_result import FieldQuality
from table_registration.tools.sample import representative_values


def field_quality(state: dict[str, Any], deps: Any) -> dict[str, Any]:
    if state.get("status") == "failed":
        return {}
    pairs = state.get("final_mappings") or []
    if not pairs:
        return {"field_quality_results": []}
    results = _concurrent(pairs, lambda pair: _analyze(state, deps, pair), deps.rules.batch_size)
    qualities = []
    errors = []
    for quality, error in results:
        if error:
            errors.append(error)
            continue
        qualities.append(quality)
    return {"field_quality_results": qualities, "errors": errors}


def _analyze(state: dict[str, Any], deps: Any, pair: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    standard = {field["name"]: field for field in state["standard_schema"]["fields"]}
    target = standard.get(pair["target_field"], {})
    payload = {
        "source_field": pair["source_field"],
        "target_field": pair["target_field"],
        "target_type": target.get("type") or "unknown",
        "target_description": target.get("description") or "",
        "samples": representative_values(state.get("source_samples", {}).get(pair["source_field"], [])),
    }
    try:
        result = deps.skills.run("analyze_field_quality", payload, FieldQuality, _coerce_quality)
    except LlmError as exc:
        return None, f"{pair['source_field']} 质量分析失败: {exc}"
    data = normalize_quality_decision(result.model_dump())
    data["source_field"] = pair["source_field"]
    data["target_field"] = pair["target_field"]
    samples = representative_values(state.get("source_samples", {}).get(pair["source_field"], []))
    return skip_unsupported_cleaning(data, samples, str(target.get("type") or "")), None


def _coerce_quality(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("direct_mapping", "needs_extraction", "needs_cleaning"):
        payload[key] = _as_bool(payload.get(key))
    payload["issues"] = [str(item) for item in payload.get("issues") or []]
    payload.setdefault("analysis", "")
    payload.setdefault("extraction_goal", "")
    payload.setdefault("cleaning_goal", "")
    return payload


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是", "需要"}
    return bool(value)


def _concurrent(items, fn, workers: int):
    if not items:
        return []
    if len(items) == 1:
        return [fn(items[0])]
    pool_size = max(1, min(workers, len(items)))
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        futures = [pool.submit(fn, item) for item in items]
        return [future.result() for future in futures]
