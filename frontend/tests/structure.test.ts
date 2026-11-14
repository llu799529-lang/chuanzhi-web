/**
 * 前端结构约束：用测试锁住，而不是靠约定。
 *   1. 网络请求只从 lib/api.ts 发出；SSE 需要读流，useAgentStream 是唯一例外（但头部与错误解析仍来自 lib/api）。
 *   2. src/ 下的源码都要被引用到：没有入口能到达的文件，要么是死代码，要么是该放进 design-archive 的设计稿。
 *   3. 页面不直接读 localStorage 里的 token：登录态只经 stores/auth。
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = fileURLToPath(new URL("../src/", import.meta.url)).replace(/\\/g, "/");

function walk(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = `${dir}${dir.endsWith("/") ? "" : "/"}${name}`;
    if (statSync(p).isDirectory()) walk(p, acc);
    else acc.push(p);
  }
  return acc;
}

const files = walk(SRC);
const rel = (p: string) => p.slice(SRC.length).replace(/^\//, "");
const code = files.filter((p) => /\.(ts|vue)$/.test(p) && !p.endsWith(".d.ts"));
const text = (p: string) => readFileSync(p, "utf8");

describe("前端结构约束", () => {
  it("网络请求只从 lib/api.ts（与 SSE 专用的 useAgentStream）发出", () => {
    const allowed = new Set(["lib/api.ts", "composables/useAgentStream.ts"]);
    const offenders = code.filter((p) => !allowed.has(rel(p)) && /\bfetch\s*\(/.test(text(p))).map(rel);
    expect(offenders).toEqual([]);
  });

  it("useAgentStream 的请求头与错误解析来自 lib/api（不再自己拼 Authorization）", () => {
    const s = text(`${SRC}composables/useAgentStream.ts`);
    expect(s.includes("authHeaders()")).toBe(true);
    expect(s.includes("errorFromResponse")).toBe(true);
    expect(/Bearer \$\{/.test(s)).toBe(false);
  });

  it("src/ 下只有会被构建的源码与样式（设计稿放 design-archive/）", () => {
    const stray = files.filter((p) => !/\.(ts|vue|css)$/.test(p)).map(rel);
    expect(stray).toEqual([]);
  });

  it("每个模块都被别的文件引用到（main.ts 是入口，App.vue 由它挂载）", () => {
    const sources = code.map((p) => ({ p, s: text(p) }));
    const unused = code
      .filter((p) => !["main.ts", "env.d.ts"].includes(rel(p)))
      .filter((p) => {
        const stem = rel(p).replace(/\.(ts|vue)$/, "").replace(/\.vue$/, "");
        const needles = [`@/${stem}`, `/${stem.split("/").pop()}.vue`, `./${stem.split("/").pop()}`];
        return !sources.some(({ p: q, s }) => q !== p && needles.some((n) => s.includes(n)));
      })
      .map(rel);
    expect(unused).toEqual([]);
  });

  it("页面与组件不直接读写登录 token（只经 stores/auth）", () => {
    const offenders = code
      .filter((p) => !rel(p).startsWith("stores/"))
      .filter((p) => /localStorage\.(get|set|remove)Item\(\s*["'`]mt_token/.test(text(p)))
      .map(rel);
    expect(offenders).toEqual([]);
  });
});
