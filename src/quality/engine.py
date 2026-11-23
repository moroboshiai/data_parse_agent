"""一次扫描执行画像范围内的规则。单条规则失败不会中断其余规则。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from quality.detectors.operators import RELATION_OPERATORS, EvalContext, evaluate
from quality.schemas import QualityProfile
from quality.timing import in_window, parse_time, zone

FORMAT_OPERATORS = {"validate_ip", "validate_domain", "validate_time", "validate_number"}
STATISTICAL_OPERATORS = {"compare_metric", "compare_baseline", "compare_distribution"}
_SAMPLE_LIMIT = 5
_DISTINCT_LIMIT = 100


def inspect_rows(
    rows: Iterable[dict[str, Any]],
    rules: list[dict[str, Any]],
    profile: QualityProfile,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    baseline: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(zone(profile.timezone))
    context = EvalContext(now=current)
    prepared = [_prepare(rule, profile) for rule in rules if rule.get("enabled", True)]
    row_rules = [rule for rule in prepared if rule["operator"] not in STATISTICAL_OPERATORS]
    stat_rules = [rule for rule in prepared if rule["operator"] in STATISTICAL_OPERATORS]
    buckets = {rule["rule_id"]: _blank_bucket() for rule in row_rules}
    broken: set[str] = set()
    errors: list[dict[str, str]] = []
    distributions: dict[str, Counter[str]] = {name: Counter() for name in profile.distribution_dimensions}
    hourly: Counter[str] = Counter()
    total = 0
    outside = 0
    time_invalid = 0
    first_time = ""
    last_time = ""
    windowed = bool(profile.time_field) and (start is not None or end is not None)

    for row in rows:
        moment = _row_time(row, profile)
        if windowed:
            if moment is None:
                time_invalid += 1
                outside += 1
                continue
            if not in_window(moment, start, end):
                outside += 1
                continue
        total += 1
        if moment is not None:
            stamp = moment.astimezone(zone(profile.timezone)).isoformat()
            first_time = stamp if not first_time or stamp < first_time else first_time
            last_time = stamp if stamp > last_time else last_time
            hourly[moment.astimezone(zone(profile.timezone)).strftime("%Y-%m-%dT%H")] += 1
        for name in profile.distribution_dimensions:
            _count_distinct(distributions[name], row.get(name))
        for rule in row_rules:
            rule_id = rule["rule_id"]
            if rule_id in broken:
                continue
            try:
                outcome = evaluate(rule["operator"], row, rule["params"], context)
            except Exception as exc:
                broken.add(rule_id)
                errors.append({"rule_id": rule_id, "error": str(exc)})
                continue
            bucket = buckets[rule_id]
            bucket[outcome] += 1
            if outcome == "fail" and len(bucket["samples"]) < _SAMPLE_LIMIT:
                bucket["samples"].append(_sample(row, rule["params"]))

    results = [_row_result(rule, buckets[rule["rule_id"]], total, context) for rule in row_rules]
    for rule_id in broken:
        for result in results:
            if result["rule_id"] == rule_id:
                result["status"] = "error"
                result["triggered"] = False
    metrics = _metrics(total, results)
    shares = {name: _shares(counter, total) for name, counter in distributions.items()}
    for rule in stat_rules:
        try:
            results.append(_stat_result(rule, metrics, shares, baseline, profile.source_id))
        except Exception as exc:
            errors.append({"rule_id": rule["rule_id"], "error": str(exc)})
            results.append(_error_result(rule, profile.source_id, str(exc)))
    return {
        "source_id": profile.source_id,
        "category": profile.category,
        "total_count": total,
        "outside_count": outside,
        "time_invalid_count": time_invalid,
        "first_event_time": first_time,
        "last_event_time": last_time,
        "hourly_count": dict(sorted(hourly.items())),
        "rule_results": results,
        "metrics": metrics,
        "distributions": shares,
        "distribution_top": {name: _top(counter) for name, counter in distributions.items()},
        "errors": errors,
    }


def rule_group(rule: dict[str, Any]) -> str:
    operator = str(rule.get("operator") or "")
    if operator in {"compare_baseline", "compare_distribution"}:
        return "compare_baseline"
    if operator in RELATION_OPERATORS:
        return "run_relation_rules"
    return "run_field_rules"


def _prepare(rule: dict[str, Any], profile: QualityProfile) -> dict[str, Any]:
    prepared = dict(rule)
    params = dict(rule.get("params") or {})
    params.setdefault("timezone", profile.timezone)
    params["_rule_id"] = rule.get("rule_id")
    if params.get("fields_from_profile") == "duplicate_fields":
        params["fields"] = list(profile.duplicate_fields)
    prepared["params"] = params
    prepared["operator"] = str(rule.get("operator") or "")
    prepared["rule_id"] = str(rule.get("rule_id") or "")
    return prepared


def _row_time(row: dict[str, Any], profile: QualityProfile) -> datetime | None:
    if not profile.time_field:
        return None
    return parse_time(row.get(profile.time_field), profile.time_formats, profile.timezone)


def _count_distinct(counter: Counter[str], value: Any) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        text = ""
    else:
        text = str(value).strip()
    if text in counter or len(counter) < _DISTINCT_LIMIT:
        counter[text] += 1
    else:
        counter["__other__"] += 1


def _blank_bucket() -> dict[str, Any]:
    return {"pass": 0, "fail": 0, "unknown": 0, "skip": 0, "samples": []}


def _sample(row: dict[str, Any], params: dict[str, Any]) -> str:
    names = []
    for key in ("field", "type_field", "value_field", "query_field", "answer_field", "rcode_field", "item_field", "collection_field", "time_field"):
        if params.get(key):
            names.append(str(params[key]))
    names.extend(str(item) for item in params.get("fields") or [])
    parts = [f"{name}={row.get(name)}" for name in dict.fromkeys(names) if name]
    return ", ".join(parts)[:200]


def _row_result(rule: dict[str, Any], bucket: dict[str, Any], total: int, ctx: EvalContext) -> dict[str, Any]:
    checked = bucket["pass"] + bucket["fail"]
    fail_rate = bucket["fail"] / checked if checked else 0.0
    field_name = _field_name(rule)
    result = _base_result(rule, field_name)
    result.update(
        {
            "total_count": total,
            "pass_count": bucket["pass"],
            "fail_count": bucket["fail"],
            "unknown_count": bucket["unknown"],
            "skip_count": bucket["skip"],
            "pass_rate": bucket["pass"] / checked if checked else 0.0,
            "fail_rate": fail_rate,
            "status": "completed",
            "triggered": _triggered(rule, fail_rate, bucket["fail"]),
            "evidence": {
                "sample_invalid_values": list(bucket["samples"]),
                "partial": bool(ctx.partial.get(rule["rule_id"])),
            },
        }
    )
    return result


def _triggered(rule: dict[str, Any], fail_rate: float, fail_count: int) -> bool:
    if fail_count <= 0:
        return False
    params = rule.get("params") or {}
    if "alert_rate" in params:
        threshold = float(params["alert_rate"])
    else:
        threshold = {"high": 0.01, "medium": 0.05, "low": 0.2, "info": 2}.get(str(rule.get("severity") or "medium"), 0.05)
    return fail_rate >= threshold


def _metrics(total: int, results: list[dict[str, Any]]) -> dict[str, float]:
    metrics: dict[str, float] = {"volume": float(total)}
    for result in results:
        field_name = result.get("field") or ""
        operator = result.get("operator") or ""
        if operator == "field_empty" and field_name:
            metrics[f"field_null_rate:{field_name}"] = float(result["fail_rate"])
        if operator in FORMAT_OPERATORS and field_name:
            metrics[f"field_invalid_rate:{field_name}"] = float(result["fail_rate"])
        if operator == "validate_enum" and field_name:
            checked = result["pass_count"] + result["fail_count"] + result["unknown_count"]
            metrics[f"field_unknown_enum_rate:{field_name}"] = (result["unknown_count"] / checked) if checked else 0.0
        if operator == "record_fingerprint":
            metrics["duplicate_rate"] = float(result["fail_rate"])
    return metrics


def _stat_result(
    rule: dict[str, Any],
    metrics: dict[str, float],
    shares: dict[str, dict[str, float]],
    baseline: dict[str, Any] | None,
    source_id: str,
) -> dict[str, Any]:
    operator = rule["operator"]
    params = rule.get("params") or {}
    field_name = str(params.get("field") or _scope_field(rule))
    evidence: dict[str, Any] = {}
    triggered = False
    observed = 0.0
    if operator == "compare_metric":
        key = _metric_key(str(params.get("metric") or ""), field_name)
        observed = float(metrics.get(key) or 0)
        evidence = {"metric": key, "observed": observed, "threshold": params.get("threshold"), "comparison": params.get("comparison")}
        triggered = key in metrics and _compare(observed, params.get("comparison") or "gt", float(params.get("threshold") or 0))
    elif operator == "compare_baseline":
        key = _metric_key(str(params.get("metric") or "volume"), field_name)
        observed = float(metrics.get(key) or 0)
        base_metrics = (baseline or {}).get("metrics") or {}
        base = base_metrics.get(key)
        evidence = {"metric": key, "observed": observed, "baseline": base}
        if base not in (None, 0):
            ratio = observed / float(base)
            evidence["ratio"] = ratio
            low = params.get("ratio_lt")
            high = params.get("ratio_gt")
            triggered = (low is not None and ratio < float(low)) or (high is not None and ratio > float(high))
        else:
            evidence["missing_baseline"] = True
    elif operator == "compare_distribution":
        current = shares.get(field_name) or {}
        base = ((baseline or {}).get("distributions") or {}).get(field_name) or {}
        delta = 0.0
        if base:
            keys = set(current) | set(base)
            delta = max((abs(float(current.get(key) or 0) - float(base.get(key) or 0)) for key in keys), default=0.0)
            triggered = delta > float(params.get("max_delta") or 0)
        evidence = {"field": field_name, "delta": delta, "missing_baseline": not bool(base)}
        observed = delta
    else:
        raise KeyError(f"未知统计算子: {operator}")
    result = _base_result(rule, field_name)
    result.update(
        {
            "total_count": int(metrics.get("volume") or 0),
            "pass_count": 0 if triggered else 1,
            "fail_count": 1 if triggered else 0,
            "unknown_count": 0,
            "skip_count": 0,
            "pass_rate": 0.0 if triggered else 1.0,
            "fail_rate": observed,
            "status": "completed",
            "triggered": triggered,
            "evidence": evidence,
            "source_id": source_id,
        }
    )
    return result


def _error_result(rule: dict[str, Any], source_id: str, message: str) -> dict[str, Any]:
    result = _base_result(rule, _field_name(rule))
    result.update(
        {
            "source_id": source_id,
            "status": "error",
            "triggered": False,
            "error": message,
            "evidence": {},
        }
    )
    return result


def _base_result(rule: dict[str, Any], field_name: str) -> dict[str, Any]:
    scope = rule.get("scope") or {}
    return {
        "rule_id": rule.get("rule_id"),
        "rule_version": rule.get("version") or "",
        "rule_name": rule.get("rule_name") or rule.get("rule_id"),
        "source_id": scope.get("source_id") or "",
        "field": field_name,
        "dimension": rule.get("dimension") or "",
        "operator": rule.get("operator") or "",
        "severity": rule.get("severity") or "medium",
        "group": rule_group(rule),
        "total_count": 0,
        "pass_count": 0,
        "fail_count": 0,
        "unknown_count": 0,
        "skip_count": 0,
        "pass_rate": 0.0,
        "fail_rate": 0.0,
        "status": "completed",
        "triggered": False,
        "evidence": {},
        "error": "",
    }


def _field_name(rule: dict[str, Any]) -> str:
    params = rule.get("params") or {}
    return str(params.get("field") or _scope_field(rule))


def _scope_field(rule: dict[str, Any]) -> str:
    fields = (rule.get("scope") or {}).get("fields") or []
    return str(fields[0]) if fields else ""


def _metric_key(metric: str, field_name: str) -> str:
    if metric in {"volume", "duplicate_rate"} or not field_name:
        return metric
    return f"{metric}:{field_name}"


def _compare(observed: float, comparison: str, threshold: float) -> bool:
    if comparison == "gt":
        return observed > threshold
    if comparison == "gte":
        return observed >= threshold
    if comparison == "lt":
        return observed < threshold
    if comparison == "lte":
        return observed <= threshold
    return False


def _shares(counter: Counter[str], total: int) -> dict[str, float]:
    if total <= 0:
        return {}
    return {key: count / total for key, count in counter.items()}


def _top(counter: Counter[str], limit: int = 10) -> list[dict[str, Any]]:
    return [{"value": key, "count": count} for key, count in counter.most_common(limit)]


def snapshot(inspection: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": inspection.get("source_id"),
        "category": inspection.get("category"),
        "metrics": dict(inspection.get("metrics") or {}),
        "distributions": inspection.get("distributions") or {},
        "volume": inspection.get("total_count") or 0,
    }
