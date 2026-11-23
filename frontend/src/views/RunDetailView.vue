<template>
  <div v-if="run" class="stack">
    <div class="page-card section-pad">
      <div class="toolbar">
        <div>
          <h1 class="page-title">{{ run.run_id }}</h1>
          <span class="pill" :class="pillClass(run.status)">{{ labelOf(statusLabel, run.status) }}</span>
        </div>
        <div class="actions">
          <el-button :loading="running" @click="step">执行一步</el-button>
          <el-button :disabled="run.stage !== 'await_confirm'" :loading="running" type="primary" @click="confirm">确认候选</el-button>
          <el-button :disabled="run.stage !== 'review'" :loading="running" @click="resume">继续</el-button>
          <el-button type="danger" plain :disabled="running || Boolean(run.activity)" @click="remove">删除</el-button>
        </div>
      </div>
      <el-alert v-if="run.activity || running" class="gap" :title="run.activity || '正在执行当前阶段，请稍候'" type="info" show-icon :closable="false" />
      <el-steps :active="active" finish-status="success" align-center>
        <el-step v-for="item in stageKeys" :key="item" :title="labelOf(stageLabel, item)" />
      </el-steps>
      <el-alert v-if="run.blockers?.length" class="gap" :title="run.blockers.join('；')" type="warning" show-icon :closable="false" />
    </div>
    <div class="page-card section-pad">
      <h2 class="sub">产物路径</h2>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="样本">{{ run.sample_path }}</el-descriptions-item>
        <el-descriptions-item label="规范表">{{ run.standard_schema_path }}</el-descriptions-item>
        <el-descriptions-item label="候选">{{ run.candidate_path || "—" }}</el-descriptions-item>
        <el-descriptions-item label="Pipeline">{{ run.pipeline_id || "—" }}</el-descriptions-item>
        <el-descriptions-item label="解析结果">{{ run.parsed_path || "—" }}</el-descriptions-item>
        <el-descriptions-item label="画像">{{ run.profile_path || "—" }}</el-descriptions-item>
        <el-descriptions-item label="知识目录">{{ run.knowledge_path || "未提供" }}</el-descriptions-item>
      </el-descriptions>
    </div>
    <div class="page-card section-pad">
      <h2 class="sub">过程记录</h2>
      <el-timeline>
        <el-timeline-item v-for="(item, index) in run.history" :key="index" :timestamp="labelOf(stageLabel, item.stage)">
          {{ item.action }} · {{ item.detail }}
        </el-timeline-item>
      </el-timeline>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { confirmRun, deleteRun, getRun, resumeRun, stepRun, waitJob } from "../api/client";
import { labelOf, pillClass, stageLabel, statusLabel } from "../labels";

const route = useRoute();
const router = useRouter();
const run = ref(null);
const running = ref(false);
let timer = 0;
const stageKeys = ["intake", "register", "await_confirm", "build_pipeline", "parse", "init_profile", "quality_analyze", "enrich", "review", "done"];
const active = computed(() => Math.max(stageKeys.indexOf(run.value?.stage), 0));

async function load() {
  run.value = await getRun(route.params.id);
}

function watchProgress() {
  window.clearInterval(timer);
  timer = window.setInterval(load, 2000);
}

async function follow(request, doneText) {
  running.value = true;
  watchProgress();
  try {
    const accepted = await request();
    if (accepted.job_id) await waitJob(accepted);
    ElMessage.success(doneText);
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "执行失败");
  } finally {
    window.clearInterval(timer);
    running.value = false;
    await load();
  }
}

function step() {
  return follow(() => stepRun(route.params.id), "已执行一个阶段");
}

function confirm() {
  return follow(() => confirmRun(route.params.id), "确认后的阶段已执行");
}

function resume() {
  return follow(() => resumeRun(route.params.id), "已从当前阶段继续");
}

async function remove() {
  try {
    await ElMessageBox.confirm(`只删除运行记录 ${run.value.run_id}。候选、Pipeline、解析结果等产物会保留。`, "删除运行记录", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await deleteRun(route.params.id);
    ElMessage.success("已删除运行记录");
    router.push("/governance/runs");
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "删除失败");
  }
}

onMounted(async () => {
  await load();
  if (run.value?.stage === "intake" && (route.query.autostart === "1" || run.value.status === "running")) {
    step();
  }
});
onUnmounted(() => window.clearInterval(timer));
</script>

<style scoped>
.page-title { margin: 0 0 8px; }
.actions { display: flex; gap: 8px; }
.gap { margin-top: 16px; }
.sub { margin: 0 0 12px; font-size: 15px; }
</style>
