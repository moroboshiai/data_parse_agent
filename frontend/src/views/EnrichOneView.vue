<template>
  <div class="stack">
    <div class="page-card section-pad">
      <h1 class="page-title">单条富化</h1>
      <p class="hint">从解析结果里选择一条事件。只富化这一条，并写入同一份富化记录。</p>
      <el-form inline>
        <el-form-item label="解析 JSONL"><el-input v-model="inputPath" style="width: 360px" /></el-form-item>
        <el-form-item label="知识目录"><el-input v-model="knowledge" style="width: 280px" /></el-form-item>
        <el-form-item><el-button :loading="loading" @click="load">读取事件</el-button></el-form-item>
      </el-form>
      <div class="pick">
        <span>序号</span>
        <el-input-number v-model="index" :min="1" :max="count || 1" />
        <el-button type="primary" :disabled="!count" :loading="running" @click="runIndex">富化该序号</el-button>
        <span v-if="count" class="hint">共 {{ count }} 条，列表展示前 {{ events.length }} 条</span>
      </div>
    </div>
    <div v-if="result" class="page-card section-pad">
      <h2 class="sub">{{ result.event_id }}</h2>
      <p class="meta">{{ typeText(result.event_type) }} · {{ result.timestamp || "无时间" }} · {{ result.src_ip || "无源地址" }} → {{ result.dst_ip || "无目的地址" }} · {{ result.domain || "无域名" }}</p>
      <p>事实：{{ factText(result) }}</p>
      <p>
        标签：
        <span v-for="item in appliedLabels(result)" :key="item.name" class="pill pill-red" :title="item.reason">{{ item.name }}</span>
        <span v-if="!appliedLabels(result).length">—</span>
      </p>
    </div>
    <div class="page-card section-pad">
      <el-table :data="events" stripe>
        <el-table-column prop="index" label="序号" width="70" />
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
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :disabled="running" @click="runRow(row)">富化</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { enrichOne, getEnrichEvents, waitJob } from "../api/client";

const typeLabel = { dns: "DNS", flow_log: "流量", parsed: "解析" };
const appliedStatuses = ["auto_accepted", "needs_review", "investigation_required"];
const inputPath = ref("outputs/parsed/pipeline_dns_test.jsonl");
const knowledge = ref("data/enrichment_knowledge");
const events = ref([]);
const count = ref(0);
const index = ref(1);
const loading = ref(false);
const running = ref(false);
const result = ref(null);

function typeText(value) {
  return typeLabel[value] || value || "—";
}

function appliedLabels(row) {
  return (row.labels || []).filter((item) => appliedStatuses.includes(item.status));
}

function factText(row) {
  return (row.facts || []).map((item) => item.name).join("、") || "—";
}

async function load() {
  loading.value = true;
  try {
    const data = await getEnrichEvents(inputPath.value);
    events.value = data.events || [];
    count.value = data.count || 0;
    if (!count.value) ElMessage.warning("这份解析结果里没有可富化的事件");
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "读取失败");
  } finally {
    loading.value = false;
  }
}

async function enrich(payload) {
  running.value = true;
  try {
    const done = await waitJob(await enrichOne({ input: inputPath.value, knowledge: knowledge.value, ...payload }));
    result.value = done.result || null;
    ElMessage.success("这条事件已富化");
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "富化失败");
  } finally {
    running.value = false;
  }
}

function runRow(row) {
  index.value = row.index;
  enrich({ event_id: row.event_id });
}

function runIndex() {
  enrich({ index: index.value });
}
</script>

<style scoped>
.hint { color: var(--muted); font-size: 13px; }
.pick { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.sub { margin: 0 0 8px; font-size: 15px; word-break: break-all; }
.meta { color: var(--muted); }
.pill { margin-right: 6px; }
</style>
