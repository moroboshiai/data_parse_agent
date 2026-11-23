<template>
  <div class="page-card section-pad">
    <div class="toolbar">
      <h1 class="page-title">候选映射</h1>
      <el-button type="primary" @click="$router.push('/registration/new')">发起注册</el-button>
    </div>
    <el-table :data="rows" stripe>
      <el-table-column label="候选" min-width="280">
        <template #default="{ row }">
          <router-link class="link" :to="`/registration/candidates/${row.candidate_id}`">{{ row.candidate_id }}</router-link>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="160">
        <template #default="{ row }"><span class="pill pill-pink">{{ row.source_name }}</span></template>
      </el-table-column>
      <el-table-column prop="standard_schema_id" label="规范类型" width="120" />
      <el-table-column prop="mapping_mode" label="映射方式" width="120" />
      <el-table-column label="字段映射" width="120">
        <template #default="{ row }">{{ row.mapped_field_count ?? row.mapping_count ?? 0 }} / {{ row.source_field_count ?? row.mapping_count ?? 0 }}</template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }"><span class="pill" :class="pillClass(row.status)">{{ labelOf(statusLabel, row.status) }}</span></template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link @click="$router.push(`/registration/candidates/${row.candidate_id}?edit=1`)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { deleteCandidate, getCandidates } from "../api/client";
import { labelOf, pillClass, statusLabel } from "../labels";

const rows = ref([]);

async function load() {
  rows.value = await getCandidates();
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`只删除候选 ${row.candidate_id}。已写入的映射记忆，以及据此构建的 Pipeline 会保留。`, "删除候选映射", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await deleteCandidate(row.candidate_id);
    ElMessage.success("已删除候选映射");
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
