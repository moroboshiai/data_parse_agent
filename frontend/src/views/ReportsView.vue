<template>
  <div class="stack">
    <div class="page-card section-pad">
      <h1 class="page-title">发起分析</h1>
      <el-form inline :model="form">
        <el-form-item label="画像"><el-input v-model="form.profile" style="width: 280px" /></el-form-item>
        <el-form-item label="数据"><el-input v-model="form.input" style="width: 320px" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="running" @click="analyze">分析</el-button></el-form-item>
      </el-form>
    </div>
    <div class="metric-row">
      <div v-for="item in cards" :key="item.label" class="metric-card">
        <div class="metric-num">{{ item.value }}</div>
        <div class="metric-text">
          <div class="metric-label">{{ item.label }}</div>
          <div class="metric-hint">{{ item.hint }}</div>
        </div>
      </div>
    </div>
    <div class="page-card section-pad" v-for="report in reports" :key="report.report_id">
      <div class="toolbar">
        <div>
          <h1 class="page-title">{{ report.report_id }}</h1>
          <span class="pill" :class="pillClass(report.quality_status)">{{ labelOf(statusLabel, report.quality_status) }}</span>
          <span class="meta">{{ report.source_id }} · {{ report.window }} · {{ report.row_count }} 行</span>
        </div>
      </div>
      <p>{{ report.summary }}</p>
      <div class="links">
        <router-link v-for="id in report.issue_ids" :key="id" :to="`/quality/issues/${id}`">{{ id }}</router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { analyzeQuality, getReports, waitJob } from "../api/client";
import { labelOf, pillClass, statusLabel } from "../labels";

const reports = ref([]);
const running = ref(false);
const form = reactive({
  profile: "data/quality/profiles/company1_flow.json",
  input: "outputs/parsed/pipeline_company1_flow.jsonl",
});
const cards = computed(() => {
  const report = reports.value[0];
  if (!report) return [];
  return [
    { label: "样本行数", value: report.row_count, hint: report.window },
    { label: "问题数", value: report.issue_count, hint: report.category },
    { label: "状态", value: labelOf(statusLabel, report.quality_status), hint: report.source_id },
    { label: "报告", value: reports.value.length, hint: "示例报告份数" },
  ];
});
async function load() {
  reports.value = await getReports();
}

async function analyze() {
  running.value = true;
  try {
    const done = await waitJob(await analyzeQuality(form));
    ElMessage.success(`报告 ${done.result?.report_id || ""} 已生成`);
    await load();
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "分析失败");
  } finally {
    running.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.page-title { margin: 0 0 8px; }
.meta { margin-left: 8px; color: var(--muted); font-size: 13px; }
.links { display: flex; gap: 16px; }
.links a { color: var(--brand); }
</style>
