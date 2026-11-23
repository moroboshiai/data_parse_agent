export const stageLabel = {
  intake: "登记",
  register: "表注册",
  await_confirm: "等待确认",
  build_pipeline: "构建管道",
  parse: "解析",
  init_profile: "画像",
  quality_analyze: "质检",
  enrich: "富化",
  review: "复核",
  done: "完成",
};

export const statusLabel = {
  running: "进行中",
  awaiting_confirm: "待确认",
  review: "待复核",
  done: "已完成",
  blocked: "阻塞",
  pending_review: "待复核",
  pending_confirm: "待确认",
  confirmed: "已确认",
  active: "生效",
  human_review: "人工复核",
  warning: "关注",
  pass: "通过",
  needs_review: "待复核",
  auto_accepted: "已采纳",
  rejected: "已拒绝",
  investigation_required: "需要调查",
  not_required: "无需调查",
  high: "高",
  medium: "中",
  low: "低",
};

export function labelOf(map, value) {
  return map[value] || value || "-";
}

export function pillClass(value) {
  if (["confirmed", "done", "active", "pass", "auto_accepted", "not_required"].includes(value)) return "pill-green";
  if (["pending_review", "review", "human_review", "warning", "needs_review", "medium"].includes(value)) return "pill-orange";
  if (["blocked", "high", "rejected", "investigation_required"].includes(value)) return "pill-red";
  return "pill-pink";
}
