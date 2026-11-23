<template>
  <div v-if="data" class="split">
    <div class="page-card section-pad">
      <div class="toolbar">
        <h1 class="page-title">资产</h1>
        <el-button type="primary" @click="open('assets')">新增</el-button>
      </div>
      <el-table :data="data.assets" stripe>
        <el-table-column prop="ip" label="地址" min-width="120" />
        <el-table-column prop="name" label="名称" min-width="100" />
        <el-table-column label="级别" width="80">
          <template #default="{ row }"><span class="pill" :class="row.importance === '重点' ? 'pill-red' : 'pill-pink'">{{ row.importance }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="open('assets', row)">编辑</el-button>
            <el-button link type="danger" @click="remove('assets', row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div class="page-card section-pad">
      <div class="toolbar">
        <h1 class="page-title">情报</h1>
        <el-button type="primary" @click="open('indicators')">新增</el-button>
      </div>
      <el-table :data="data.indicators" stripe>
        <el-table-column prop="indicator_type" label="类型" width="80" />
        <el-table-column prop="value" label="值" min-width="120" />
        <el-table-column prop="threat_status" label="判定" width="90" />
        <el-table-column prop="source" label="来源" min-width="110" />
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="open('indicators', row)">编辑</el-button>
            <el-button link type="danger" @click="remove('indicators', row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div class="page-card section-pad">
      <div class="toolbar">
        <h1 class="page-title">历史</h1>
        <el-button type="primary" @click="open('history')">新增</el-button>
      </div>
      <el-table :data="data.history" stripe>
        <el-table-column prop="indicator_type" label="类型" width="80" />
        <el-table-column prop="value" label="值" min-width="110" />
        <el-table-column prop="note" label="说明" min-width="120" />
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="open('history', row)">编辑</el-button>
            <el-button link type="danger" @click="remove('history', row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <el-dialog v-model="visible" :title="dialogTitle" width="520px" destroy-on-close>
      <el-form v-if="kind === 'assets'" label-width="90px" :model="form">
        <el-form-item label="地址"><el-input v-model="form.ip" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="级别">
          <el-select v-model="form.importance" style="width: 180px">
            <el-option label="重点" value="重点" />
            <el-option label="普通" value="普通" />
          </el-select>
        </el-form-item>
        <el-form-item label="说明"><el-input v-model="form.note" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <el-form v-else-if="kind === 'indicators'" label-width="90px" :model="form">
        <el-form-item label="类型">
          <el-select v-model="form.indicator_type" style="width: 180px">
            <el-option label="ip" value="ip" />
            <el-option label="domain" value="domain" />
          </el-select>
        </el-form-item>
        <el-form-item label="值"><el-input v-model="form.value" /></el-form-item>
        <el-form-item label="判定">
          <el-select v-model="form.threat_status" style="width: 180px">
            <el-option label="malicious" value="malicious" />
            <el-option label="suspicious" value="suspicious" />
            <el-option label="benign" value="benign" />
          </el-select>
        </el-form-item>
        <el-form-item label="置信度">
          <el-select v-model="form.confidence" style="width: 180px">
            <el-option label="high" value="high" />
            <el-option label="medium" value="medium" />
            <el-option label="low" value="low" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源"><el-input v-model="form.source" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="form.note" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <el-form v-else label-width="90px" :model="form">
        <el-form-item label="类型">
          <el-select v-model="form.indicator_type" style="width: 180px">
            <el-option label="ip" value="ip" />
            <el-option label="domain" value="domain" />
          </el-select>
        </el-form-item>
        <el-form-item label="值"><el-input v-model="form.value" /></el-form-item>
        <el-form-item label="频度">
          <el-select v-model="form.frequency" style="width: 180px">
            <el-option label="high" value="high" />
            <el-option label="medium" value="medium" />
            <el-option label="low" value="low" />
          </el-select>
        </el-form-item>
        <el-form-item label="说明"><el-input v-model="form.note" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { addKnowledge, deleteKnowledge, getKnowledge, updateKnowledge } from "../api/client";

const titles = { assets: "资产", indicators: "情报", history: "历史" };
const data = ref(null);
const visible = ref(false);
const saving = ref(false);
const kind = ref("assets");
const editing = ref(false);
const match = ref({});
const form = reactive({});
const dialogTitle = computed(() => `${editing.value ? "编辑" : "新增"}${titles[kind.value]}`);

function blank(target) {
  if (target === "assets") return { ip: "", name: "", importance: "普通", note: "" };
  if (target === "indicators") {
    return { indicator_type: "domain", value: "", threat_status: "suspicious", confidence: "medium", source: "osint_feed", note: "" };
  }
  return { indicator_type: "domain", value: "", frequency: "low", note: "" };
}

function assign(target) {
  Object.keys(form).forEach((key) => delete form[key]);
  Object.assign(form, target);
}

function identity(target, row) {
  if (target === "assets") return { ip: row.ip };
  if (target === "indicators") return { indicator_type: row.indicator_type, value: row.value, source: row.source };
  return { indicator_type: row.indicator_type, value: row.value };
}

function open(target, row) {
  kind.value = target;
  editing.value = Boolean(row);
  match.value = row ? identity(target, row) : {};
  assign(row ? { ...blank(target), ...row } : blank(target));
  visible.value = true;
}

async function load() {
  data.value = await getKnowledge();
}

async function save() {
  saving.value = true;
  try {
    if (editing.value) {
      await updateKnowledge(kind.value, { match: match.value, item: { ...form } });
    } else {
      await addKnowledge(kind.value, { item: { ...form } });
    }
    ElMessage.success("已保存");
    visible.value = false;
    await load();
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "保存失败");
  } finally {
    saving.value = false;
  }
}

async function remove(target, row) {
  try {
    await ElMessageBox.confirm(`从知识库删除这条${titles[target]}，后续富化不再使用它。`, "删除知识", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await deleteKnowledge(target, identity(target, row));
    ElMessage.success("已删除");
    await load();
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || "删除失败");
  }
}

onMounted(load);
</script>

<style scoped>
.split { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.page-title { margin: 0; }
</style>
