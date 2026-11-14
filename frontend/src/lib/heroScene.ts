/**
 * 落地页三维场景加载器
 *
 * three.min.js / OrbitControls.js / ambulance.js / hospital.js 都是原生脚本，**只注入一次**；
 * hospital.js 不再自己找画布并启动，而是提供 window.__mtMountHospitalScene(canvas, wrap)：
 * 每次进入落地页挂载一次，离开时调用它返回的清理函数（停渲染循环、断开观察器、释放 WebGL 上下文）。
 *
 * 以前的问题（实测反馈「退回主页那个东西消失」）：脚本只在第一次进入时执行，离开时又把渲染器释放了；
 * 从登录页返回首页，新的画布没有任何代码去渲染，三维场景就是空白。
 */
const BUST = "20261112"; // 两个场景脚本改过：带版本号，避免浏览器继续用缓存里的旧 hospital.js
const SCRIPTS = [
  "/assets/vendor/three/three.min.js",
  "/assets/vendor/three/OrbitControls.js",
  `/assets/vendor/three/ambulance.js?v=${BUST}`,
  `/assets/vendor/three/hospital.js?v=${BUST}`,
];

const cache = new Map<string, Promise<void>>();

function injectScript(src: string): Promise<void> {
  const hit = cache.get(src);
  if (hit) return hit;
  const p = new Promise<void>((resolve, reject) => {
    const el = document.createElement("script");
    el.src = src;
    el.async = false; // 保持文档顺序执行
    el.onload = () => resolve();
    el.onerror = () => {
      cache.delete(src); // 失败的不缓存：下次进入落地页还能重试
      reject(new Error(`脚本加载失败：${src}`));
    };
    document.head.appendChild(el);
  });
  cache.set(src, p);
  return p;
}

type MountFn = (canvas: HTMLCanvasElement, wrap: HTMLElement) => (() => void) | null;
interface SceneWindow {
  THREE?: { OrbitControls?: unknown };
  __mtMountHospitalScene?: MountFn;
}

let cleanup: (() => void) | null = null;
// 每次挂载 / 卸载加一：脚本还在加载时用户就离开了页面，加载完不再挂到已经不存在的画布上
let generation = 0;

function showFallback(): void {
  const fb = document.querySelector<HTMLElement>(".hero-scene-fallback");
  if (fb) fb.hidden = false;
}

/** 挂载三维场景：每次进入落地页调用一次 */
export async function mountHeroScene(): Promise<void> {
  unmountHeroScene();
  const mine = ++generation;
  const w = window as unknown as SceneWindow;
  try {
    for (const src of SCRIPTS) {
      if (src.includes("three.min.js") && w.THREE) continue;
      if (src.includes("OrbitControls") && w.THREE?.OrbitControls) continue;
      await injectScript(src);
    }
  } catch (err) {
    showFallback();
    console.warn("[landing] 三维场景加载失败：", err);
    return;
  }
  if (mine !== generation) return;
  const canvas = document.getElementById("sceneCanvas") as HTMLCanvasElement | null;
  const wrap = document.getElementById("heroScene");
  if (!canvas || !wrap || typeof w.__mtMountHospitalScene !== "function") {
    showFallback();
    return;
  }
  cleanup = w.__mtMountHospitalScene(canvas, wrap);
}

/** 路由离开时停止渲染、释放 WebGL 上下文（下次进入重新挂载） */
export function unmountHeroScene(): void {
  generation++;
  const fn = cleanup;
  cleanup = null;
  if (!fn) return;
  try {
    fn();
  } catch (e) {
    console.warn("[landing] 三维场景清理失败：", e);
  }
}
