import { createApp } from "vue";
import { createPinia } from "pinia";
import { VueQueryPlugin } from "@tanstack/vue-query";
import App from "./App.vue";
import { router } from "./router";
import { setUnauthorizedHandler } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";
import "./styles/global.css";

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.use(VueQueryPlugin);

// 登录过期（任何业务接口 401）：清掉本地登录态，带上当前地址跳登录页，登录后回到原处。
setUnauthorizedHandler(() => {
  useAuthStore().clear();
  const cur = router.currentRoute.value;
  if (cur.name !== "login") void router.push({ name: "login", query: { redirect: cur.fullPath } });
});

app.mount("#app");
