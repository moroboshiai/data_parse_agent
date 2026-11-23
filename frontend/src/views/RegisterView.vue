<template>
  <div class="page-card section-pad form-card">
    <h1 class="page-title">发起注册</h1>
    <p class="hint">提交后调用表注册智能体，完成后打开真实候选。该过程可能调用大模型。</p>
    <el-form label-width="120px" :model="form">
      <el-form-item label="样本"><el-input v-model="form.sample" /></el-form-item>
      <el-form-item label="规范表"><el-input v-model="form.standard" /></el-form-item>
      <el-form-item label="来源结构"><el-input v-model="form.schema" placeholder="可选" /></el-form-item>
      <el-form-item label="来源名称"><el-input v-model="form.sourceName" /></el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="running" @click="submit">开始注册</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { registerTable, waitJob } from "../api/client";

const router = useRouter();
const running = ref(false);
const form = reactive({
  sample: "data/source/company1/dns/dns_sample.csv",
  standard: "data/standard_schema/dns_schema.json",
  schema: "",
  sourceName: "company1_dns",
});

async function submit() {
  running.value = true;
  try {
    const done = await waitJob(await registerTable(form));
    const path = done.result?.candidate_path || "";
    const id = path.split(/[/\\]/).pop()?.replace(/\.json$/, "");
    ElMessage.success("注册完成");
    if (id) router.push(`/registration/candidates/${id}`);
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "注册失败");
  } finally {
    running.value = false;
  }
}
</script>

<style scoped>
.form-card { max-width: 760px; }
.hint { color: var(--muted); font-size: 13px; }
</style>
