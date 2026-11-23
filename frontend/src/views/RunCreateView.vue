<template>
  <div class="page-card section-pad form-card">
    <h1 class="page-title">新建治理任务</h1>
    <p class="hint">登记后会自动开始表注册。映射阶段会调用大模型，可能需要数分钟。</p>
    <el-form label-width="120px" :model="form">
      <el-form-item label="来源名称" required>
        <el-input v-model="form.source_name" placeholder="company1_dns" />
      </el-form-item>
      <el-form-item label="样本路径" required>
        <el-input v-model="form.sample_path" />
      </el-form-item>
      <el-form-item label="规范表" required>
        <el-input v-model="form.standard_schema_path" />
      </el-form-item>
      <el-form-item label="解析输入">
        <el-input v-model="form.input_path" placeholder="默认同样本" />
      </el-form-item>
      <el-form-item label="知识目录">
        <el-input v-model="form.knowledge_path" placeholder="可空，默认使用 data/enrichment_knowledge" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="submit">登记任务</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { reactive } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { createRun } from "../api/client";

const router = useRouter();
const form = reactive({
  source_name: "company1_alarm",
  sample_path: "data/source/company1/alarm/alarm_sample.csv",
  standard_schema_path: "data/standard_schema/alarm_event_schema.json",
  input_path: "",
  knowledge_path: "",
});

async function submit() {
  try {
    const run = await createRun(form);
    ElMessage.success("已登记，正在开始表注册");
    router.push(`/governance/runs/${run.run_id}?autostart=1`);
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || "登记失败");
  }
}
</script>

<style scoped>
.form-card { max-width: 760px; }
.hint { color: var(--muted); font-size: 13px; }
</style>
