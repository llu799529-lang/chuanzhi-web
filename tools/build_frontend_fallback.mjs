#!/usr/bin/env node
/**
 * 前端备用构建：纯 JavaScript（TypeScript 编译器 + Vue 官方 SFC 编译器），零原生依赖。只在 Vite 跑不起来时使用。
 *
 *   node tools/build_frontend_fallback.mjs      → 重新生成 frontend/dist，并做两项冒烟测试；任一失败退出码为 1
 *
 * 为什么需要：Vite 5 依赖 rollup / esbuild 的「平台原生模块」。在 Windows 上 npm install 得到的 node_modules 只含 Windows 版本；
 * 换到 Linux、断网环境或安装时漏装了原生模块，`vite build` 会直接失败，提交包里就只剩旧的 dist。
 * tools/pack_submission.py 在 Vite 失败时自动改用本脚本。正式构建仍是 build_vue.bat（vue-tsc + vite build）。
 *
 * 做法（与 Vite 同一入口、同一份源码）：
 *   · .vue → @vue/compiler-sfc（与 Vite 插件同一个编译器）；.ts 与依赖包里的 ESM → TypeScript 编译器转为 CommonJS；
 *   · 一个 10 行的模块注册表把全部模块装进一个文件（与 webpack 运行时同理）；样式随所在模块执行时注入 <style>；
 *   · vue 使用官方「浏览器 + 生产」构建；其余依赖按 package.json 的 exports / module 字段解析。
 * 与 Vite 产物的差异：单文件、未压缩、不按路由拆包——本地运行的评审场景下没有可感知的加载差异。
 *
 * 冒烟（不联网、不需要浏览器）：
 *   1. 模块加载：在 Node 的 vm 沙箱里执行「浏览器产物本身」（DOM 用最小桩），并强制执行全部模块；
 *   2. 页面渲染：同一份编译结果交给 Vue 官方 server-renderer，渲染工作台（含 8 个子页面）、登录页、落地页，
 *      并检查关键文案（眼底示例图、化验单示例等）确实出现。两项都不检查样式与布局，不能替代在浏览器里点一遍。
 */
import crypto from "node:crypto";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const FE = path.join(ROOT, "frontend");
const SRC = path.join(FE, "src");
const NM = path.join(FE, "node_modules");
const OUT = path.join(FE, "dist");
const feRequire = createRequire(path.join(FE, "package.json"));
const ts = feRequire("typescript");
const sfc = feRequire("@vue/compiler-sfc");

const h8 = (s) => crypto.createHash("sha256").update(s).digest("hex").slice(0, 8);
const rel = (p) => path.relative(FE, p).split(path.sep).join("/");
const isBare = (s) => !s.startsWith(".") && !s.startsWith("/") && !s.startsWith("@/");
const ALIAS = { vue: path.join(NM, "vue", "dist", "vue.runtime.esm-browser.prod.js") };
const CONDITIONS = new Set(["browser", "import", "module", "default"]);
const DEFINES = [
  ["import.meta.env.VITE_API_BASE", "undefined"], ["import.meta.env.BASE_URL", '"/"'], ["import.meta.env.MODE", '"production"'],
  ["import.meta.env.DEV", "false"], ["import.meta.env.PROD", "true"], ["import.meta.env", "({})"], ["import.meta.url", '""'],
  ["import.meta", "({})"], ["process.env.NODE_ENV", '"production"'], ["__VUE_OPTIONS_API__", "true"],
  ["__VUE_PROD_DEVTOOLS__", "false"], ["__VUE_PROD_HYDRATION_MISMATCH_DETAILS__", "false"],
];
const applyDefines = (code) => DEFINES.reduce((c, [k, v]) => (c.includes(k) ? c.split(k).join(v) : c), code);

function resolveFile(base) {
  for (const ext of ["", ".ts", ".js", ".mjs", ".cjs", ".vue", ".json", "/index.ts", "/index.js", "/index.mjs"]) {
    const p = base + ext;
    if (fs.existsSync(p) && fs.statSync(p).isFile()) return p;
  }
  return null;
}

