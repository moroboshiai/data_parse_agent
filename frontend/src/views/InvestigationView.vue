<template>
  <div v-if="item" class="stack">
    <div class="page-card section-pad">
      <h1 class="page-title">{{ item.event_id }}</h1>
      <span class="pill" :class="pillClass(item.investigation_status)">{{ labelOf(statusLabel, item.investigation_status) }}</span>
      <p>{{ item.recommendation }}</p>
    </div>
    <div class="split">
      <div class="page-card section-pad">
        <h2 class="sub">事实</h2>
        <el-table :data="item.facts" stripe>
          <el-table-column prop="name" label="名称" width="120" />
          <el-table-column prop="value" label="取值" />
        </el-table>
      </div>
      <div class="page-card section-pad">
        <h2 class="sub">标签</h2>
        <el-table :data="item.labels" stripe>
          <el-table-column prop="name" label="名称" />
          <el-table-column label="状态">
            <template #default="{ row }"><span class="pill pill-red">{{ labelOf(statusLabel, row.status) }}</span></template>
          </el-table-column>
        </el-table>
      </div>
    </div>
    <div class="page-card section-pad">
      <h2 class="sub">查询过程</h2>
      <el-table :data="item.decisions" stripe>
        <el-table-column prop="round" label="轮次" width="80" />
        <el-table-column prop="tool" label="工具" width="160" />
        <el-table-column prop="detail" label="结果" />
      </el-table>
      <p class="missing">缺失证据：{{ item.missing_evidence.join("；") }}</p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { getInvestigation } from "../api/client";
import { labelOf, pillClass, statusLabel } from "../labels";

const route = useRoute();
const item = ref(null);
onMounted(async () => { item.value = await getInvestigation(route.params.id); });
</script>

<style scoped>
.sub { margin: 0 0 12px; font-size: 15px; }
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.missing { color: var(--muted); font-size: 13px; }
</style>
