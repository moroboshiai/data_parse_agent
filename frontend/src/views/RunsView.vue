<template>
  <div class="page-card section-pad">
    <div class="toolbar">
      <h1 class="page-title">任务列表</h1>
      <el-button type="primary" @click="$router.push('/governance/runs/new')">新建任务</el-button>
    </div>
    <el-table :data="rows" stripe>
      <el-table-column prop="run_id" label="运行编号" min-width="240">
        <template #default="{ row }">
          <router-link class="link" :to="`/governance/runs/${row.run_id}`">{{ row.run_id }}</router-link>
        </template>
      </el-table-column>
      <el-table-column prop="source_name" label="来源" width="160" />
      <el-table-column prop="category" label="规范类型" width="140" />
      <el-table-column label="阶段" width="120">
        <template #default="{ row }">{{ labelOf(stageLabel, row.stage) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }"><span class="pill" :class="pillClass(row.status)">{{ labelOf(statusLabel, row.status) }}</span></template>
      </el-table-column>
      <el-table-column label="阻塞" min-width="240">
        <template #default="{ row }">{{ (row.blockers || []).join("；") || "无" }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="danger" :disabled="Boolean(row.activity)" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { deleteRun, getRuns } from "../api/client";
import { labelOf, pillClass, stageLabel, statusLabel } from "../labels";

const rows = ref([]);

async function load() {
  rows.value = await getRuns();
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`只删除运行记录 ${row.run_id}。候选、Pipeline、解析结果等产物会保留。`, "删除运行记录", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await deleteRun(row.run_id);
    ElMessage.success("已删除运行记录");
    await load();
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "删除失败");
  }
}

onMounted(load);
</script>

<style scoped>
.link { color: var(--brand); }
.page-title { margin: 0; }
</style>
