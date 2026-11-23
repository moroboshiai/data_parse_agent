<template>
  <div class="page-card section-pad">
    <h1 class="page-title">质量画像</h1>
    <p class="hint">从规范表生成画像并写入 data/quality/profiles。</p>
    <el-form inline>
      <el-form-item label="规范表"><el-input v-model="standard" style="width: 320px" /></el-form-item>
      <el-form-item label="来源标识"><el-input v-model="sourceId" style="width: 180px" /></el-form-item>
      <el-form-item><el-button type="primary" :loading="running" @click="create">生成画像</el-button></el-form-item>
    </el-form>
    <el-table :data="rows" stripe>
      <el-table-column prop="source_id" label="来源" width="180">
        <template #default="{ row }"><span class="pill pill-pink">{{ row.source_id }}</span></template>
      </el-table-column>
      <el-table-column prop="category" label="规则分类" width="140" />
      <el-table-column prop="time_field" label="时间字段" width="120" />
      <el-table-column prop="field_count" label="字段数" width="100" />
      <el-table-column prop="profile_path" label="画像路径" min-width="280" />
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getProfiles, initProfile, waitJob } from "../api/client";

const rows = ref([]);
const running = ref(false);
const standard = ref("data/standard_schema/dns_schema.json");
const sourceId = ref("company1_dns");

async function load() {
  rows.value = await getProfiles();
}

async function create() {
  running.value = true;
  try {
    const done = await waitJob(await initProfile({ standard: standard.value, source_id: sourceId.value }));
    ElMessage.success(`已写入 ${done.result?.field_count || 0} 个字段`);
    await load();
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "生成失败");
  } finally {
    running.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.hint { color: var(--muted); font-size: 13px; }
</style>
