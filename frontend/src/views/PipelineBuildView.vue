<template>
  <div class="stack">
    <div class="page-card section-pad form-card">
      <h1 class="page-title">构建与解析</h1>
      <p class="hint">构建会调用解析智能体并写入规则仓库。解析会按 Pipeline 生成 JSONL。</p>
      <el-form label-width="120px" :model="form">
        <el-form-item label="已确认候选"><el-input v-model="form.candidate" /></el-form-item>
        <el-form-item label="样本"><el-input v-model="form.sample" /></el-form-item>
        <el-form-item label="来源类型"><el-input v-model="form.source_type" /></el-form-item>
        <el-form-item label="解析输入"><el-input v-model="form.input" /></el-form-item>
        <el-form-item label="Pipeline">
          <el-select v-model="pipelineId" clearable placeholder="解析已有管道" style="width: 320px">
            <el-option v-for="item in pipelines" :key="item.pipeline_id" :label="item.pipeline_id" :value="item.pipeline_id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="running" @click="build">构建</el-button>
          <el-button :loading="running" @click="parse">解析</el-button>
        </el-form-item>
      </el-form>
    </div>
    <div v-if="preview" class="page-card section-pad">
      <h2 class="sub">解析预览</h2>
      <el-table :data="preview.rows" stripe>
        <el-table-column v-for="key in columns" :key="key" :prop="key" :label="key" min-width="140" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { buildPipeline, getPipelines, parsePipeline, waitJob } from "../api/client";

const router = useRouter();
const pipelines = ref([]);
const pipelineId = ref("");
const preview = ref(null);
const running = ref(false);
const form = reactive({
  candidate: "outputs/candidates/da4d966ffabf49a0a48010d305d6bc9a.json",
  sample: "data/source/company1/dns/dns_sample.csv",
  source_type: "dns_log",
  input: "data/source/company1/dns/dns.csv",
});
const columns = computed(() => Object.keys(preview.value?.rows?.[0] || {}));

async function build() {
  running.value = true;
  try {
    const done = await waitJob(await buildPipeline(form));
    ElMessage.success(`Pipeline ${done.result?.pipeline_id || ""} 已保存`);
    if (done.result?.pipeline_id) router.push(`/parsing/pipelines/${done.result.pipeline_id}`);
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "构建失败");
  } finally {
    running.value = false;
  }
}

async function parse() {
  if (!pipelineId.value) {
    ElMessage.warning("请选择要解析的 Pipeline");
    return;
  }
  running.value = true;
  try {
    const done = await waitJob(await parsePipeline({ pipeline_id: pipelineId.value, input: form.input }));
    ElMessage.success(`已写出 ${done.result?.rows || 0} 行，失败事件 ${done.result?.events || 0}`);
    router.push(`/parsing/pipelines/${pipelineId.value}`);
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "解析失败");
  } finally {
    running.value = false;
  }
}

onMounted(async () => {
  pipelines.value = await getPipelines();
  pipelineId.value = pipelines.value[0]?.pipeline_id || "";
});
</script>

<style scoped>
.form-card { max-width: 860px; }
.hint { color: var(--muted); font-size: 13px; }
.sub { margin: 0 0 12px; font-size: 15px; }
</style>
