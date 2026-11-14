import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "@/stores/auth";

export const router = createRouter({
  history: createWebHistory(),
  // 换页回到顶部：以前从落地页中部点「登录」，登录页停在半截；从登录页回首页也不在顶部
  scrollBehavior(to, _from, saved) {
    if (saved) return saved;
    if (to.hash) return { el: to.hash, behavior: "smooth" };
    return { top: 0 };
  },
  routes: [
    {
      path: "/",
      name: "landing",
      component: () => import("@/features/landing/LandingPage.vue"),
    },
    {
      path: "/login",
      name: "login",
      component: () => import("@/features/auth/LoginPage.vue"),
    },
    {
      path: "/app",
      name: "workbench",
      component: () => import("@/features/workbench/WorkbenchPage.vue"),
    },
  ],
});

router.beforeEach((to) => {
  const auth = useAuthStore();
  if (to.name === "workbench" && !auth.loggedIn) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.name === "login" && auth.loggedIn) {
    return { name: "workbench" };
  }
});
