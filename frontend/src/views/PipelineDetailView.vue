<template>
  <div v-if="preview" class="stack">
    <div class="page-card section-pad">
      <div class="toolbar">
        <div>
          <h1 class="page-title">{{ preview.pipeline_id }}</h1>
          <span class="pill" :class="pillClass(preview.status)">{{ labelOf(statusLabel, preview.status) }}</span>
        </div>
        <div class="actions">
          <el-button :loading="running" @click="learn">根据失败事件学习</el-button>
          <el-button @click="$router.push('/parsing/publish')">发布与回滚</el-button>
          <el-button type="danger" plain :disabled="running" @click="remove">删除</el-button>
        </div>
      </div>
      <el-alert :title="preview.notice" type="warning" show-icon :closable="false" />
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
    <div class="page-card section-pad">
      <h2 class="sub">字段步骤</h2>
      <el-table :data="preview.field_steps" stripe>
        <el-table-column prop="source_field" label="源字段" />
        <el-table-column prop="field" label="规范字段" />
        <el-table-column prop="operator" label="算子" />
        <el-table-column prop="rule_id" label="规则" />
        <el-table-column prop="active_version" label="生效版本" width="110" />
        <el-table-column prop="canary_version" label="灰度版本" width="110" />
      </el-table>
    </div>
    <div class="page-card section-pad">
      <h2 class="sub">解析预览</h2>
      <el-alert v-if="preview.preview_notice" class="gap" :title="preview.preview_notice" type="warning" show-icon :closable="false" />
      <el-table :data="preview.rows" stripe>
        <el-table-column v-for="key in columns" :key="key" :label="key" min-width="140">
          <template #default="{ row }">{{ row[key] ?? "空" }}</template>
        </el-table-column>
      </el-table>
    </div>
    <div class="page-card section-pad">
      <h2 class="sub">失败事件</h2>
      <el-table :data="events" stripe>
        <el-table-column prop="event_id" label="事件" width="140" />
        <el-table-column prop="field" label="字段" width="120" />
        <el-table-column prop="operator" label="算子" width="160" />
        <el-table-column prop="message" label="说明" min-width="280" />
        <el-table-column prop="resolution" label="处理" width="120" />
      </el-table>
      <h2 class="sub gap">学习决策</h2>
      <el-table :data="preview.learn_decisions" stripe>
        <el-table-column prop="event_id" label="事件" width="140" />
        <el-table-column prop="action" label="动作" width="120" />
        <el-table-column prop="summary" label="说明" min-width="320" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { deletePipeline, getPipelineEvents, getPipelinePreview, learnPipeline, waitJob } from "../api/client";
import { labelOf, pillClass, statusLabel } from "../labels";

const route = useRoute();
const router = useRouter();
const preview = ref(null);
const events = ref([]);
const running = ref(false);
const columns = computed(() => Object.keys(preview.value?.rows?.[0] || {}));
const summaryCards = computed(() => {
  const row = preview.value || {};
  const source = Number(row.source_field_count || 0);
  const mapped = Number(row.mapped_field_count || 0);
  const unmapped = Number(row.unmapped_field_count || 0);
  return [
    { label: "来源表字段", value: source, hint: row.source_name || "来源表列数" },
    { label: "已完成映射", value: mapped, hint: source ? `${mapped} / ${source}` : "已进入管道的源字段" },
    { label: "未映射", value: unmapped, hint: "来源字段尚未进入管道" },
    { label: "失败事件", value: events.value.length || Number(row.event_count || 0), hint: "解析失败待学习" },
  ];
});

async function load() {
  const id = route.params.id;
  preview.value = await getPipelinePreview(id);
  events.value = (await getPipelineEvents(id)).events;
}

async function learn() {
  running.value = true;
  try {
    const done = await waitJob(await learnPipeline(route.params.id));
    ElMessage.success(`学习完成，决策 ${done.result?.decisions?.length || 0} 条。新版本需人工发布。`);
    await load();
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "学习失败");
  } finally {
    running.value = false;
  }
}

async function remove() {
  try {
    await ElMessageBox.confirm(`只从规则仓库移除 Pipeline ${preview.value.pipeline_id}。规则、失败事件和解析结果文件会保留。`, "删除 Pipeline", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await deletePipeline(route.params.id);
    ElMessage.success("已删除 Pipeline");
    router.push("/parsing/pipelines");
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "删除失败");
  }
}

onMounted(load);
</script>

<style scoped>
.page-title { margin: 0 0 8px; }
.sub { margin: 0 0 12px; font-size: 15px; }
.gap { margin-top: 16px; }
</style>
