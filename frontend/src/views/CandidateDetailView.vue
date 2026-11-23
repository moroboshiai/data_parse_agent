<template>
  <div v-if="item" class="stack">
    <div class="page-card section-pad">
      <div class="toolbar">
        <div>
          <h1 class="page-title">{{ item.candidate_id }}</h1>
          <span class="pill" :class="pillClass(item.status)">{{ labelOf(statusLabel, item.status) }}</span>
          <span class="meta">{{ item.source_name }} · {{ item.standard_schema_id }} · {{ item.mapping_mode }}</span>
        </div>
        <div class="actions">
          <el-button v-if="!editing" @click="startEdit">编辑</el-button>
          <template v-else>
            <el-button type="primary" :loading="saving" @click="save">保存</el-button>
            <el-button :disabled="saving" @click="cancelEdit">取消</el-button>
          </template>
          <el-button type="primary" :disabled="editing || item.status === 'confirmed' || item.status === 'failed'" :loading="running" @click="confirm">确认候选</el-button>
          <el-button type="danger" plain :disabled="editing || running" @click="remove">删除</el-button>
        </div>
      </div>
      <el-alert v-for="error in visibleErrors" :key="error" :title="error" type="error" show-icon :closable="false" />
    </div>
    <div class="metric-row">
      <div v-for="card in summaryCards" :key="card.label" class="metric-card">
        <div class="metric-num">{{ card.value }}</div>
        <div class="metric-text">
          <div class="metric-label">{{ card.label }}</div>
          <div class="metric-hint">{{ card.hint }}</div>
        </div>
      </div>
    </div>
    <div v-if="editing" class="stack">
      <div v-for="row in drafts" :key="row.index" class="page-card section-pad">
        <h2 class="sub">{{ row.source_field }} → {{ row.target_field }}</h2>
        <el-form label-width="100px">
          <el-form-item label="来源字段"><el-input v-model="row.source_field" /></el-form-item>
          <el-form-item label="规范字段"><el-input v-model="row.target_field" /></el-form-item>
        </el-form>
        <p v-if="!row.rules.length" class="hint">这条映射没有提取或清洗规则。</p>
        <div v-for="rule in row.rules" :key="rule.kind" class="rule-block">
          <h3 class="rule-title">{{ rule.kind === "extraction" ? "提取规则" : "清洗规则" }}</h3>
          <el-form label-width="100px">
            <el-form-item label="规则编号"><el-input v-model="rule.rule_id" /></el-form-item>
            <template v-if="rule.kind === 'extraction'">
              <el-form-item label="正则"><el-input v-model="rule.pattern" /></el-form-item>
              <el-form-item label="分组"><el-input-number v-model="rule.group" :min="0" /></el-form-item>
            </template>
            <template v-else>
              <el-form-item label="算子">
                <el-select v-model="rule.operator" style="width: 240px">
                  <el-option v-for="name in operators" :key="name" :label="name" :value="name" />
                </el-select>
              </el-form-item>
              <el-form-item label="输出格式"><el-input v-model="rule.output_format" /></el-form-item>
            </template>
            <el-form-item label="说明"><el-input v-model="rule.description" type="textarea" :rows="2" /></el-form-item>
          </el-form>
        </div>
      </div>
    </div>
    <div v-if="unmappedOverview.length" class="page-card section-pad">
      <h2 class="sub">未映射原因</h2>
      <p class="hint">共 {{ unmappedCount }} 个来源字段未进入规范映射，按智能体给出的原因归类。</p>
      <el-table :data="unmappedOverview" stripe>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="reason-list">
              <div v-for="detail in row.items" :key="detail.source_field" class="reason-item">
                <strong>{{ detail.source_field || "未命名字段" }}</strong>
                <p v-if="detail.evidence?.length">{{ detail.evidence.join("；") }}</p>
                <p v-else class="hint">没有补充证据。</p>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="count" label="字段数" width="90" />
        <el-table-column prop="reason" label="原因" min-width="320" class-name="wrap-cell" />
        <el-table-column label="来源字段" min-width="220" class-name="wrap-cell">
          <template #default="{ row }">{{ (row.fields || []).join("、") || "—" }}</template>
        </el-table-column>
      </el-table>
    </div>
    <el-alert
      v-else-if="unmappedCount > 0 && !editing"
      title="有未映射字段，但候选结果未记录具体原因。"
      type="info"
      show-icon
      :closable="false"
    />
    <div v-if="!editing" class="page-card section-pad">
      <h2 class="sub">字段映射</h2>
      <el-table :data="item.mappings" stripe :row-class-name="rowClass">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div v-if="row.rules?.length" class="rule-list">
              <div v-for="rule in row.rules" :key="rule.kind" class="rule-block">
                <h3 class="rule-title">{{ rule.kind === "extraction" ? "提取规则" : "清洗规则" }} {{ rule.rule_id }}</h3>
                <p v-if="rule.pattern">正则：{{ rule.pattern }}，分组 {{ rule.group ?? "—" }}</p>
                <p v-if="rule.operator">算子：{{ rule.operator }}</p>
                <p v-if="rule.output_format">输出格式：{{ rule.output_format }}</p>
                <p v-if="rule.input_formats?.length">输入格式：{{ rule.input_formats.join("、") }}</p>
                <p>{{ rule.description || "无说明" }}</p>
                <el-table v-if="rule.previews?.length" :data="rule.previews" size="small">
                  <el-table-column prop="input" label="输入" min-width="220" />
                  <el-table-column prop="output" label="输出" min-width="180" />
                </el-table>
              </div>
            </div>
            <p v-else class="hint">这条映射没有提取或清洗规则。</p>
          </template>
        </el-table-column>
        <el-table-column prop="source_field" label="来源字段" width="140" />
        <el-table-column prop="target_field" label="规范字段" width="160" />
        <el-table-column prop="confidence" label="置信度" width="90" />
        <el-table-column label="处理" width="90">
          <template #default="{ row }">
            {{ row.direct_mapping ? "直映" : row.needs_extraction ? "提取" : "清洗" }}
          </template>
        </el-table-column>
        <el-table-column label="规则" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ ruleText(row) }}</template>
        </el-table-column>
        <el-table-column label="试跑" width="90">
          <template #default="{ row }">
            <span class="pill" :class="row.validation_ok ? 'pill-green' : 'pill-red'">{{ row.validation_ok ? "通过" : "未通过" }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="test_message" label="智能体映射说明" min-width="220" class-name="wrap-cell" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { confirmCandidate, deleteCandidate, getCandidate, updateCandidate, waitJob } from "../api/client";
import { labelOf, pillClass, statusLabel } from "../labels";

const operators = ["trim", "normalize_datetime", "lower", "upper", "collapse_whitespace"];
const route = useRoute();
const router = useRouter();
const item = ref(null);
const drafts = ref([]);
const editing = ref(false);
const running = ref(false);
const saving = ref(false);
const unmappedOverview = computed(() => item.value?.unmapped_overview || []);
const unmappedCount = computed(() => {
  const documented = unmappedOverview.value.reduce((sum, row) => sum + Number(row.count || 0), 0);
  return Number(item.value?.unmapped_field_count || documented);
});
const visibleErrors = computed(() =>
  (item.value?.errors || []).filter((text) => !String(text || "").includes("需人工确认")),
);
const summaryCards = computed(() => {
  const row = item.value || {};
  const source = Number(row.source_field_count || 0);
  const mapped = Number(row.mapped_field_count || 0);
  const unmapped = unmappedCount.value;
  const errors = visibleErrors.value.length;
  return [
    { label: "来源表字段", value: source, hint: row.source_name || "样本表列数" },
    { label: "已完成映射", value: mapped, hint: source ? `${mapped} / ${source}` : "已给出规范字段" },
    { label: "未映射", value: unmapped, hint: unmappedOverview.value.length ? `${unmappedOverview.value.length} 类原因` : "来源字段尚未映射" },
    { label: "异常项", value: errors, hint: errors ? "映射或规则告警" : "无阻塞错误" },
  ];
});

function rowClass({ row }) {
  return row.validation_ok ? "" : "fail-row";
}

function ruleText(row) {
  const text = (row.rules || []).map((rule) => {
    const body = rule.pattern || [rule.operator, rule.output_format].filter(Boolean).join(" ");
    return [rule.rule_id, body].filter(Boolean).join(" · ");
  }).filter(Boolean);
  return text.join("；") || "—";
}

async function load() {
  item.value = await getCandidate(route.params.id);
  if (route.query.edit === "1") startEdit();
}

function startEdit() {
  drafts.value = item.value.mappings.map((row, index) => ({
    index,
    source_field: row.source_field,
    target_field: row.target_field,
    rules: (row.rules || []).map((rule) => ({ ...rule })),
  }));
  editing.value = true;
}

function cancelEdit() {
  editing.value = false;
  router.replace({ query: {} });
}

async function save() {
  saving.value = true;
  try {
    item.value = await updateCandidate(route.params.id, { mappings: drafts.value });
    editing.value = false;
    router.replace({ query: {} });
    ElMessage.success("候选映射已保存");
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "保存失败");
  } finally {
    saving.value = false;
  }
}

