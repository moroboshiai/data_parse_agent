import axios from "axios";

const http = axios.create({ baseURL: "/api", timeout: 30000 });

export function getMeta() {
  return http.get("/meta").then((res) => res.data);
}

export function getJob(id) {
  return http.get(`/jobs/${id}`).then((res) => res.data);
}

export async function waitJob(job) {
  let current = job;
  while (current.status === "running") {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    current = await getJob(current.job_id);
  }
  if (current.status === "failed") {
    throw new Error(current.error || "任务失败");
  }
  return current;
}

export function getDashboard() {
  return http.get("/dashboard").then((res) => res.data);
}

export function getRuns() {
  return http.get("/runs").then((res) => res.data.runs);
}

export function getRun(id) {
  return http.get(`/runs/${id}`).then((res) => res.data);
}

export function createRun(payload) {
  return http.post("/runs", payload).then((res) => res.data);
}

export function confirmRun(id) {
  return http.post(`/runs/${id}/confirm`).then((res) => res.data);
}

export function resumeRun(id) {
  return http.post(`/runs/${id}/resume`).then((res) => res.data);
}

export function stepRun(id) {
  return http.post(`/runs/${id}/step`).then((res) => res.data);
}

export function deleteRun(id) {
  return http.delete(`/runs/${id}`).then((res) => res.data);
}

export function registerTable(payload) {
  return http.post("/registration", payload).then((res) => res.data);
}

export function confirmCandidate(id) {
  return http.post(`/candidates/${id}/confirm`).then((res) => res.data);
}

export function deleteCandidate(id) {
  return http.delete(`/candidates/${id}`).then((res) => res.data);
}

export function buildPipeline(payload) {
  return http.post("/parsing/build", payload).then((res) => res.data);
}

export function parsePipeline(payload) {
  return http.post("/parsing/parse", payload).then((res) => res.data);
}

export function learnPipeline(id) {
  return http.post(`/pipelines/${id}/learn`).then((res) => res.data);
}

export function deletePipeline(id) {
  return http.delete(`/pipelines/${id}`).then((res) => res.data);
}

export function initProfile(payload) {
  return http.post("/quality/profiles", payload).then((res) => res.data);
}

export function analyzeQuality(payload) {
  return http.post("/quality/analyze", payload).then((res) => res.data);
}

export function diagnoseIssue(id) {
  return http.post(`/quality/issues/${id}/diagnose`).then((res) => res.data);
}

export function enrichOne(payload) {
  return http.post("/enrichment/event", payload).then((res) => res.data);
}

export function getEnrichEvents(input) {
  return http.get("/enrichment/events", { params: { input } }).then((res) => res.data);
}

export function enrichBatch(payload) {
  return http.post("/enrichment/batch", payload).then((res) => res.data);
}

export function getCandidates() {
  return http.get("/candidates").then((res) => res.data.candidates);
}

export function getCandidate(id) {
  return http.get(`/candidates/${id}`).then((res) => res.data);
}

export function updateCandidate(id, payload) {
  return http.put(`/candidates/${id}`, payload).then((res) => res.data);
}

export function getPipelines() {
  return http.get("/pipelines").then((res) => res.data.pipelines);
}

export function getPipelinePreview(id) {
  return http.get(`/pipelines/${id}/preview`).then((res) => res.data);
}

export function getPipelineEvents(id) {
  return http.get(`/pipelines/${id}/events`).then((res) => res.data);
}

export function submitPublish(id, payload) {
  return http.post(`/pipelines/${id}/publish`, payload).then((res) => res.data);
}

export function getProfiles() {
  return http.get("/quality/profiles").then((res) => res.data.profiles);
}

export function getReports() {
  return http.get("/quality/reports").then((res) => res.data.reports);
}

export function getBaselines() {
  return http.get("/quality/baselines").then((res) => res.data.sources);
}

export function getBaseline(params) {
  return http.get("/quality/baseline", { params }).then((res) => res.data);
}

export function setBaseline(payload) {
  return http.post("/quality/baseline", payload).then((res) => res.data);
}

export function getIssue(id) {
  return http.get(`/quality/issues/${id}`).then((res) => res.data);
}

export function getRecords(input) {
  return http.get("/enrichment/records", { params: input ? { input } : {} }).then((res) => res.data);
}

export function getInvestigation(id) {
  return http.get(`/enrichment/investigations/${id}`).then((res) => res.data);
}

export function getKnowledge(path) {
  return http.get("/enrichment/knowledge", { params: path ? { path } : {} }).then((res) => res.data);
}

export function addKnowledge(kind, payload) {
  return http.post(`/enrichment/knowledge/${kind}`, payload).then((res) => res.data);
}

export function updateKnowledge(kind, payload) {
  return http.put(`/enrichment/knowledge/${kind}`, payload).then((res) => res.data);
}

export function deleteKnowledge(kind, params) {
  return http.delete(`/enrichment/knowledge/${kind}`, { params }).then((res) => res.data);
}
