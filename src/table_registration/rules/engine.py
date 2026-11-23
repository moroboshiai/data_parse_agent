"""可执行业务约束。映射和清洗隔离由这里拦截，而不是只写在提示词里。"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from table_registration.config import RuleSettings

FORBIDDEN_MAPPING_KEYS = {
    "extraction",
    "extraction_rule",
    "extract_rule",
    "cleaning",
    "cleaning_rule",
    "clean_rule",
    "transform",
    "transformation",
    "governance",
    "regex",
    "pattern",
    "operator",
    "operations",
}

_LABELS = {
    "high": "high",
    "medium": "medium",
    "low": "low",
    "高": "high",
    "中": "medium",
    "低": "low",
}
_RANK = {"high": 3, "medium": 2, "low": 1, None: 0}
_IPV4 = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")
_DATE = re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}")
_URL = re.compile(r"https?://|[\w.-]+\.[A-Za-z]{2,}")
_NESTED_QUANTIFIER = re.compile(r"\((?:\?:)?[^()]*[+*][^()]*\)[+*{]")


class MappingIsolationError(Exception):
    """映射模型输出了清洗、提取或治理内容。"""


def check_sample_required(rows: list[dict[str, Any]] | None, read_error: str | None = None) -> list[str]:
    if read_error:
        return [read_error]
    if not rows:
        return ["必须上传来源表样本，且至少包含一行有效数据"]
    if any(not str(name).strip() for row in rows for name in row):
        return ["字段名称不能为空"]
    names = list(rows[0].keys())
    if not any(str(name).strip() for name in names):
        return ["样本没有有效字段"]
    if len(names) != len(set(names)):
        return ["字段标识不能重复"]
    if not has_effective_rows(rows):
        return ["样本没有有效数据行"]
    return []


def has_effective_rows(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        if any(value not in (None, "") for value in row.values()):
            return True
    return False


def choose_mapping_mode(source_schema_present: bool) -> str:
    return "schema" if source_schema_present else "sample"


def label_from_score(score: float, settings: RuleSettings) -> str:
    if score >= settings.confidence.high_min:
        return "high"
    if score >= settings.confidence.medium_min:
        return "medium"
    return "low"


def normalize_label(value: Any, settings: RuleSettings) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "low"
    if isinstance(value, (int, float)):
        return label_from_score(float(value), settings)
    text = str(value).strip().lower()
    if text in {"", "none", "null"}:
        return None
    return _LABELS.get(text, _LABELS.get(str(value).strip(), "low"))


def iter_keys(payload: Any):
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield str(key)
            yield from iter_keys(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from iter_keys(item)


def reject_mapping_side_effects(payload: dict[str, Any]) -> dict[str, Any]:
    found = sorted({key.lower() for key in iter_keys(payload)} & FORBIDDEN_MAPPING_KEYS)
    if found:
        joined = "、".join(found)
        raise MappingIsolationError(f"映射阶段禁止生成清洗和治理规则（发现字段: {joined}）")
    return payload


def mapping_payload_normalizer(settings: RuleSettings) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def normalize(payload: dict[str, Any]) -> dict[str, Any]:
        reject_mapping_side_effects(payload)
        mappings = payload.get("mappings")
        if not isinstance(mappings, list):
            payload["mappings"] = []
            return payload
        cleaned = []
        for item in mappings:
            if not isinstance(item, dict):
                continue
            evidence = item.get("evidence") or []
            if isinstance(evidence, str):
                evidence = [evidence]
            target = item.get("target_field")
            if target in ("", "null", "none", "未映射"):
                target = None
            confidence = item.get("confidence")
            score = item.get("confidence_score")
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                score = float(confidence)
            cleaned.append(
                {
                    "source_field": str(item.get("source_field") or "").strip(),
                    "target_field": None if target is None else str(target).strip() or None,
                    "explanation": str(item.get("explanation") or ""),
                    "confidence": normalize_label(confidence, settings),
                    "confidence_score": score if isinstance(score, (int, float)) else None,
                    "evidence": [str(piece) for piece in evidence if str(piece).strip()],
                    "reason": str(item.get("reason") or ""),
                    "needs_human_confirm": bool(item.get("needs_human_confirm", False)),
                }
            )
        payload["mappings"] = cleaned
        return payload

    return normalize


def samples_contradict(samples: list[Any], value_type: str) -> bool:
    values = [str(value).strip() for value in samples if value not in (None, "")]
    if not values:
        return False
    kind = (value_type or "unknown").lower()
    if kind in {"ip", "ipv4"}:
        return not any(_IPV4.search(value) for value in values)
    if kind in {"url", "uri"}:
        return not any(_URL.search(value) for value in values)
    if kind in {"datetime", "timestamp", "time"}:
        return not any(_DATE.search(value) for value in values)
    return False


def make_mapping(**kwargs: Any) -> dict[str, Any]:
    base = {
        "source_field": "",
        "target_field": None,
        "explanation": "",
        "confidence": None,
        "confidence_score": None,
        "evidence": [],
        "reason": "",
        "needs_human_confirm": True,
    }
    base.update(kwargs)
    return base


def review_mapping(
    mapping: dict[str, Any],
    standard_fields: list[dict[str, Any]],
    samples: list[Any],
    settings: RuleSettings,
) -> dict[str, Any]:
    """程序复核置信度：空依据不能为高，目标必须存在，样本冲突则降一级。"""
    data = make_mapping(**mapping)
    fields = {field["name"]: field for field in standard_fields if field.get("name")}
    target = data.get("target_field")
    evidence = [piece for piece in data.get("evidence") or [] if str(piece).strip()]
    reason = str(data.get("reason") or "").strip()
    confidence = data.get("confidence") or "low"
    if target and target not in fields:
        reason = f"目标字段不在规范表中: {target}"
        target = None
        confidence = "low"
    if not target:
        return make_mapping(
            source_field=data["source_field"],
            target_field=None,
            explanation=data.get("explanation") or reason or "未找到映射",
            confidence="low",
            confidence_score=data.get("confidence_score"),
            evidence=evidence,
            reason=reason or "未找到映射",
            needs_human_confirm=True,
        )
    if not evidence or not reason:
        if confidence == "high":
            confidence = "medium"
    value_type = str(fields[target].get("type") or "unknown")
    if samples_contradict(samples, value_type) and confidence in {"high", "medium"}:
        confidence = "medium" if confidence == "high" else "low"
    explanation = str(data.get("explanation") or "").strip() or reason
    return make_mapping(
        source_field=data["source_field"],
        target_field=target,
        explanation=explanation,
        confidence=confidence,
        confidence_score=data.get("confidence_score"),
        evidence=evidence,
        reason=reason,
        needs_human_confirm=confidence != "high",
    )


def fields_needing_retry(mappings: list[dict[str, Any]], source_field_names: list[str]) -> list[str]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mapping in mappings:
        grouped[mapping["source_field"]].append(mapping)
    retry: list[str] = []
    for name in source_field_names:
        group = grouped.get(name) or []
        if not group or any(
            not item.get("target_field") or item.get("confidence") in {"medium", "low", None}
            for item in group
        ):
            retry.append(name)
    return retry


def filter_mapped(mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in mappings if item.get("target_field")]


def apply_uniqueness(
    mappings: list[dict[str, Any]],
    standard_fields: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    meta = {field["name"]: bool(field.get("allow_multi_source", False)) for field in standard_fields}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    passthrough: list[dict[str, Any]] = []
    for item in mappings:
        target = item.get("target_field")
        if not target:
            passthrough.append(item)
            continue
        grouped[str(target)].append(item)
    kept: list[dict[str, Any]] = []
    messages: list[str] = []
    notes: list[str] = []
    for target, group in grouped.items():
        if meta.get(target, False) or len(group) == 1:
            kept.extend(group)
            continue
        ordered = sorted(group, key=lambda item: _RANK.get(item.get("confidence"), 0), reverse=True)
        top = _RANK.get(ordered[0].get("confidence"), 0)
        winners = [item for item in ordered if _RANK.get(item.get("confidence"), 0) == top]
        if len(winners) > 1:
            messages.append(f"规范字段 {target} 存在同置信度的多来源映射，需人工确认")
            for item in ordered:
                updated = dict(item)
                updated["needs_human_confirm"] = True
                kept.append(updated)
            continue
        kept.append(dict(winners[0]))
        for loser in ordered[1:]:
            demoted = dict(loser)
            demoted["target_field"] = None
            demoted["confidence"] = "low"
            demoted["needs_human_confirm"] = True
            demoted["reason"] = f"规范字段 {target} 不允许多来源映射"
            demoted["explanation"] = demoted["reason"]
            passthrough.append(demoted)
            notes.append(f"{loser['source_field']} 对 {target} 的映射已取消，因为该规范字段不允许多来源")
    return [*kept, *passthrough], messages, notes


def normalize_quality_decision(item: dict[str, Any]) -> dict[str, Any]:
    needs_extraction = bool(item.get("needs_extraction"))
    needs_cleaning = bool(item.get("needs_cleaning"))
    item["needs_extraction"] = needs_extraction
    item["needs_cleaning"] = needs_cleaning
    item["direct_mapping"] = not needs_extraction and not needs_cleaning
    if item["direct_mapping"]:
        item["extraction_goal"] = ""
        item["cleaning_goal"] = ""
    return item


def cleaning_is_supported(quality: dict[str, Any], samples: list[Any], target_type: str) -> tuple[bool, str]:
    """判断现有清洗白名单能否完成质量分析提出的转换。"""
    if not quality.get("needs_cleaning"):
        return True, ""
    goal = f"{quality.get('cleaning_goal') or ''} {quality.get('analysis') or ''}".lower()
    values = [str(value).strip() for value in samples if value not in (None, "")]
    kind = (target_type or "").lower()
    if _is_integer_ip_conversion(goal, kind, values):
        return False, "白名单算子无法完成整数 IP 转换，表注册阶段跳过清洗"
    if _is_protocol_conversion(goal):
        return False, "白名单算子无法完成协议编码转换，表注册阶段跳过清洗"
    if _is_cosmetic_cleaning(goal):
        return True, ""
    if _is_time_cleaning(goal, kind):
        if values and all(_datetime_supported(value) for value in values):
            return True, ""
        return False, "白名单时间算子无法解析当前样本，表注册阶段跳过清洗"
    return False, "清洗目标超出白名单算子，表注册阶段跳过清洗"


def skip_unsupported_cleaning(quality: dict[str, Any], samples: list[Any], target_type: str) -> dict[str, Any]:
    supported, reason = cleaning_is_supported(quality, samples, target_type)
    if supported or not quality.get("needs_cleaning"):
        return quality
    quality["needs_cleaning"] = False
    quality["cleaning_skipped_reason"] = reason
    if not quality.get("needs_extraction"):
        quality["direct_mapping"] = True
    return quality


def _is_integer_ip_conversion(goal: str, target_type: str, values: list[str]) -> bool:
    mentions_ip = any(token in goal for token in ("ip", "ipv4", "点分")) or "ip" in target_type
    return mentions_ip and bool(values) and all(_ipv4_integer(value) for value in values)


def _is_protocol_conversion(goal: str) -> bool:
    return "协议" in goal and any(token in goal for token in ("名称", "编码", "转换"))


def _is_cosmetic_cleaning(goal: str) -> bool:
    tokens = ("空白", "空格", "大小写", "trim", "lower", "upper", "whitespace", "首尾")
    return any(token in goal for token in tokens)


def _is_time_cleaning(goal: str, target_type: str) -> bool:
    tokens = ("时间", "日期", "datetime", "timestamp", "time")
    return any(token in goal for token in tokens) or any(token in target_type for token in ("datetime", "timestamp", "time"))


def _datetime_supported(value: str) -> bool:
    from table_registration.tools.cleaning_executor import CleaningError, apply_cleaning

    try:
        apply_cleaning(
            {"operator": "normalize_datetime", "input_formats": [], "output_format": "%Y-%m-%d %H:%M:%S"},
            value,
        )
    except CleaningError:
        return False
    return True


def _ipv4_integer(value: str) -> bool:
    if not value.isdigit():
        return False
    return 0 <= int(value) <= 0xFFFFFFFF


def check_regex_safety(pattern: str, settings: RuleSettings) -> list[str]:
    errors: list[str] = []
    if len(pattern) > settings.regex_max_length:
        errors.append("正则超过长度上限")
    if _NESTED_QUANTIFIER.search(pattern):
        errors.append("正则存在灾难性回溯风险")
    try:
        re.compile(pattern)
    except re.error as exc:
        errors.append(f"正则无法编译: {exc}")
    return errors


def validate_standard_schema(schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not schema or not schema.get("id") or not schema.get("category_alias"):
        errors.append("规范表缺少 id 或 category_alias")
    fields = schema.get("fields") if schema else None
    if not isinstance(fields, list) or not fields:
        errors.append("规范表缺少字段")
        return errors
    names = []
    for field in fields:
        # 从 'storage_name' 或 'name' 中提取字段名称
        name = str(field.get("storage_name") or field.get("name") or "").strip()
        if not name:
            errors.append("规范字段名称不能为空")
        names.append(name)
    if len([name for name in names if name]) != len(set(name for name in names if name)):
        errors.append("规范字段名称重复")
    return errors


def validate_mapping_targets(
    mappings: list[dict[str, Any]],
    standard_fields: list[dict[str, Any]],
) -> list[str]:
    names = {field["name"] for field in standard_fields}
    errors = []
    for mapping in mappings:
        target = mapping.get("target_field")
        if target and target not in names:
            errors.append(f"目标字段不在规范表中: {target}")
        if target and not mapping.get("evidence"):
            errors.append(f"{mapping.get('source_field')} 的映射缺少判断依据")
    return errors


def stamp_version(rule: dict[str, Any], version: int) -> dict[str, Any]:
    stamped = dict(rule)
    stamped["version"] = version
    return stamped


def record_failure(errors: list[str], message: str) -> list[str]:
    errors.append(message)
    return errors


def run_extraction_sample_validation(*args, **kwargs):
    from table_registration.tools.regex_executor import test_extraction_rule

    return test_extraction_rule(*args, **kwargs)


def run_cleaning_sample_validation(*args, **kwargs):
    from table_registration.tools.cleaning_executor import test_cleaning_rule

    return test_cleaning_rule(*args, **kwargs)


def check_idempotent(apply_once: Callable[[Any], Any], value: Any) -> str | None:
    first = apply_once(value)
    second = apply_once(first)
    if first != second:
        return "规则不满足幂等"
    return None


RULES = {
    "sample-required": check_sample_required,
    "schema-branching": choose_mapping_mode,
    "mapping-fallback": fields_needing_retry,
    "mapped-field-only": filter_mapped,
    "mapping-cleaning-isolation": reject_mapping_side_effects,
    "mapping-confidence-policy": review_mapping,
    "mapping-target-validation": validate_mapping_targets,
    "mapping-uniqueness-policy": apply_uniqueness,
    "unmapped-field-policy": make_mapping,
    "mapping-evidence-required": validate_mapping_targets,
    "sample-quality-check": has_effective_rows,
    "extraction-necessity": normalize_quality_decision,
    "cleaning-necessity": normalize_quality_decision,
    "no-unnecessary-transformation": normalize_quality_decision,
    "regex-safety": check_regex_safety,
    "rule-sample-validation": run_extraction_sample_validation,
    "cleaning-sample-validation": run_cleaning_sample_validation,
    "rule-versioning": stamp_version,
    "rule-no-silent-failure": record_failure,
    "rule-idempotency": check_idempotent,
}