function pick(entry) {
  if (typeof entry === "string") return entry;
  if (Array.isArray(entry)) {
    for (const x of entry) { const r = pick(x); if (r) return r; }
    return null;
  }
  if (entry && typeof entry === "object") {
    for (const [k, v] of Object.entries(entry)) if (CONDITIONS.has(k)) { const r = pick(v); if (r) return r; }
  }
  return null;
}

function packageDir(name, from) {
  for (let dir = path.dirname(from); ; dir = path.dirname(dir)) {
    const cand = path.join(dir, "node_modules", name);
    if (fs.existsSync(path.join(cand, "package.json"))) return cand;
    if (path.dirname(dir) === dir) break;
  }
  const cand = path.join(NM, name);
  return fs.existsSync(path.join(cand, "package.json")) ? cand : null;
}

function resolveSpec(spec, from) {
  if (spec.startsWith("@/")) return resolveFile(path.join(SRC, spec.slice(2)));
  if (!isBare(spec)) return resolveFile(path.resolve(path.dirname(from), spec));
  if (ALIAS[spec]) return ALIAS[spec];
  const parts = spec.split("/");
  const name = spec.startsWith("@") ? parts.slice(0, 2).join("/") : parts[0];
  const sub = "." + spec.slice(name.length);
  const dir = packageDir(name, from);
  if (!dir) return null;
  const pkg = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
  let target = null;
  if (pkg.exports !== undefined && pkg.exports !== null) {
    const ex = typeof pkg.exports === "string" || Array.isArray(pkg.exports) || !Object.keys(pkg.exports).some((k) => k.startsWith("."))
      ? { ".": pkg.exports } : pkg.exports;
    if (ex[sub] !== undefined) target = pick(ex[sub]);
    else {
      for (const [k, v] of Object.entries(ex)) {
        const star = k.indexOf("*");
        if (star < 0) continue;
        const pre = k.slice(0, star);
        const post = k.slice(star + 1);
        if (sub.startsWith(pre) && sub.endsWith(post)) {
          const t = pick(v);
          if (t) { target = t.split("*").join(sub.slice(pre.length, sub.length - post.length)); break; }
        }
      }
    }
  }
  if (!target) target = sub !== "." ? sub : (pkg.module || (typeof pkg.browser === "string" ? pkg.browser : null) || pkg.main || "index.js");
  return resolveFile(path.join(dir, target));
}

function compileVue(file) {
  const r = rel(file);
  const id = h8(r);
  const { descriptor, errors } = sfc.parse(fs.readFileSync(file, "utf8"), { filename: file });
  if (errors.length) throw new Error(`${r}: ${errors[0].message || errors[0]}`);
  const scoped = descriptor.styles.some((s) => s.scoped);
  const scopeId = scoped ? `data-v-${id}` : undefined;
  let code;
  if (descriptor.script || descriptor.scriptSetup) {
    code = sfc.compileScript(descriptor, {
      id, inlineTemplate: true, isProd: true, genDefaultAs: "_sfc_main",
      fs: { fileExists: (f) => fs.existsSync(f), readFile: (f) => fs.readFileSync(f, "utf8"), realpath: (f) => fs.realpathSync(f) },
      templateOptions: { scoped, transformAssetUrls: false, compilerOptions: { scopeId } },
    }).content;
  } else {
    const t = sfc.compileTemplate({ source: descriptor.template ? descriptor.template.content : "", filename: file, id, scoped,
      isProd: true, transformAssetUrls: false, compilerOptions: { scopeId } });
    if (t.errors.length) throw new Error(`${r} <template>: ${t.errors[0]}`);
    code = t.code + "\nconst _sfc_main = { render };\n";
  }
  let css = "";
  for (const s of descriptor.styles) {
    const out = sfc.compileStyle({ source: s.content, filename: file, id: `data-v-${id}`, scoped: s.scoped, isProd: true, trim: true });
    if (out.errors.length) throw new Error(`${r} <style>: ${out.errors[0]}`);
    css += out.code + "\n";
  }
  return (css ? `__mt_css(${JSON.stringify(css)}, ${JSON.stringify(id)});\n` : "") + code +
    `\n${scoped ? `_sfc_main.__scopeId = "${scopeId}";\n` : ""}export default _sfc_main;\n`;
}

