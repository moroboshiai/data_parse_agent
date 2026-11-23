<template>
  <div v-if="payload" class="stack">
    <div class="page-card section-pad">
      <h1 class="page-title">{{ issue.title }}</h1>
      <span class="pill" :class="pillClass(issue.severity)">{{ labelOf(statusLabel, issue.severity) }}</span>
      <el-button class="gap" type="primary" :loading="running" @click="diagnose">诊断</el-button>
      <p v-if="issue.description">{{ issue.description }}</p>
      <el-descriptions class="gap" :column="2" border>
        <el-descriptions-item label="问题编号">{{ issue.issue_id }}</el-descriptions-item>
        <el-descriptions-item label="字段">{{ issue.field }}</el-descriptions-item>
        <el-descriptions-item label="维度">{{ issue.dimension }}</el-descriptions-item>
        <el-descriptions-item label="指标">{{ issue.metric }}</el-descriptions-item>
        <el-descriptions-item label="当前值">{{ issue.value }}</el-descriptions-item>
        <el-descriptions-item label="阈值">{{ issue.threshold }}</el-descriptions-item>
      </el-descriptions>
    </div>
    <div v-if="payload.diagnosis" class="page-card section-pad">
      <h2 class="sub">诊断</h2>
      <p>{{ payload.diagnosis.summary }}</p>
      <p><strong>已核实：</strong>{{ payload.diagnosis.verified.join("；") }}</p>
      <p><strong>未核实：</strong>{{ payload.diagnosis.unverified.join("；") }}</p>
      <h2 class="sub">治理任务</h2>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="任务">{{ payload.diagnosis.task.task_id }}</el-descriptions-item>
        <el-descriptions-item label="目标智能体">{{ payload.diagnosis.task.target_agent }}</el-descriptions-item>
        <el-descriptions-item label="说明">{{ payload.diagnosis.task.description }}</el-descriptions-item>
        <el-descriptions-item label="验证指标">{{ payload.diagnosis.task.verification_metrics.join("、") }}</el-descriptions-item>
      </el-descriptions>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import { diagnoseIssue, getIssue, waitJob } from "../api/client";
import { labelOf, pillClass, statusLabel } from "../labels";

const route = useRoute();
const payload = ref(null);
const running = ref(false);
const issue = computed(() => payload.value?.issue || {});
async function load() {
  payload.value = await getIssue(route.params.id);
}

async function diagnose() {
  running.value = true;
  try {
    await waitJob(await diagnoseIssue(route.params.id));
    ElMessage.success("诊断已写入");
    await load();
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "诊断失败");
  } finally {
    running.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.sub { margin: 0 0 12px; font-size: 15px; }
.gap { margin-top: 12px; }
</style>
