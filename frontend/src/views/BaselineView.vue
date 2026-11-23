<template>
  <div class="stack">
    <div class="page-card section-pad">
      <h1 class="page-title">基线对比</h1>
      <p class="hint">选择来源、基线和当前窗口后对比指标。将当前设为基线会写入正式基线文件，不重跑质检。表中百分比都是异常占比，不是质检通过率，数值越高说明问题越多。</p>
      <el-form inline>
        <el-form-item label="来源">
          <el-select v-model="sourceKey" placeholder="选择来源" style="width: 240px" @change="onSourceChange">
            <el-option v-for="item in sources" :key="item.source_id" :label="sourceLabel(item)" :value="item.source_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="基线">
          <el-select v-model="baselineId" placeholder="选择基线" style="width: 280px">
            <el-option v-for="item in snapshots" :key="item.id" :label="snapshotLabel(item)" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="当前">
          <el-select v-model="currentId" placeholder="选择当前窗口" style="width: 280px">
            <el-option v-for="item in reports" :key="item.id" :label="snapshotLabel(item)" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="compare">对比</el-button>
          <el-button :disabled="!currentId || currentId === 'saved'" :loading="saving" @click="promote">将当前设为基线</el-button>
        </el-form-item>
      </el-form>
    </div>
    <div class="page-card section-pad">
      <p v-if="result" class="hint">{{ result.source_id }} / {{ result.category }} · 基线体量 {{ result.baseline_volume ?? result.volume }} · 当前体量 {{ result.volume }} · {{ result.updated_at || "无时间" }}</p>
      <el-alert v-if="result?.notice" class="gap" :title="result.notice" type="warning" show-icon :closable="false" />
      <el-empty v-if="!result?.comparisons?.length" :description="emptyText" />
      <el-table v-else :data="result.comparisons" stripe>
        <el-table-column label="指标" min-width="260">
          <template #default="{ row }">
            <div class="metric-name" :title="row.metric">{{ metricTitle(row.metric) }}</div>
            <div class="metric-desc">{{ metricMeaning(row.metric) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="基线" width="140">
          <template #default="{ row }">{{ formatValue(row.baseline, row.metric) }}</template>
        </el-table-column>
        <el-table-column label="当前" width="140">
          <template #default="{ row }">{{ formatValue(row.current, row.metric) }}</template>
        </el-table-column>
        <el-table-column label="变化" width="180">
          <template #default="{ row }">
            <span :class="changed(row.delta) ? 'up' : ''">{{ formatDelta(row) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getBaseline, getBaselines, setBaseline } from "../api/client";

const sources = ref([]);
const sourceKey = ref("");
const baselineId = ref("");
const currentId = ref("");
const result = ref(null);
const loading = ref(false);
const saving = ref(false);

const selected = computed(() => sources.value.find((item) => item.source_id === sourceKey.value) || null);
const snapshots = computed(() => selected.value?.snapshots || []);
const reports = computed(() => snapshots.value.filter((item) => item.kind === "report"));
const emptyText = computed(() => result.value?.notice || "暂无数据");

function sourceLabel(item) {
  return item.category && item.category !== item.source_id ? `${item.source_id} / ${item.category}` : item.source_id;
}

function snapshotLabel(item) {
  const volume = item.volume != null ? ` · ${item.volume} 行` : "";
  const time = item.updated_at ? ` · ${item.updated_at}` : "";
  return `${item.label || item.id}${volume}${time}`;
}

function defaultBaseline(list) {
  const saved = list.find((item) => item.kind === "baseline");
  if (saved) return saved.id;
  const reportList = list.filter((item) => item.kind === "report");
  return reportList[0]?.id || "";
}

function defaultCurrent(list, baseline) {
  const reportList = list.filter((item) => item.kind === "report");
  if (!reportList.length) return "";
  const latest = reportList[reportList.length - 1];
  if (latest.id === baseline && reportList.length > 1) return reportList[reportList.length - 2].id;
  return latest.id === baseline ? "" : latest.id;
}

function onSourceChange() {
  const list = snapshots.value;
  baselineId.value = defaultBaseline(list);
  currentId.value = defaultCurrent(list, baselineId.value);
  result.value = null;
}

const fieldNames = {
  src_ip: "源IP",
  dst_ip: "目的IP",
  dns_server_ip: "DNS服务器IP",
  domain: "域名",
  time: "时间",
  dns_query_type: "查询类型",
  dns_res_code: "响应码",
  dns_ansr_type: "应答类型",
  dns_a: "A记录",
  dns_aaaa: "AAAA记录",
  dns_aa: "权威应答",
  dns_rd: "递归标志",
  dns_repeat_count: "重复次数",
  dns_req_len: "请求长度",
  dns_res_len: "响应长度",
  dns_ttl: "TTL",
  src_port: "源端口",
  dst_port: "目的端口",
  proto_4: "四层协议",
  proto_7: "七层协议",
};

function fieldLabel(field) {
  return fieldNames[field] || field || "";
}

function metricInfo(metric) {
  if (metric === "volume") {
    return { title: "样本行数", meaning: "窗口内记录数，不是比率" };
  }
  if (metric === "duplicate_rate") {
    return { title: "重复记录率", meaning: "异常占比，越高说明重复越多" };
  }
  const [kind, field] = String(metric || "").split(":");
  const name = fieldLabel(field);
  if (kind === "field_null_rate") {
    return { title: `${name}空值率`, meaning: "异常占比，越高说明空值越多" };
  }
  if (kind === "field_invalid_rate") {
    return { title: `${name}格式无效率`, meaning: "异常占比，越高说明格式错误越多" };
  }
  if (kind === "field_unknown_enum_rate") {
    return { title: `${name}未知枚举率`, meaning: "异常占比，越高说明取值不在枚举内越多" };
  }
  if (kind === "time_parse_fail_rate") {
    return { title: "时间解析失败率", meaning: "异常占比，越高说明时间无法解析越多" };
  }
  if (String(metric).includes("rate")) {
    return { title: metric, meaning: "异常占比，不是质检通过率" };
  }
  return { title: metric, meaning: "" };
}

function metricTitle(metric) {
  return metricInfo(metric).title;
}

function metricMeaning(metric) {
  return metricInfo(metric).meaning;
}

function isRate(metric) {
  return typeof metric === "string" && metric.includes("rate");
}

function formatPercent(value) {
  return `${(value * 100).toFixed(2)}%`;
}

function formatValue(value, metric) {
  if (value == null || value === "") return "—";
  if (typeof value !== "number") return String(value);
  if (isRate(metric)) return formatPercent(value);
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(2);
}

function formatDelta(row) {
  if (row.delta == null) return "—";
  const formatted = formatValue(row.delta, row.metric);
  if (formatted === "—") return "—";
  return row.delta > 0 ? `+${formatted}` : formatted;
}

function changed(delta) {
  return typeof delta === "number" && Math.abs(delta) > 0.05;
}

async function compare() {
  if (baselineId.value && currentId.value && baselineId.value === currentId.value) {
    ElMessage.warning("请选择与当前不同的基线");
    result.value = { notice: "请选择与当前不同的基线", comparisons: [] };
    return;
  }
  loading.value = true;
  try {
    result.value = await getBaseline({
      source_id: sourceKey.value,
      category: selected.value?.category || "",
      baseline: baselineId.value,
      current: currentId.value,
    });
    if (result.value?.baseline_id) baselineId.value = result.value.baseline_id;
    if (result.value?.current_id) currentId.value = result.value.current_id;
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "对比失败");
  } finally {
    loading.value = false;
  }
}

async function promote() {
  if (!currentId.value || currentId.value === "saved") {
    ElMessage.warning("请选择一份质量报告作为基线");
    return;
  }
  saving.value = true;
  try {
    await setBaseline({
      source_id: sourceKey.value,
      category: selected.value?.category || "",
      snapshot_id: currentId.value,
    });
    ElMessage.success("已将当前窗口设为正式基线");
    await loadSources();
    baselineId.value = "saved";
    await compare();
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "设置失败");
  } finally {
    saving.value = false;
  }
}

async function loadSources() {
  sources.value = await getBaselines();
  if (!sourceKey.value) {
    const first =
      sources.value.find((item) => (item.snapshots || []).filter((row) => row.kind === "report").length >= 2) ||
      sources.value.find((item) => item.snapshots?.length) ||
      sources.value[0];
    sourceKey.value = first?.source_id || "";
    onSourceChange();
  } else {
    const current = selected.value;
    if (current && !snapshots.value.some((item) => item.id === baselineId.value)) {
      baselineId.value = defaultBaseline(snapshots.value);
    }
    if (current && !reports.value.some((item) => item.id === currentId.value)) {
      currentId.value = defaultCurrent(snapshots.value, baselineId.value);
    }
  }
}

onMounted(async () => {
  await loadSources();
  if (sourceKey.value) await compare();
});
</script>

<style scoped>
.hint { color: var(--muted); font-size: 13px; }
.gap { margin: 0 0 12px; }
.up { color: var(--brand); font-weight: 700; }
.metric-name { font-weight: 600; }
.metric-desc { margin-top: 4px; color: var(--muted); font-size: 12px; }
</style>
