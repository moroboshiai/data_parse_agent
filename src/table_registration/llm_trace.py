"""把模型调用的输入输出落到 outputs/llm_traces，并在命令行打截断摘要。"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from table_registration.config import env_flag, find_repo_root, get_llm_settings

_LOCK = threading.Lock()
_SKILL = re.compile(r"^SKILL:\s*(.+)$", re.MULTILINE)
_CONSOLE_CHARS = 400
_AGENTS = {
    "source-schema-normalization": "表结构注册",
    "sample-based-field-mapping": "表结构注册",
    "schema-based-field-mapping": "表结构注册",
    "sample-assisted-mapping": "表结构注册",
    "field-quality-analysis": "表结构注册",
    "extraction-rule-generation": "表结构注册",
    "cleaning-rule-generation": "表结构注册",
    "source-schema-registration": "表结构注册",
    "pipeline-planning": "数据解析",
    "rule-generation": "数据解析",
    "rule-optimization": "数据解析",
    "rule-reuse-analysis": "数据解析",
    "parsing-issue-diagnosis": "数据解析",
    "pipeline-quality-evaluation": "数据解析",
    "quality-planning": "数据质检",
    "quality-analysis": "数据质检",
    "quality-diagnosis": "数据质检",
    "anomaly-analysis": "数据质检",
    "governance-recommendation": "数据质检",
    "security-label-classification": "数据富化",
    "investigation-planning": "数据富化",
    "investigation-summary": "数据富化",
    "governance-routing": "治理主控",
}
_JOB_AGENTS = {
    "register": "表结构注册",
    "confirm-candidate": "表结构注册",
    "build": "数据解析",
    "parse": "数据解析",
    "learn": "数据解析",
    "init-profile": "数据质检",
    "analyze": "数据质检",
    "diagnose": "数据质检",
    "enrich-batch": "数据富化",
    "enrich-one": "数据富化",
    "investigate": "数据富化",
    "governance-step": "治理主控",
    "governance-confirm": "治理主控",
    "governance-resume": "治理主控",
}


def skill_name(system: str) -> str:
    matched = _SKILL.search(system or "")
    return (matched.group(1) if matched else "").strip() or "unknown"


def agent_for_skill(skill: str) -> str:
    return _AGENTS.get(skill, "未知智能体")


def agent_for_job(kind: str) -> str:
    return _JOB_AGENTS.get(kind, "后台任务")


def log_job(kind: str, *, job_id: str, status: str, error: str = "") -> None:
    agent = agent_for_job(kind)
    extra = f"  error={_clip(error)}" if error else ""
    _console(f"[任务] {agent}  {kind}  {status}  job={job_id[:8]}{extra}")


def log_call_start(system: str, user: str) -> None:
    skill = skill_name(system)
    _console(f"[智能体] {agent_for_skill(skill)}  {skill}  开始调用")
    _console(f"  输入: {_clip(_compact(user))}")


def log_call_end(
    *,
    system: str,
    raw_response: str = "",
    parsed_json: dict[str, Any] | None = None,
    error: str = "",
    duration_ms: int = 0,
) -> None:
    skill = skill_name(system)
    agent = agent_for_skill(skill)
    if error:
        _console(f"[智能体] {agent}  {skill}  失败  {duration_ms}ms  {_clip(error)}")
        return
    body = json.dumps(parsed_json, ensure_ascii=False) if parsed_json is not None else raw_response
    _console(f"[智能体] {agent}  {skill}  完成  {duration_ms}ms")
    _console(f"  输出: {_clip(_compact(body))}")


def record_call(
    *,
    system: str,
    user: str,
    output_model: str,
    started_at: datetime,
    finished_at: datetime,
    attempt: int,
    call_index: int,
    raw_response: str = "",
    parsed_json: dict[str, Any] | None = None,
    error: str = "",
    model: str = "",
    url: str = "",
) -> Path | None:
    directory = _trace_dir()
    if directory is None:
        return None
    payload = {
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_ms": max(0, int((finished_at - started_at).total_seconds() * 1000)),
        "model": model,
        "url": url,
        "skill": skill_name(system),
        "output_model": output_model,
        "attempt": attempt,
        "call_index": call_index,
        "status": "ok" if not error else "error",
        "error": error,
        "input": {
            "system": system,
            "user": user,
            "payload": _as_json(user),
        },
        "output": {
            "raw_response": raw_response,
            "parsed_json": parsed_json,
        },
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = started_at.strftime("%Y%m%dT%H%M%S")
        name = f"{stamp}_{_safe(payload['skill'])}_{uuid4().hex[:8]}.json"
        path = directory / name
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        summary = {
            "started_at": payload["started_at"],
            "skill": payload["skill"],
            "status": payload["status"],
            "duration_ms": payload["duration_ms"],
            "error": error,
            "file": str(path),
        }
        with _LOCK:
            path.write_text(text, encoding="utf-8-sig")
            index = directory / "calls.jsonl"
            line = json.dumps(summary, ensure_ascii=False) + "\n"
            payload_bytes = line.encode("utf-8")
            if not index.is_file() or index.stat().st_size == 0:
                payload_bytes = b"\xef\xbb\xbf" + payload_bytes
            with index.open("ab") as handle:
                handle.write(payload_bytes)
        return path
    except OSError:
        return None


def _trace_dir() -> Path | None:
    settings = get_llm_settings()
    if not env_flag("LLM_LOG_CALLS", settings.log_calls):
        return None
    raw = os.environ.get("LLM_TRACE_DIR", "").strip()
    if raw:
        return Path(raw)
    try:
        return find_repo_root() / "outputs" / "llm_traces"
    except FileNotFoundError:
        return None


def _as_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None


def _compact(text: str) -> str:
    payload = _as_json(text)
    if payload is not None:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _clip(text: str, limit: int = _CONSOLE_CHARS) -> str:
    value = str(text or "").replace("\n", " ")
    if len(value) <= limit:
        return value
    return value[:limit] + "…"


def _console_encoding() -> str:
    if os.name != "nt":
        return sys.stdout.encoding or "utf-8"
    try:
        import ctypes

        code_page = int(ctypes.windll.kernel32.GetConsoleOutputCP())
        if code_page in {0, 65001}:
            return "utf-8"
        return f"cp{code_page}"
    except Exception:
        return "gbk"


def _console(line: str) -> None:
    text = line + "\n"
    encoding = _console_encoding()
    try:
        if os.name == "nt" and hasattr(sys.stdout, "buffer") and sys.stdout.isatty():
            sys.stdout.buffer.write(text.encode(encoding, errors="replace"))
            sys.stdout.buffer.flush()
            return
    except Exception:
        pass
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode(encoding, errors="replace"))
        sys.stdout.buffer.flush()


def _safe(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return cleaned or "skill"
