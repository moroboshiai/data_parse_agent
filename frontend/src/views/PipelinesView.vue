<template>
  <div class="page-card section-pad">
    <div class="toolbar">
      <h1 class="page-title">Pipeline</h1>
      <el-button type="primary" @click="$router.push('/parsing/build')">构建与解析</el-button>
    </div>
    <el-table :data="rows" stripe>
      <el-table-column label="Pipeline" min-width="220">
        <template #default="{ row }">
          <router-link class="link" :to="`/parsing/pipelines/${row.pipeline_id}`">{{ row.pipeline_id }}</router-link>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="160">
        <template #default="{ row }"><span class="pill pill-pink">{{ row.source_name }}</span></template>
      </el-table-column>
      <el-table-column prop="source_type" label="类型" width="120" />
      <el-table-column label="字段映射" width="120">
        <template #default="{ row }">{{ row.mapped_field_count ?? row.step_count ?? 0 }} / {{ row.source_field_count ?? row.step_count ?? 0 }}</template>
      </el-table-column>
      <el-table-column prop="event_count" label="失败事件" width="100" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }"><span class="pill" :class="pillClass(row.status)">{{ labelOf(statusLabel, row.status) }}</span></template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { deletePipeline, getPipelines } from "../api/client";
import { labelOf, pillClass, statusLabel } from "../labels";

const rows = ref([]);

async function load() {
  rows.value = await getPipelines();
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`只从规则仓库移除 Pipeline ${row.pipeline_id}。规则、失败事件和解析结果文件会保留。`, "删除 Pipeline", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await deletePipeline(row.pipeline_id);
    ElMessage.success("已删除 Pipeline");
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
