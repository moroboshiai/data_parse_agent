<template>
  <div class="page-card section-pad form-card">
    <h1 class="page-title">发布与回滚</h1>
    <p class="hint">发布和回滚会直接改规则仓库的生效版本。只有灰度版本可以发布。</p>
    <el-form label-width="120px" :model="form">
      <el-form-item label="Pipeline">
        <el-select v-model="form.pipeline_id" style="width: 320px">
          <el-option v-for="item in pipelines" :key="item.pipeline_id" :label="item.pipeline_id" :value="item.pipeline_id" />
        </el-select>
      </el-form-item>
      <el-form-item label="规则 ID"><el-input v-model="form.rule_id" /></el-form-item>
      <el-form-item label="版本"><el-input-number v-model="form.version" :min="1" /></el-form-item>
      <el-form-item label="动作">
        <el-radio-group v-model="form.action">
          <el-radio value="publish">发布</el-radio>
          <el-radio value="rollback">回滚</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="submit">提交</el-button>
      </el-form-item>
    </el-form>
    <el-alert v-if="message" :title="message" type="warning" show-icon :closable="false" />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { getPipelines, submitPublish } from "../api/client";

const pipelines = ref([]);
const message = ref("");
const form = reactive({ pipeline_id: "", rule_id: "rule_time", version: 2, action: "publish" });

async function submit() {
  try {
    const result = await submitPublish(form.pipeline_id, form);
    message.value = result.message || `生效版本已切换为 ${result.active_version}`;
  } catch (error) {
    message.value = error.response?.data?.detail || error.message || "未执行";
  }
}

onMounted(async () => {
  pipelines.value = await getPipelines();
  form.pipeline_id = pipelines.value[0]?.pipeline_id || "";
});
</script>

<style scoped>
.form-card { max-width: 760px; }
.hint { color: var(--muted); font-size: 13px; }
</style>
