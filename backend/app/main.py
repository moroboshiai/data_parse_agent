"""治理控制台 API。默认连接真实智能体，GOVERNANCE_API_MODE=demo 时使用示例数据。"""

from __future__ import annotations

import json
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.live import LiveService, display_paths
from app.store import DemoStore
from governance.store import RunBusyError

app = FastAPI(title="数据治理控制台", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
MODE = os.environ.get("GOVERNANCE_API_MODE", "live").strip().lower()
live = LiveService() if MODE != "demo" else None
demo = DemoStore() if MODE == "demo" else None


@app.middleware("http")
async def show_relative_paths(request, call_next):
    response = await call_next(request)
    if live is None or "application/json" not in response.headers.get("content-type", ""):
        return response
    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response(content=body, status_code=response.status_code, headers=dict(response.headers), media_type=response.media_type)
    headers = {key: value for key, value in response.headers.items() if key.lower() not in {"content-length", "content-type"}}
    return JSONResponse(display_paths(live.root, payload), status_code=response.status_code, headers=headers)


class RunCreate(BaseModel):
    source_name: str
    sample_path: str
    standard_schema_path: str
    input_path: str = ""
    knowledge_path: str = ""


class RuleEdit(BaseModel):
    kind: str
    rule_id: str = ""
    operator: str = ""
    pattern: str = ""
    group: int | None = None
    output_format: str = ""
    description: str = ""


class MappingEdit(BaseModel):
    index: int
    source_field: str
    target_field: str
    rules: list[RuleEdit] = []


class CandidateEdit(BaseModel):
    mappings: list[MappingEdit]


class RegisterBody(BaseModel):
    sample: str
    standard: str
    source_name: str = "source_table"
    source_schema: str = ""


class BuildBody(BaseModel):
    candidate: str
    sample: str
    source_type: str = "generic"


class ParseBody(BaseModel):
    pipeline_id: str
    input: str


class PublishBody(BaseModel):
    rule_id: str
    version: int
    action: str = "publish"


class ProfileBody(BaseModel):
    standard: str
    source_id: str = ""


class AnalyzeBody(BaseModel):
    profile: str
    input: str
    start: str = ""
    end: str = ""


class BaselineBody(BaseModel):
    source_id: str
    category: str = ""
    snapshot_id: str


class EnrichBody(BaseModel):
    input: str
    knowledge: str


class EnrichOneBody(BaseModel):
    input: str
    knowledge: str = ""
    event_id: str = ""
    index: int = 0


class InvestigateBody(BaseModel):
    event: str
    knowledge: str


class KnowledgeItemBody(BaseModel):
    path: str = ""
    match: dict = Field(default_factory=dict)
    item: dict = Field(default_factory=dict)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "demo" if demo else "live"}


@app.get("/api/meta")
def meta() -> dict:
    if demo:
        return {"mode": "demo", "stages": []}
    return live.meta()


@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict:
    if demo:
        raise HTTPException(status_code=404, detail="演示模式没有后台任务")
    return _or_404(lambda: live.jobs.get(job_id))


@app.get("/api/dashboard")
def dashboard() -> dict:
    return demo.dashboard() if demo else live.dashboard()


@app.get("/api/runs")
def list_runs() -> dict:
    return {"runs": demo.list_runs() if demo else live.list_runs()}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return _or_404(lambda: demo.get_run(run_id) if demo else live.get_run(run_id))


@app.post("/api/runs")
def create_run(body: RunCreate) -> dict:
    try:
        if demo:
            return demo.create_run(body.model_dump())
        return live.start_run(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/runs/{run_id}")
def remove_run(run_id: str) -> dict:
    try:
        if demo:
            return demo.delete_run(run_id)
        return live.delete_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="记录不存在") from exc
    except RunBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/step")
def step_run(run_id: str) -> dict:
    return _queue(lambda: live.queue_step(run_id))


@app.post("/api/runs/{run_id}/confirm")
def confirm_run(run_id: str) -> dict:
    if demo:
        return _mutate(lambda: demo.confirm_run(run_id))
    return _queue(lambda: live.queue_confirm(run_id))


@app.post("/api/runs/{run_id}/resume")
def resume_run(run_id: str) -> dict:
    if demo:
        return _mutate(lambda: demo.resume_run(run_id))
    return _queue(lambda: live.queue_resume(run_id))


@app.get("/api/candidates")
def list_candidates() -> dict:
    return {"candidates": demo.list_candidates() if demo else live.list_candidates()}


@app.get("/api/candidates/{candidate_id}")
def get_candidate(candidate_id: str) -> dict:
    return _or_404(lambda: demo.get_candidate(candidate_id) if demo else live.get_candidate(candidate_id))


@app.put("/api/candidates/{candidate_id}")
def update_candidate(candidate_id: str, body: CandidateEdit) -> dict:
    return _mutate(lambda: demo.update_candidate(candidate_id, body.model_dump()) if demo else live.update_candidate(candidate_id, body.model_dump()))


@app.delete("/api/candidates/{candidate_id}")
def remove_candidate(candidate_id: str) -> dict:
    return _or_404(lambda: demo.delete_candidate(candidate_id) if demo else live.delete_candidate(candidate_id))


@app.post("/api/registration")
def register(body: RegisterBody) -> dict:
    return _queue(lambda: live.queue_register(body.model_dump()))


@app.post("/api/candidates/{candidate_id}/confirm")
def confirm_candidate(candidate_id: str) -> dict:
    return _queue(lambda: live.queue_confirm_candidate(candidate_id))


@app.get("/api/pipelines")
def list_pipelines() -> dict:
    return {"pipelines": demo.list_pipelines() if demo else live.list_pipelines()}