async function confirm() {
  running.value = true;
  try {
    await waitJob(await confirmCandidate(route.params.id));
    ElMessage.success("候选已确认并写入映射记忆");
    await load();
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "确认失败");
  } finally {
    running.value = false;
  }
}

async function remove() {
  try {
    await ElMessageBox.confirm(`只删除候选 ${item.value.candidate_id}。已写入的映射记忆，以及据此构建的 Pipeline 会保留。`, "删除候选映射", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await deleteCandidate(route.params.id);
    ElMessage.success("已删除候选映射");
    router.push("/registration/candidates");
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "删除失败");
  }
}

onMounted(load);
watch(() => route.query.edit, (value) => {
  if (value === "1" && item.value) startEdit();
});
</script>

<style scoped>
.page-title { margin: 0 0 8px; word-break: break-all; }
.meta { margin-left: 8px; color: var(--muted); font-size: 13px; }
.sub { margin: 0 0 12px; font-size: 15px; }
.hint { color: var(--muted); }
.reason-list { display: grid; gap: 12px; }
.reason-item p { margin: 6px 0 0; white-space: normal; overflow-wrap: anywhere; line-height: 1.6; }
.rule-list { display: grid; gap: 12px; }
.rule-block { margin-top: 8px; }
.rule-title { margin: 0 0 8px; font-size: 14px; }
.rule-block p { margin: 0 0 8px; white-space: normal; overflow-wrap: anywhere; line-height: 1.6; }
:deep(.el-table td.wrap-cell .cell) { white-space: normal; line-height: 1.6; overflow-wrap: anywhere; }
:deep(.fail-row) { background: #fff6f6 !important; }
</style>