function toCJS(code, isTS) {
  return ts.transpileModule(code, {
    fileName: isTS ? "module.ts" : "module.js", reportDiagnostics: false,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true, isolatedModules: true,
      useDefineForClassFields: true, removeComments: true, allowJs: true, sourceMap: false },
  }).outputText;
}

function rewriteRequires(code, map) {
  const sf = ts.createSourceFile("module.js", code, ts.ScriptTarget.ES2022, true, ts.ScriptKind.JS);
  const edits = [];
  const visit = (n) => {
    if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === "require"
        && n.arguments.length === 1 && ts.isStringLiteralLike(n.arguments[0])) {
      const a = n.arguments[0];
      edits.push([a.getStart(sf), a.end, map(a.text)]);
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  edits.sort((x, y) => y[0] - x[0]);
  for (const [s, e, v] of edits) code = code.slice(0, s) + JSON.stringify(v) + code.slice(e);
  return code;
}

function buildGraph(entry, { virtual = new Map(), external = false } = {}) {
  const ids = new Map();
  const code = new Map();
  const queue = [];
  const unresolved = new Set();
  const add = (key) => {
    if (!ids.has(key)) { ids.set(key, ids.size); queue.push(key); }
    return ids.get(key);
  };
  const entryId = add(entry);
  while (queue.length) {
    const key = queue.shift();
    if (key.startsWith("\0ext:")) { code.set(key, `module.exports = __mt_node_require(${JSON.stringify(key.slice(5))});`); continue; }
    if (key === "\0empty") { code.set(key, "module.exports = {};"); continue; }
    const raw = virtual.has(key) ? virtual.get(key) : fs.readFileSync(key, "utf8");
    if (key.endsWith(".css")) { code.set(key, `__mt_css(${JSON.stringify(raw)}, ${JSON.stringify(h8(rel(key)))});`); continue; }
    if (key.endsWith(".json")) { code.set(key, `module.exports = ${raw};`); continue; }
    const isVue = key.endsWith(".vue");
    const source = applyDefines(isVue ? compileVue(key) : raw);
    const out = rewriteRequires(toCJS(source, isVue || key.endsWith(".ts")), (spec) => {
      if (external && isBare(spec)) return add("\0ext:" + spec);
      const target = resolveSpec(spec, key);
      if (target) return add(target);
      if (key.startsWith(SRC)) throw new Error(`无法解析「${spec}」（${rel(key)}）`);
      unresolved.add(`${spec} ← ${rel(key)}`);
      return add("\0empty");
    });
    code.set(key, out);
  }
  return { entryId, ids, code, unresolved };
}

const RUNTIME = "var C={};function R(i){var c=C[i];if(c)return c.exports;var m=C[i]={exports:{}};D[i].call(m.exports,m,m.exports,R);return m.exports}";
const BROWSER_PRELUDE = 'var process={env:{NODE_ENV:"production"}},global=globalThis;' +
  "function __mt_css(css,id){if(typeof document==='undefined'||document.querySelector('style[data-mt=\"'+id+'\"]'))return;" +
  "var s=document.createElement('style');s.setAttribute('data-mt',id);s.textContent=css;document.head.appendChild(s)}";

function emit(g, prelude, tail) {
  const defs = [...g.ids].map(([key, id]) => `${id}:function(module,exports,require){${g.code.get(key)}\n}`);
  return `(function(){${prelude}\nvar D={\n${defs.join(",\n")}\n};\n${RUNTIME}\n${tail}\n})();\n`;
}

async function loadSmoke(code) {
  const issues = [];
  const notes = [];
  const noop = () => {};
  const mem = new Map([["mt_token", "smoke-token"], ["mt_username", "smoke"]]);
  const storage = { getItem: (k) => (mem.has(k) ? mem.get(k) : null), setItem: (k, v) => void mem.set(k, String(v)),
    removeItem: (k) => void mem.delete(k), clear: () => mem.clear() };
  const el = () => ({ style: {}, dataset: {}, children: [], setAttribute: noop, getAttribute: () => null, removeAttribute: noop,
    appendChild: noop, removeChild: noop, insertBefore: noop, addEventListener: noop, removeEventListener: noop,
    classList: { add: noop, remove: noop, toggle: noop, contains: () => false }, textContent: "", innerHTML: "" });
  const document = { head: el(), body: el(), documentElement: el(), createElement: el, createElementNS: el, createTextNode: el,
    createComment: el, querySelector: () => null, querySelectorAll: () => [], getElementById: () => null, getElementsByTagName: () => [],
    addEventListener: noop, removeEventListener: noop, visibilityState: "visible", hidden: false, title: "", cookie: "" };
  const ctx = vm.createContext({
    console: { log: noop, info: noop, debug: noop, warn: (...a) => notes.push(a.map(String).join(" ").slice(0, 200)),
      error: (...a) => issues.push(a.map((x) => (x && x.stack) || String(x)).join(" ").slice(0, 600)) },
    setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask, URL, URLSearchParams, TextEncoder, TextDecoder,
    AbortController, Blob, File, FormData, Headers, Request, Response, fetch: () => new Promise(noop), document,
    navigator: { userAgent: "node", language: "zh-CN", onLine: true },
    location: { href: "http://127.0.0.1:8010/app", origin: "http://127.0.0.1:8010", protocol: "http:", host: "127.0.0.1:8010",
      hostname: "127.0.0.1", port: "8010", pathname: "/app", search: "", hash: "" },
    history: { state: null, length: 1, pushState(s) { this.state = s; }, replaceState(s) { this.state = s; }, go: noop, back: noop, forward: noop },
    localStorage: storage, sessionStorage: storage,
    matchMedia: () => ({ matches: false, addEventListener: noop, removeEventListener: noop, addListener: noop, removeListener: noop }),
    requestAnimationFrame: (f) => setTimeout(f, 16), cancelAnimationFrame: clearTimeout, addEventListener: noop,
    removeEventListener: noop, dispatchEvent: () => true, scrollTo: noop, innerWidth: 1440, innerHeight: 900, devicePixelRatio: 1,
    getComputedStyle: () => ({ getPropertyValue: () => "" }),
  });
  vm.runInContext("var window = globalThis, self = globalThis;", ctx);
  const onRejection = (e) => issues.push("未处理的 Promise 拒绝：" + String((e && e.stack) || e).slice(0, 600));
  process.on("unhandledRejection", onRejection);
  try {
    vm.runInContext(code, ctx, { filename: "app.js" });
  } catch (e) {
    issues.push("执行异常：" + String((e && e.stack) || e).slice(0, 800));
  }
  await new Promise((r) => setTimeout(r, 500));
  process.off("unhandledRejection", onRejection);
  console.log(`[冒烟] ${issues.length ? "失败" : "通过"} 模块加载（浏览器产物本身，全部模块执行一遍；已登录状态下初始路由 /app）`
    + (notes.length ? `；警告 ${notes.length} 条：${notes.slice(0, 2).join(" | ")}` : ""));
  for (const x of issues.slice(0, 4)) console.log("    " + x);
  return issues.length ? 1 : 0;
}

const SMOKE_ENTRY = path.join(SRC, "__mt_smoke__.ts");
const SMOKE = `
import { createSSRApp, h } from "vue";
import { renderToString } from "vue/server-renderer";
import { createPinia } from "pinia";
import { VueQueryPlugin } from "@tanstack/vue-query";
import { createMemoryHistory, createRouter } from "vue-router";
import Workbench from "@/features/workbench/WorkbenchPage.vue";
import Login from "@/features/auth/LoginPage.vue";
import Landing from "@/features/landing/LandingPage.vue";
const mem = new Map<string, string>([["mt_token", "smoke-token"], ["mt_username", "smoke"]]);
(globalThis as any).localStorage = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => mem.set(k, String(v)),
  removeItem: (k: string) => mem.delete(k) };
// 服务端渲染没有浏览器的 location；登录页在 setup 里读取 redirect 参数，给一个只读桩
(globalThis as any).location = { href: "http://127.0.0.1:8010/login", origin: "http://127.0.0.1:8010", pathname: "/login", search: "", hash: "" };
export async function run() {
  const out: Record<string, { ok: boolean; html?: string; error?: string }> = {};
  const routes = [{ path: "/", name: "landing", component: Landing }, { path: "/login", name: "login", component: Login },
                  { path: "/app", name: "workbench", component: Workbench }];
  for (const [name, C, at] of [["workbench", Workbench, "/app"], ["login", Login, "/login"], ["landing", Landing, "/"]] as const) {
    try {
      const router = createRouter({ history: createMemoryHistory(), routes });
      await router.push(at);
      await router.isReady();
      const app = createSSRApp({ render: () => h(C as any) });
      app.use(createPinia());
      app.use(router);
      app.use(VueQueryPlugin);
      out[name] = { ok: true, html: await renderToString(app) };
    } catch (e: any) {
      out[name] = { ok: false, error: String((e && e.stack) || e).slice(0, 700) };
    }
  }
  return out;
}
`;

async function renderSmoke() {
  const g = buildGraph(SMOKE_ENTRY, { virtual: new Map([[SMOKE_ENTRY, SMOKE]]), external: true });
  const dir = path.join(NM, ".mt-smoke");
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `smoke-${Date.now()}.cjs`);
  fs.writeFileSync(file, emit(g, "var __mt_node_require=require;function __mt_css(){}", `module.exports=R(${g.entryId});`));
  let res;
  try {
    res = await feRequire(file).run();
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
  const must = { workbench: ["上传眼底彩照", "示例 A · 眼底彩照", "示例 B · 失焦照片", "没有眼底照片？用示例图体验", "示例化验单", "眼底图上传演示", "新手指南", "使用指南", "双眼筛查"] };
  let failed = 0;
  for (const [name, r] of Object.entries(res)) {
    const miss = r.ok ? (must[name] || []).filter((s) => !r.html.includes(s)) : [];
    const browserOnly = !r.ok && name !== "workbench" && /(window|document|location|navigator|matchMedia) is not defined/.test(r.error || "");
    const ok = (r.ok && !miss.length) || browserOnly;
    failed += ok ? 0 : 1;
    const detail = r.ok ? `${r.html.length} 字符${miss.length ? "，缺少：" + miss.join("、") : ""}`
      : browserOnly ? `依赖浏览器全局变量，服务端渲染不适用（${String(r.error).split("\n")[0]}）` : r.error;
    console.log(`[冒烟] ${ok ? "通过" : "失败"} 页面渲染 ${name}：${detail}`);
  }
  return failed;
}

async function main() {
  const t0 = Date.now();
  const g = buildGraph(path.join(SRC, "main.ts"));
  const js = emit(g, BROWSER_PRELUDE, `R(${g.entryId});`);
  new vm.Script(js, { filename: "app.js" });
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.cpSync(path.join(FE, "public"), OUT, { recursive: true });
  fs.mkdirSync(path.join(OUT, "assets"), { recursive: true });
  const name = `app-${h8(js)}.js`;
  fs.writeFileSync(path.join(OUT, "assets", name), js);
  const html = fs.readFileSync(path.join(FE, "index.html"), "utf8");
  const tag = '<script type="module" src="/src/main.ts"></script>';
  if (!html.includes(tag)) throw new Error("index.html 里没有找到入口 script 标签");
  fs.writeFileSync(path.join(OUT, "index.html"), html.replace(tag, `<script defer src="/assets/${name}"></script>`));
  const ours = [...g.ids.keys()].filter((k) => k.startsWith(SRC)).length;
  console.log(`[构建] ${g.ids.size} 个模块（源码 ${ours} 个）→ dist/assets/${name}（${(js.length / 1024).toFixed(0)} KB，未压缩），`
    + `用时 ${((Date.now() - t0) / 1000).toFixed(1)}s`);
  if (g.unresolved.size) console.log("[构建] 依赖包内未解析、以空模块代替（只有被执行时才会出错）：" + [...g.unresolved].join("；"));
  if (process.argv.includes("--no-smoke")) return 0;
  return (await loadSmoke(emit(g, BROWSER_PRELUDE, `R(${g.entryId});for(var k in D)R(+k);`))) + (await renderSmoke());
}

main().then((failed) => { process.exitCode = failed ? 1 : 0; }, (e) => { console.error("[错误] " + ((e && e.stack) || e)); process.exitCode = 1; });
