import { createRouter, createWebHistory } from "vue-router";
import AppLayout from "../layouts/AppLayout.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      component: AppLayout,
      children: [
        { path: "", name: "dashboard", component: () => import("../views/DashboardView.vue") },
        { path: "governance/runs", component: () => import("../views/RunsView.vue") },
        { path: "governance/runs/new", component: () => import("../views/RunCreateView.vue") },
        { path: "governance/runs/:id", component: () => import("../views/RunDetailView.vue") },
        { path: "registration/candidates", component: () => import("../views/CandidatesView.vue") },
        { path: "registration/new", component: () => import("../views/RegisterView.vue") },
        { path: "registration/candidates/:id", component: () => import("../views/CandidateDetailView.vue") },
        { path: "parsing/pipelines", component: () => import("../views/PipelinesView.vue") },
        { path: "parsing/build", component: () => import("../views/PipelineBuildView.vue") },
        { path: "parsing/publish", component: () => import("../views/PublishView.vue") },
        { path: "parsing/pipelines/:id", component: () => import("../views/PipelineDetailView.vue") },
        { path: "quality/reports", component: () => import("../views/ReportsView.vue") },
        { path: "quality/profiles", component: () => import("../views/ProfilesView.vue") },
        { path: "quality/baseline", component: () => import("../views/BaselineView.vue") },
        { path: "quality/issues/:id", component: () => import("../views/IssueDetailView.vue") },
        { path: "enrichment/one", component: () => import("../views/EnrichOneView.vue") },
        { path: "enrichment/records", component: () => import("../views/RecordsView.vue") },
        { path: "enrichment/investigations/:id", component: () => import("../views/InvestigationView.vue") },
        { path: "enrichment/knowledge", component: () => import("../views/KnowledgeView.vue") },
      ],
    },
  ],
});

export default router;
