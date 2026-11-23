<template>
  <div>
    <h1 class="page-title">工作台</h1>
    <div class="metric-row">
      <div v-for="item in metrics" :key="item.key" class="metric-card">
        <div class="metric-num">{{ item.value }}</div>
        <div class="metric-text">
          <div class="metric-label">{{ item.label }}</div>
          <div class="metric-hint">{{ item.hint }}</div>
        </div>
      </div>
    </div>
    <div class="page-card section-pad">
      <div class="toolbar">
        <strong>最近运行</strong>
        <el-button type="primary" @click="$router.push('/governance/runs/new')">新建治理任务</el-button>
      </div>
      <el-table :data="runs" stripe>
        <el-table-column prop="run_id" label="运行编号" min-width="220">
          <template #default="{ row }">
            <router-link class="link" :to="`/governance/runs/${row.run_id}`">{{ row.run_id }}</router-link>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="160">
          <template #default="{ row }"><span class="pill pill-pink">{{ row.source_name }}</span></template>
        </el-table-column>
        <el-table-column label="类型" width="120">
          <template #default="{ row }"><span class="pill pill-orange">{{ row.category }}</span></template>
        </el-table-column>
        <el-table-column label="阶段" width="120">
          <template #default="{ row }">{{ labelOf(stageLabel, row.stage) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }"><span class="pill" :class="pillClass(row.status)">{{ labelOf(statusLabel, row.status) }}</span></template>
        </el-table-column>
        <el-table-column label="阻塞" min-width="220">
          <template #default="{ row }">{{ (row.blockers || []).join("；") || "无" }}</template>
        </el-table-column>
      </el-table>
      <p class="stages">阶段顺序：{{ stages.map((item) => labelOf(stageLabel, item)).join(" → ") }}</p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { getDashboard } from "../api/client";
import { labelOf, pillClass, stageLabel, statusLabel } from "../labels";

const metrics = ref([]);
const runs = ref([]);
const stages = ref([]);

onMounted(async () => {
  const data = await getDashboard();
  metrics.value = data.metrics;
  runs.value = data.runs;
  stages.value = data.stages;
});
</script>

<style scoped>
.link { color: var(--brand); }
.stages { margin: 12px 0 0; color: var(--muted); font-size: 12px; }
</style>
