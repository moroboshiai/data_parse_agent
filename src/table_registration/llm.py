"""本地 OpenAI 兼容对话接口。

请求契约与现有治理项目一致：POST {base_url}/v1/chat/completions，
关闭思考模式，并从 choices[0].message.content 中抽取 JSON。
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

import requests
from pydantic import BaseModel, ValidationError

from table_registration.config import LlmSettings, env_flag, get_llm_settings
from table_registration.llm_trace import log_call_end, log_call_start, record_call


class LlmError(Exception):
    pass


class CallBudgetExceeded(LlmError):
    pass


def resolve_chat_url(base_url: str | None = None) -> str:
    settings = get_llm_settings()
    raw = (base_url or os.environ.get("LLM_BASE_URL") or settings.base_url).rstrip("/")
    if raw.endswith("/chat/completions"):
        return raw
    return raw + "/v1/chat/completions"


def resolve_model(model: str | None = None) -> str:
    settings = get_llm_settings()
    return model or os.environ.get("LLM_MODEL") or settings.model


def resolve_requests_verify() -> bool | str:
    settings = get_llm_settings()
    env = os.environ.get("LLM_VERIFY_SSL")
    if env is not None:
        lowered = env.strip().lower()
        if lowered in {"0", "false", "no", "off"}:
            return False
        if lowered in {"1", "true", "yes", "on"}:
            return True
        return env.strip()
    if settings.ca_bundle:
        return settings.ca_bundle
    return settings.verify_ssl


def chat_completion(
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
    timeout: float | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> str:
    settings = get_llm_settings()
    if not env_flag("LLM_ENABLED", settings.enabled):
        raise LlmError("模型已关闭")
    verify = resolve_requests_verify()
    if verify is False:
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
    payload = {
        "model": resolve_model(model),
        "messages": messages,
        "temperature": settings.temperature if temperature is None else temperature,
        "max_tokens": settings.max_tokens if max_tokens is None else max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    response = requests.post(
        resolve_chat_url(base_url),
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=settings.timeout if timeout is None else timeout,
        verify=verify,
    )
    if response.status_code != 200:
        raise LlmError(f"模型请求失败: HTTP {response.status_code}")
    body = response.json()
    content = body["choices"][0]["message"]["content"]
    return re.sub(r"\n+", "\n", content)


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL)
    if fence:
        stripped = fence.group(1)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise LlmError("模型输出不是 JSON 对象")
    try:
        payload = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LlmError("模型输出不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise LlmError("模型输出不是 JSON 对象")
    return payload


class LlmClient:
    def __init__(
        self,
        *,
        enabled: bool | None = None,
        max_calls: int | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        settings: LlmSettings | None = None,
    ) -> None:
        cfg = settings or get_llm_settings()
        self.enabled = cfg.enabled if enabled is None else enabled
        self.max_calls = cfg.max_calls_per_task if max_calls is None else max_calls
        self.max_retries = cfg.max_retries if max_retries is None else max_retries
        self.timeout = cfg.timeout if timeout is None else timeout
        self.temperature = cfg.temperature if temperature is None else temperature
        self.max_tokens = cfg.max_tokens if max_tokens is None else max_tokens
        self.call_count = 0
        self.failure_count = 0

    def complete_json(
        self,
        system: str,
        user: str,
        model: type[BaseModel],
        *,
        payload_normalizer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> BaseModel:
        if not self.enabled:
            raise LlmError("模型已关闭")
        if self.call_count >= self.max_calls:
            raise CallBudgetExceeded("已达到任务模型调用上限")
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if self.call_count >= self.max_calls:
                break
            self.call_count += 1
            started = datetime.now()
            text = ""
            parsed: dict[str, Any] | None = None
            error = ""
            result: BaseModel | None = None
            try:
                try:
                    log_call_start(system, user)
                except Exception:
                    pass
                text = chat_completion(
                    [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    timeout=self.timeout,
                )
                payload = extract_json_object(text)
                if payload_normalizer is not None:
                    payload = payload_normalizer(payload)
                parsed = payload
                result = model.model_validate(payload)
            except (LlmError, ValidationError, requests.RequestException, KeyError, IndexError) as exc:
                last_error = exc
                error = str(exc)
                self.failure_count += 1
            _trace_call(
                system=system,
                user=user,
                model=model,
                started=started,
                attempt=attempt,
                call_index=self.call_count,
                raw_response=text,
                parsed_json=parsed,
                error=error,
            )
            if result is not None:
                return result
        raise LlmError(f"模型输出无法通过校验: {last_error}") from last_error


def _trace_call(
    *,
    system: str,
    user: str,
    model: type[BaseModel],
    started: datetime,
    attempt: int,
    call_index: int,
    raw_response: str = "",
    parsed_json: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    finished = datetime.now()
    duration_ms = max(0, int((finished - started).total_seconds() * 1000))
    try:
        log_call_end(
            system=system,
            raw_response=raw_response,
            parsed_json=parsed_json,
            error=error,
            duration_ms=duration_ms,
        )
        record_call(
            system=system,
            user=user,
            output_model=model.__name__,
            started_at=started,
            finished_at=finished,
            attempt=attempt + 1,
            call_index=call_index,
            raw_response=raw_response,
            parsed_json=parsed_json,
            error=error,
            model=resolve_model(),
            url=resolve_chat_url(),
        )
    except Exception:
        return
