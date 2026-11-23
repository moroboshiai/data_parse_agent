<template>
  <div class="stack">
    <div class="page-card section-pad">
      <div class="toolbar">
        <h1 class="page-title">批量富化</h1>
        <el-button @click="$router.push('/enrichment/one')">单条富化</el-button>
      </div>
      <el-form inline>
        <el-form-item label="解析 JSONL"><el-input v-model="inputPath" style="width: 320px" /></el-form-item>
        <el-form-item label="知识目录"><el-input v-model="knowledge" style="width: 280px" /></el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="running" @click="run">富化</el-button>
          <el-button :loading="running" @click="load">查看该输入</el-button>
        </el-form-item>
      </el-form>
    </div>
    <div class="metric-row">
      <div v-for="item in summaryCards" :key="item.label" class="metric-card">
        <div class="metric-num">{{ item.value }}</div>
        <div class="metric-text">
          <div class="metric-label">{{ item.label }}</div>
          <div class="metric-hint">{{ item.hint }}</div>
        </div>
      </div>
    </div>
    <div v-if="labelCards.length" class="metric-row">
      <div v-for="item in labelCards" :key="item.name" class="metric-card">
        <div class="metric-num">{{ item.count }}</div>
        <div class="metric-text">
          <div class="metric-label">{{ item.name }}</div>
          <div class="metric-hint">打了该标签的记录</div>
        </div>
      </div>
    </div>
    <div class="page-card section-pad">
      <h2 class="sub">富化记录</h2>
      <p class="hint">共 {{ summary.total || rows.length }} 条。{{ listHint }}</p>
      <el-table :data="rows" stripe>
      <el-table-column prop="event_id" label="事件" min-width="160">
        <template #default="{ row }">
          <router-link v-if="row.investigation_status === 'investigation_required'" class="link" :to="`/enrichment/investigations/${row.event_id}`">{{ row.event_id }}</router-link>
          <span v-else>{{ row.event_id }}</span>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="90">
        <template #default="{ row }">{{ typeText(row.event_type) }}</template>
      </el-table-column>
      <el-table-column label="时间" min-width="170">
        <template #default="{ row }">{{ row.timestamp || "—" }}</template>
      </el-table-column>
      <el-table-column label="源地址" min-width="140">
        <template #default="{ row }">{{ row.src_ip || "—" }}</template>
      </el-table-column>
      <el-table-column label="目的地址" min-width="140">
        <template #default="{ row }">{{ row.dst_ip || "—" }}</template>
      </el-table-column>
      <el-table-column label="域名" min-width="180">
        <template #default="{ row }">{{ row.domain || "—" }}</template>
      </el-table-column>
      <el-table-column label="智能化打标依据" min-width="180">
        <template #default="{ row }">{{ row.facts.map((item) => item.name).join("、") || "—" }}</template>
      </el-table-column>
      <el-table-column label="智能化标签" min-width="180">
        <template #default="{ row }">
          <span v-for="item in appliedLabels(row)" :key="item.name" class="pill pill-red" :title="item.reason">{{ item.name }}</span>
          <span v-if="!appliedLabels(row).length">—</span>
        </template>
      </el-table-column>
    </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { enrichBatch, getRecords, waitJob } from "../api/client";

const rows = ref([]);
const summary = ref({ total: 0, all_total: 0, labeled: 0, unlabeled: 0, investigation_required: 0, labels: [] });
const running = ref(false);
const appliedStatuses = ["auto_accepted", "needs_review", "investigation_required"];
const summaryCards = computed(() => [
  { label: "总计", value: summary.value.total ?? rows.value.length, hint: "当前输入对应的富化记录" },
  { label: "已打标签", value: summary.value.labeled ?? 0, hint: "至少有一个采纳标签" },
  { label: "未打标签", value: summary.value.unlabeled ?? 0, hint: "没有采纳中的风险标签" },
  { label: "需调查", value: summary.value.investigation_required ?? 0, hint: "需要进入调查的记录" },
]);
const labelCards = computed(() => summary.value.labels || []);
const listHint = computed(() => {
  const total = Number(summary.value.total || 0);
  const all = Number(summary.value.all_total || 0);
  const extra = all > total ? `仓库中另有 ${all - total} 条其他输入的历史结果未计入。` : "";
  if (total > rows.value.length) return `有标签的记录已置顶，其余按时间展示，当前 ${rows.value.length} 条。${extra}`;
  return extra || "有标签的记录已置顶。";
});

const typeLabel = { dns: "DNS", flow_log: "流量", parsed: "解析" };

function typeText(value) {
  return typeLabel[value] || value || "—";
}

function appliedLabels(row) {
  return (row.labels || []).filter((item) => appliedStatuses.includes(item.status));
}
const inputPath = ref("outputs/parsed/pipeline_company1_flow.jsonl");
const knowledge = ref("data/enrichment_knowledge");

async function load() {
  const data = await getRecords(inputPath.value);
  rows.value = data.records || [];
  summary.value = data.summary || { total: rows.value.length, all_total: rows.value.length, labeled: 0, unlabeled: 0, investigation_required: 0, labels: [] };
}

async function run() {
  running.value = true;
  try {
    const done = await waitJob(await enrichBatch({ input: inputPath.value, knowledge: knowledge.value }));
    ElMessage.success(`已写入 ${done.result?.count || 0} 条富化记录`);
    await load();
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "富化失败");
  } finally {
    running.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.link { color: var(--brand); }
.pill { margin-right: 6px; }
.page-title { margin: 0; }
.sub { margin: 0 0 8px; font-size: 15px; }
.hint { margin: 0 0 12px; color: var(--muted); }
</style>
