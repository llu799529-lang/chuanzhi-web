import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";

/**
 * Vitest 独立配置：与 vite.config.ts 共用同一个 alias 和插件，
 * 但不带 dev server 的 proxy（单测不该打真实后端）。
 *
 * environment 用 node 而不是 jsdom：
 * 现有可测单元是「纯函数 + fetch 契约」，不需要 DOM。
 * 引入 jsdom 会让 node_modules 多出 130+ 个包，收益不抵成本。
 * 真正需要 DOM 的验证交给 Playwright 端到端（跑真实浏览器，比 jsdom 更可信）。
 */
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
    globals: false,
  },
});
