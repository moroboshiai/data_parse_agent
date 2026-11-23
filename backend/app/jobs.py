"""后台任务。注册、解析、质检和富化可能调用大模型，不能堵在请求里。"""

from __future__ import annotations

import threading
from typing import Any, Callable
from uuid import uuid4

from table_registration.llm_trace import log_job


class JobRunner:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._write = threading.Lock()

    def start(self, kind: str, work: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        job_id = uuid4().hex
        job = {"job_id": job_id, "kind": kind, "status": "running", "result": None, "error": ""}
        with self._lock:
            self._jobs[job_id] = job
        log_job(kind, job_id=job_id, status="开始")

        def _run() -> None:
            try:
                with self._write:
                    result = work()
                self._finish(job_id, status="done", result=result)
            except Exception as exc:
                self._finish(job_id, status="failed", error=str(exc))

        threading.Thread(target=_run, daemon=True).start()
        return dict(job)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            return dict(job)

    def _finish(self, job_id: str, *, status: str, result: dict[str, Any] | None = None, error: str = "") -> None:
        kind = ""
        with self._lock:
            job = self._jobs[job_id]
            kind = str(job.get("kind") or "")
            job["status"] = status
            job["result"] = result
            job["error"] = error
        label = "结束" if status == "done" else "失败"
        log_job(kind, job_id=job_id, status=label, error=error)