@app.get("/api/pipelines/{pipeline_id}/preview")
def pipeline_preview(pipeline_id: str) -> dict:
    return _or_404(lambda: demo.pipeline_preview(pipeline_id) if demo else live.pipeline_preview(pipeline_id))


@app.get("/api/pipelines/{pipeline_id}/events")
def pipeline_events(pipeline_id: str) -> dict:
    return _or_404(lambda: demo.pipeline_events(pipeline_id) if demo else live.pipeline_events(pipeline_id))


@app.delete("/api/pipelines/{pipeline_id}")
def remove_pipeline(pipeline_id: str) -> dict:
    return _or_404(lambda: demo.delete_pipeline(pipeline_id) if demo else live.delete_pipeline(pipeline_id))


@app.post("/api/parsing/build")
def build_pipeline_route(body: BuildBody) -> dict:
    return _queue(lambda: live.queue_build(body.model_dump()))


@app.post("/api/parsing/parse")
def parse_route(body: ParseBody) -> dict:
    return _queue(lambda: live.queue_parse(body.model_dump()))


@app.post("/api/pipelines/{pipeline_id}/learn")
def learn_route(pipeline_id: str) -> dict:
    return _queue(lambda: live.queue_learn(pipeline_id))


@app.post("/api/pipelines/{pipeline_id}/publish")
def publish_rule(pipeline_id: str, body: PublishBody) -> dict:
    if demo:
        return {"accepted": False, "message": "静态演示不执行发布或回滚。"}
    try:
        return live.publish(pipeline_id, body.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="记录不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/quality/profiles")
def quality_profiles() -> dict:
    return {"profiles": demo.quality_profiles() if demo else live.quality_profiles()}


@app.get("/api/quality/reports")
def quality_reports() -> dict:
    return {"reports": demo.quality_reports() if demo else live.quality_reports()}


@app.get("/api/quality/baselines")
def quality_baselines() -> dict:
    sources = demo.quality_baselines() if demo else live.quality_baselines()
    return {"sources": sources}


@app.get("/api/quality/baseline")
def quality_baseline(source_id: str = "", category: str = "", baseline: str = "", current: str = "") -> dict:
    if demo:
        return demo.quality_baseline(source_id, category, baseline, current)
    try:
        return live.quality_baseline(source_id, category, baseline, current)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/quality/baseline")
def set_quality_baseline(body: BaselineBody) -> dict:
    if demo:
        return demo.set_quality_baseline(body.source_id, body.category, body.snapshot_id)
    try:
        return live.set_quality_baseline(body.source_id, body.category, body.snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/quality/issues/{issue_id}")
def quality_issue(issue_id: str) -> dict:
    return _or_404(lambda: demo.quality_issue(issue_id) if demo else live.quality_issue(issue_id))


@app.post("/api/quality/profiles")
def init_profile(body: ProfileBody) -> dict:
    return _queue(lambda: live.queue_profile(body.model_dump()))


@app.post("/api/quality/analyze")
def analyze(body: AnalyzeBody) -> dict:
    return _queue(lambda: live.queue_analyze(body.model_dump()))


@app.post("/api/quality/issues/{issue_id}/diagnose")
def diagnose(issue_id: str) -> dict:
    return _queue(lambda: live.queue_diagnose(issue_id))


@app.get("/api/enrichment/records")
def enrichment_records(input: str = "") -> dict:
    return demo.enrichment_page() if demo else live.enrichment_page(input)


@app.get("/api/enrichment/investigations/{event_id}")
def investigation(event_id: str) -> dict:
    return _or_404(lambda: demo.investigation(event_id) if demo else live.investigation(event_id))


@app.get("/api/enrichment/knowledge")
def knowledge(path: str = "") -> dict:
    if demo:
        return demo.knowledge()
    try:
        return live.knowledge(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/enrichment/knowledge/{kind}")
def add_knowledge(kind: str, body: KnowledgeItemBody) -> dict:
    store = demo or live
    return _mutate(lambda: store.add_knowledge(kind, body.item, body.path))


@app.put("/api/enrichment/knowledge/{kind}")
def update_knowledge(kind: str, body: KnowledgeItemBody) -> dict:
    store = demo or live
    return _mutate(lambda: store.update_knowledge(kind, body.match, body.item, body.path))


@app.delete("/api/enrichment/knowledge/{kind}")
def delete_knowledge(kind: str, path: str = "", ip: str = "", indicator_type: str = "", value: str = "", source: str = "") -> dict:
    store = demo or live
    match = {"ip": ip, "indicator_type": indicator_type, "value": value, "source": source}
    return _mutate(lambda: store.delete_knowledge(kind, match, path))


@app.get("/api/enrichment/events")
def enrichment_events(input: str, limit: int = 50) -> dict:
    if demo:
        return {"count": 0, "events": []}
    try:
        return live.preview_events(input, limit=max(1, min(limit, 200)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/enrichment/event")
def enrich_one(body: EnrichOneBody) -> dict:
    return _queue(lambda: live.queue_one(body.model_dump()))


@app.post("/api/enrichment/batch")
def enrich_batch(body: EnrichBody) -> dict:
    return _queue(lambda: live.queue_batch(body.model_dump()))


@app.post("/api/enrichment/investigate")
def investigate_one(body: InvestigateBody) -> dict:
    return _queue(lambda: live.queue_investigate(body.model_dump()))


def _or_404(loader):
    try:
        return loader()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="记录不存在") from exc


def _mutate(loader):
    try:
        return loader()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="记录不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _queue(loader):
    if demo:
        raise HTTPException(status_code=400, detail="演示模式不执行真实智能体")
    try:
        return loader()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="记录不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
