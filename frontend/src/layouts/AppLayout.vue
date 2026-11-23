<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <span class="logo">治</span>
        <span>数据治理智能体</span>
      </div>
      <nav class="topnav">
        <router-link v-for="item in topNav" :key="item.key" :to="item.path" :class="{ active: module === item.key }">
          {{ item.title }}
        </router-link>
      </nav>
      <div class="top-side">{{ mode === "live" ? "真实接入" : "静态演示" }}</div>
    </header>
    <div class="body">
      <aside class="sider">
        <div class="sider-title">{{ sideTitle }}</div>
        <router-link v-for="item in sideNav" :key="item.path" :to="item.path" class="side-link" :class="{ active: isSideActive(item.path) }">
          {{ item.title }}
        </router-link>
      </aside>
      <main class="main">
        <el-alert class="demo-alert" :title="banner" :type="mode === 'live' ? 'success' : 'info'" show-icon :closable="false" />
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { getMeta } from "../api/client";

const topNav = [
  { key: "dashboard", title: "工作台", path: "/" },
  { key: "governance", title: "治理主控", path: "/governance/runs" },
  { key: "registration", title: "表结构注册", path: "/registration/candidates" },
  { key: "parsing", title: "数据解析", path: "/parsing/pipelines" },
  { key: "quality", title: "数据质检", path: "/quality/reports" },
  { key: "enrichment", title: "数据富化", path: "/enrichment/records" },
];

const menus = {
  dashboard: { title: "工作台", items: [{ title: "总览", path: "/" }] },
  governance: {
    title: "治理主控",
    items: [
      { title: "任务列表", path: "/governance/runs" },
      { title: "新建任务", path: "/governance/runs/new" },
    ],
  },
  registration: {
    title: "表结构注册",
    items: [
      { title: "候选列表", path: "/registration/candidates" },
      { title: "发起注册", path: "/registration/new" },
    ],
  },
  parsing: {
    title: "数据解析",
    items: [
      { title: "Pipeline", path: "/parsing/pipelines" },
      { title: "构建与解析", path: "/parsing/build" },
      { title: "发布与回滚", path: "/parsing/publish" },
    ],
  },
  quality: {
    title: "数据质检",
    items: [
      { title: "质量报告", path: "/quality/reports" },
      { title: "质量画像", path: "/quality/profiles" },
      { title: "基线对比", path: "/quality/baseline" },
    ],
  },
  enrichment: {
    title: "数据富化",
    items: [
      { title: "单条富化", path: "/enrichment/one" },
      { title: "批量结果", path: "/enrichment/records" },
      { title: "知识库", path: "/enrichment/knowledge" },
    ],
  },
};

const route = useRoute();
const mode = ref("live");
const banner = computed(() =>
  mode.value === "live"
    ? "已连接仓库中的智能体。确认、注册、解析、质检和富化会读写真实产物，并可能调用大模型。"
    : "当前为静态演示，操作不会调用智能体。"
);
onMounted(async () => {
  try {
    mode.value = (await getMeta()).mode || "live";
  } catch {
    mode.value = "live";
  }
});
const module = computed(() => {
  const path = route.path;
  if (path.startsWith("/governance")) return "governance";
  if (path.startsWith("/registration")) return "registration";
  if (path.startsWith("/parsing")) return "parsing";
  if (path.startsWith("/quality")) return "quality";
  if (path.startsWith("/enrichment")) return "enrichment";
  return "dashboard";
});
const sideNav = computed(() => menus[module.value].items);
const sideTitle = computed(() => menus[module.value].title);

function isSideActive(path) {
  if (path === "/") return route.path === "/";
  if (path === "/governance/runs") return route.path === path || /^\/governance\/runs\/(?!new$).+/.test(route.path);
  if (path === "/registration/candidates") return route.path === path || /^\/registration\/candidates\/.+/.test(route.path);
  if (path === "/parsing/pipelines") return route.path === path || /^\/parsing\/pipelines\/.+/.test(route.path);
  return route.path === path;
}
</script>

<style scoped>
.shell { min-height: 100%; display: flex; flex-direction: column; }
.topbar {
  height: 48px;
  display: flex;
  align-items: center;
  padding: 0 16px;
  background: var(--brand);
  color: #fff;
}
.brand { display: flex; align-items: center; gap: 8px; width: 210px; font-weight: 600; }
.logo {
  width: 22px; height: 22px; border-radius: 2px; background: #fff; color: var(--brand);
  display: grid; place-items: center; font-size: 13px; font-weight: 700;
}
.topnav { display: flex; gap: 4px; flex: 1; }
.topnav a { color: #fff; padding: 6px 12px; border-radius: 2px; font-size: 14px; }
.topnav a.active, .topnav a:hover { background: rgba(0, 0, 0, 0.16); }
.top-side { font-size: 12px; opacity: 0.9; }
.body { display: flex; min-width: 0; min-height: calc(100vh - 48px); }
.sider { flex: 0 0 210px; width: 210px; background: #fff; border-right: 1px solid var(--line); padding: 12px 0; }
.sider-title { padding: 4px 16px 10px; color: #606266; font-size: 13px; white-space: nowrap; }
.side-link { display: block; padding: 10px 16px; color: #303133; font-size: 14px; white-space: nowrap; }
.side-link.active { background: var(--brand-soft); color: var(--brand); border-right: 3px solid var(--brand); }
.main { flex: 1; min-width: 0; padding: 16px; overflow: auto; }
.demo-alert { margin-bottom: 12px; }
</style>
