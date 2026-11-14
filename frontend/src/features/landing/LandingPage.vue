<script setup lang="ts">
/**
 * 落地页 · 1:1 迁移自 frontend/index.html
 * 视觉零改动：DOM 结构、类名、文案、SVG 全部照搬；
 * 只把 a[href] 换成 router-link / 锚点，交互改为 Composition API。
 */
import { onBeforeUnmount, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { mountHeroScene, unmountHeroScene } from "@/lib/heroScene";
import "@/styles/landing.css";

// 工作台截图用 BASE_URL 自适应：
// 原生页通过相对路径 assets/... 取图，所以在根路径和 /_legacy/ 下都能显示；
// Vue 版写在根路径 / 下，硬编码 "/assets/..." 一旦部署到子路径就会破图，
// 同时也能避开 SPA 兜底把 404 图片替换成 index.html 的问题。
const ASSET_BASE = import.meta.env.BASE_URL;

const auth = useAuthStore();
const shot = ref<"workbench" | "triage">("workbench");
const root = ref<HTMLElement | null>(null);

let io: IntersectionObserver | null = null;

function pickShot(v: "workbench" | "triage") {
  shot.value = v;
}

onMounted(() => {
  document.body.classList.add("landing");

  // 滚动揭示（与原页面同一套阈值/边距）
  const els = root.value?.querySelectorAll<HTMLElement>(".reveal, .stagger");
  if (!els || !els.length || !("IntersectionObserver" in window)) {
    els?.forEach((e) => e.classList.add("in"));
  } else {
    io = new IntersectionObserver(
      (entries) => {
        entries.forEach((en) => {
          if (en.isIntersecting) {
            en.target.classList.add("in");
            io?.unobserve(en.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -60px 0px" },
    );
    els.forEach((e) => io?.observe(e));
  }

  // 三维场景必须在 DOM 就绪后加载
  void mountHeroScene();
});

onBeforeUnmount(() => {
  io?.disconnect();
  io = null;
  unmountHeroScene();
  document.body.classList.remove("landing");
});
</script>

<template>
  <div ref="root" class="mt-landing">
    <a class="skip" href="#main" hidden>跳到主要内容</a>

    <!-- ============ 导航：顶栏 ============ -->
    <header class="nav">
      <div class="nav-inner">
        <RouterLink class="wordmark" to="/" aria-label="MedTriage 首页">
          <svg class="wordmark-logo" viewBox="20 26 127 127" width="40" height="40" aria-hidden="true">
            <defs>
              <linearGradient id="wlg-deep" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#0a2440" /><stop offset="18%" stop-color="#1a4a76" />
                <stop offset="36%" stop-color="#4f8ec2" /><stop offset="48%" stop-color="#dbeefd" />
                <stop offset="56%" stop-color="#3f7cb0" /><stop offset="76%" stop-color="#14395c" />
                <stop offset="100%" stop-color="#0c2844" />
              </linearGradient>
              <linearGradient id="wlg-card" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#0a2440" /><stop offset="18%" stop-color="#1a4a76" />
                <stop offset="36%" stop-color="#4f8ec2" /><stop offset="48%" stop-color="#7fa8cc" />
                <stop offset="56%" stop-color="#3f7cb0" /><stop offset="76%" stop-color="#14395c" />
                <stop offset="100%" stop-color="#0c2844" />
              </linearGradient>
              <linearGradient id="wlg-mid" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#7db0d8" /><stop offset="26%" stop-color="#aacfeb" />
                <stop offset="50%" stop-color="#ffffff" /><stop offset="74%" stop-color="#6fa2cb" />
                <stop offset="100%" stop-color="#93bfe0" />
              </linearGradient>
              <linearGradient id="wlg-light" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#cfe4f6" /><stop offset="30%" stop-color="#edf6fd" />
                <stop offset="55%" stop-color="#ffffff" /><stop offset="82%" stop-color="#bcd8ee" />
                <stop offset="100%" stop-color="#dcecf9" />
              </linearGradient>
              <linearGradient id="wlg-cross" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#cfe0f0" /><stop offset="35%" stop-color="#c4d9eb" />
                <stop offset="65%" stop-color="#b8d0e6" /><stop offset="100%" stop-color="#c9ddee" />
              </linearGradient>
            </defs>
            <rect x="53" y="53" width="94" height="94" rx="26" fill="url(#wlg-light)" stroke="url(#wlg-deep)" stroke-width="2.5" transform="rotate(-18 100 100) translate(-16 -16)" />
            <rect x="53" y="53" width="94" height="94" rx="26" fill="url(#wlg-mid)" stroke="url(#wlg-deep)" stroke-width="2" transform="rotate(-9 100 100) translate(-8 -8)" />
            <rect x="53" y="53" width="94" height="94" rx="26" fill="url(#wlg-card)" stroke="url(#wlg-cross)" stroke-width="3" />
            <rect x="92" y="68" width="16" height="64" rx="8" fill="url(#wlg-cross)" />
            <rect x="68" y="92" width="64" height="16" rx="8" fill="url(#wlg-cross)" />
          </svg>
          <span class="wordmark-name">MedTriage</span>
          <span class="wordmark-sub">多模态智能分诊</span>
        </RouterLink>
        <nav class="nav-links" aria-label="主导航">
          <a href="#modules">筛查能力</a>
          <a href="#agent">AI 智能分诊</a>
          <a href="#flow">工作流程</a>
          <a href="#compliance">安全边界</a>
        </nav>
        <div class="nav-cta">
          <RouterLink v-if="!auth.loggedIn" class="btn btn-text" to="/login">登录</RouterLink>
          <RouterLink v-else class="btn btn-text" to="/app">{{ auth.displayName }}</RouterLink>
          <RouterLink class="btn btn-primary" to="/app">进入系统
            <span class="btn-arrow-circle"><i class="ph ph-arrow-right" aria-hidden="true"></i></span>
          </RouterLink>
        </div>
      </div>
    </header>

    <main id="main">
      <!-- ============ 首屏：主视觉 ============ -->
      <section class="hero">
        <div class="container hero-grid">
          <div class="hero-brand stagger in">
            <div class="hero-kicker"><span class="hero-kicker-dot"></span>Screening · Triage · Navigation</div>
            <h1 class="hero-wordmark">MedTriage</h1>
            <div class="hero-subtitle">眼底图糖尿病视网膜病变筛查</div>
            <div class="hero-rule"></div>
            <p class="hero-desc">上传<strong>免散瞳眼底彩照</strong>，系统输出 DR 0–4 级分级、各级概率与病灶热力图，并给出随访节奏与就医提示。不诊断、不处方，只做糖网筛查参考。</p>
            <div class="hero-actions">
              <RouterLink class="btn hero-btn-primary" to="/app">
                开始筛查
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
              </RouterLink>
              <a class="btn hero-btn-ghost" href="#flow">了解更多</a>
            </div>
            <div class="hero-trust">
              <span>自训练 EfficientNet-B3</span>
              <span>QWK 0.896 · test 508 张</span>
              <span>DR 0–4 级五级分级</span>
            </div>
          </div>

          <div id="heroScene" class="hero-scene reveal" aria-label="社区医院三维微缩模型，可拖拽旋转、缩放查看">
            <canvas id="sceneCanvas"></canvas>
            <p class="hero-scene-hint"><i class="ph ph-hand-swipe-left" aria-hidden="true"></i> 拖拽旋转 · 滚轮缩放</p>
            <p class="hero-scene-fallback" hidden>当前浏览器不支持 WebGL，无法展示三维场景。</p>
          </div>
        </div>
      </section>

      <!-- 摘要条 -->
      <div class="abstract-wrap">
        <div class="container">
          <dl class="abstract reveal">
            <div class="abstract-cell">
              <dt>输入</dt>
              <dd>免散瞳眼底彩照 · 化验单影像</dd>
            </div>
            <div class="abstract-cell">
              <dt>输出</dt>
              <dd>DR 0–4 级分级 · 各级概率 · 病灶热力图</dd>
            </div>
            <div class="abstract-cell">
              <dt>边界</dt>
              <dd>不诊断、不处方、不给剂量、不建议停药</dd>
            </div>
            <div class="abstract-cell">
              <dt>提示</dt>
              <dd>视力骤降、视野缺损请立即就医</dd>
            </div>
          </dl>
        </div>
      </div>

      <!-- ============ 01 系统能力 ============ -->
      <section id="modules" class="section">
        <div class="container">
          <div class="section-head reveal">
            <p class="section-no">01</p>
            <div>
              <h2>一张眼底照，读懂糖网风险</h2>
              <p>围绕糖尿病视网膜病变筛查的完整链路：分级模型判读、病灶定位标注、多模态大模型报告解读、随访节奏映射；并支持化验单识别，辅助全身代谢指标评估。每一步输出都可追溯、可复核。</p>
            </div>
          </div>

          <div class="toc stagger">
            <article class="toc-row expanded">
              <div class="toc-main">
                <p class="toc-no">1.1</p>
                <h3 class="toc-title">DR 分级筛查</h3>
                <p class="toc-desc">上传免散瞳眼底彩照，EfficientNet-B3 输出 DR 0–4 级分级与各级概率，按分级映射眼科随访节奏。</p>
                <p class="toc-status"><span class="tag tag-active">已上线</span></p>
              </div>
              <div class="toc-table">
                <p class="table-caption"><b>分级对照</b>DR 各级的临床含义与随访节奏（占比取自本项目 test 留出集 508 张）</p>
                <table class="data-table">
                  <thead>
                    <tr><th>分级</th><th>临床含义</th><th>占比</th></tr>
                  </thead>
                  <tbody>
                    <tr class="hl"><td>0 级</td><td>无明显视网膜病变，6–12 个月内复查</td><td class="num">44.5%</td></tr>
                    <tr><td>1 级</td><td>轻度非增殖期病变（轻度 NPDR）</td><td class="num">11.4%</td></tr>
                    <tr><td>2 级</td><td>中度非增殖期病变（中度 NPDR）</td><td class="num">23.4%</td></tr>
                    <tr><td>3–4 级</td><td>重度 NPDR 至增殖期病变（PDR）</td><td class="num">20.7%</td></tr>
                  </tbody>
                </table>
              </div>
            </article>

            <article class="toc-row">
              <p class="toc-no">1.2</p>
              <h3 class="toc-title">病灶定位标注</h3>
              <p class="toc-desc">Grad-CAM 热力图标示可疑病灶位置与范围——微血管瘤、点状出血、硬性渗出等典型糖网征象一眼可见。</p>
              <p class="toc-status"><span class="tag tag-active">已上线</span></p>
            </article>

            <article class="toc-row">
              <p class="toc-no">1.3</p>
              <h3 class="toc-title">大模型报告解读</h3>
              <p class="toc-desc">大模型结合分级与病灶结果，生成结构化筛查报告：分级依据、危险因素与生活建议。</p>
              <p class="toc-status"><span class="tag tag-active">已上线</span></p>
            </article>

            <article class="toc-row">
              <p class="toc-no">1.4</p>
              <h3 class="toc-title">化验单识别</h3>
              <p class="toc-desc">上传血常规、生化、血糖血脂等报告，结构化为指标表格；异常项标橙并附通俗解释——糖尿病病程与血糖控制情况是糖网进展的关键参考。</p>
              <p class="toc-status"><span class="tag tag-active">已上线</span></p>
            </article>
          </div>
        </div>
      </section>

      <!-- ============ AI Agent 展示 ============ -->
      <section id="agent" class="agent-show">
        <div class="container">
          <div class="ag-head reveal">
            <div class="hero-kicker">AI · Agent</div>
            <h2 class="ag-title">AI 智能分诊<br /><em>辅助疾病风险判断</em></h2>
            <p class="ag-lead">
              从眼底、化验到症状，MedTriage 的 Agent <b>读完所有检查，给出分诊建议，也给出疾病风险判断</b>。每一步推理可追溯、可复核。
            </p>
            <div class="ag-caps">
              <span class="c"><i class="d b"></i>眼底筛查</span>
              <span class="c"><i class="d o"></i>化验单识别</span>
              <span class="c"><i class="d g"></i>症状分诊</span>
              <span class="c"><i class="d p"></i>疾病风险判断</span>
            </div>
          </div>

          <div class="ag-tabs reveal" role="tablist" aria-label="界面预览切换">
            <button type="button" class="ag-tab" :class="{ on: shot === 'workbench' }" role="tab" :aria-selected="shot === 'workbench'" @click="pickShot('workbench')">工作台总览</button>
            <button type="button" class="ag-tab" :class="{ on: shot === 'triage' }" role="tab" :aria-selected="shot === 'triage'" @click="pickShot('triage')">AI 扫描分诊</button>
          </div>

          <div class="ag-stack reveal">
            <!-- 图片只挂一份：原本前后两块屏幕各挂了一份（共 4 张），
                 任何一张 404 都会露出 alt 文字；这里收成 2 张，两处都取它。 -->
            <div class="ag-screen-back">
              <div class="ag-screen">
                <div class="ag-bar">
                  <span class="dots"><i></i><i></i><i></i></span>
                  <span class="addr">MedTriage · 工作台 / Agent 助手</span>
                </div>
                <div class="ag-shot">
                  <img
                    :src="ASSET_BASE + 'assets/agent-workbench.webp'"
                    :class="{ on: shot === 'workbench' }"
                    alt="MedTriage 工作台 · Agent 助手界面"
                    loading="lazy"
                    decoding="async"
                  />
                  <img
                    :src="ASSET_BASE + 'assets/agent-triage.webp'"
                    :class="{ on: shot === 'triage' }"
                    alt="MedTriage 症状分诊 · AI 扫描界面"
                    loading="lazy"
                    decoding="async"
                  />
                </div>
              </div>
            </div>
            <div class="ag-screen-front">
              <div class="ag-screen">
                <div class="ag-bar">
                  <span class="dots"><i></i><i></i><i></i></span>
                  <span class="addr">MedTriage · 工作台 / Agent 助手</span>
                </div>
                <div class="ag-shot">
                  <img
                    :src="ASSET_BASE + 'assets/agent-workbench.webp'"
                    :class="{ on: shot === 'workbench' }"
                    alt="MedTriage 工作台 · Agent 助手界面"
                    loading="lazy"
                    decoding="async"
                  />
                  <img
                    :src="ASSET_BASE + 'assets/agent-triage.webp'"
                    :class="{ on: shot === 'triage' }"
                    alt="MedTriage 症状分诊 · AI 扫描界面"
                    loading="lazy"
                    decoding="async"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 02 工作流程 ============ -->
      <section id="flow" class="method-band">
        <div class="container">
          <div class="section-head reveal">
            <p class="section-no">02</p>
            <div>
              <h2>从一张眼底照到一份筛查报告</h2>
              <p>四步完成，每步输出都可追溯、可复核。</p>
            </div>
          </div>
          <div class="method stagger">
            <div class="method-step">
              <p class="method-no">STEP 1</p>
              <h3>上传眼底照</h3>
              <p>免散瞳眼底彩照，手机拍摄或医院导出均可。</p>
            </div>
            <div class="method-step">
              <p class="method-no">STEP 2</p>
              <h3>模型分级</h3>
              <p>EfficientNet-B3 判读 DR 0–4 级，输出各级概率。</p>
            </div>
            <div class="method-step">
              <p class="method-no">STEP 3</p>
              <h3>病灶定位</h3>
              <p>Grad-CAM 热力图标示可疑病灶，结合大模型生成报告。</p>
            </div>
            <div class="method-step">
              <p class="method-no">STEP 4</p>
              <h3>随访建议</h3>
              <p>按分级映射复查节奏，给出就诊前注意事项。</p>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 03 边界与免责 ============ -->
      <section id="compliance" class="section">
        <div class="container">
          <div class="section-head reveal">
            <p class="section-no">03</p>
            <div>
              <h2>先说清做不到什么</h2>
            </div>
          </div>
          <div class="bounds reveal">
            <div class="bounds-left">
              <h3>MedTriage 是糖网筛查参考，不是医生。</h3>
              <p>它能帮你看清“有没有糖网风险、多快复查”，但永远代替不了散瞳眼底检查与眼科面诊。所有输出以“分级与疑似征象”表述，供眼科医生参考与复核。</p>
            </div>
            <ul class="bounds-list">
              <li><i class="ph ph-minus" aria-hidden="true"></i><span>不诊断——只输出 DR 分级与概率，不使用“确诊”表述</span></li>
              <li><i class="ph ph-minus" aria-hidden="true"></i><span>不处方——不给剂量、不建议停药、不推荐替代药</span></li>
              <li><i class="ph ph-minus" aria-hidden="true"></i><span>急症征象（视力骤降、视野缺损、眼前黑影骤增、眼痛伴头痛）提示立即就医</span></li>
              <li><i class="ph ph-minus" aria-hidden="true"></i><span>每份结果携带固定免责声明与时间戳</span></li>
              <li><i class="ph ph-minus" aria-hidden="true"></i><span>眼底照片与历史记录本地存储，可随时删除</span></li>
            </ul>
          </div>
        </div>
      </section>
    </main>

    <!-- ============ 页脚 ============ -->
    <footer class="footer">
      <div class="container">
        <div class="footer-grid">
          <div class="footer-brand">
            <RouterLink class="wordmark" to="/">
              <svg class="wordmark-logo" viewBox="20 26 127 127" width="36" height="36" aria-hidden="true">
                <defs>
                  <linearGradient id="wlg2-deep" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#0a2440" /><stop offset="18%" stop-color="#1a4a76" /><stop offset="36%" stop-color="#4f8ec2" /><stop offset="48%" stop-color="#dbeefd" /><stop offset="56%" stop-color="#3f7cb0" /><stop offset="76%" stop-color="#14395c" /><stop offset="100%" stop-color="#0c2844" /></linearGradient>
                  <linearGradient id="wlg2-card" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#0a2440" /><stop offset="18%" stop-color="#1a4a76" /><stop offset="36%" stop-color="#4f8ec2" /><stop offset="48%" stop-color="#7fa8cc" /><stop offset="56%" stop-color="#3f7cb0" /><stop offset="76%" stop-color="#14395c" /><stop offset="100%" stop-color="#0c2844" /></linearGradient>
                  <linearGradient id="wlg2-mid" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#7db0d8" /><stop offset="26%" stop-color="#aacfeb" /><stop offset="50%" stop-color="#ffffff" /><stop offset="74%" stop-color="#6fa2cb" /><stop offset="100%" stop-color="#93bfe0" /></linearGradient>
                  <linearGradient id="wlg2-light" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#cfe4f6" /><stop offset="30%" stop-color="#edf6fd" /><stop offset="55%" stop-color="#ffffff" /><stop offset="82%" stop-color="#bcd8ee" /><stop offset="100%" stop-color="#dcecf9" /></linearGradient>
                  <linearGradient id="wlg2-cross" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#cfe0f0" /><stop offset="35%" stop-color="#c4d9eb" /><stop offset="65%" stop-color="#b8d0e6" /><stop offset="100%" stop-color="#c9ddee" /></linearGradient>
                </defs>
                <rect x="53" y="53" width="94" height="94" rx="26" fill="url(#wlg2-light)" stroke="url(#wlg2-deep)" stroke-width="2.5" transform="rotate(-18 100 100) translate(-16 -16)" />
                <rect x="53" y="53" width="94" height="94" rx="26" fill="url(#wlg2-mid)" stroke="url(#wlg2-deep)" stroke-width="2" transform="rotate(-9 100 100) translate(-8 -8)" />
                <rect x="53" y="53" width="94" height="94" rx="26" fill="url(#wlg2-card)" stroke="url(#wlg2-cross)" stroke-width="3" />
                <rect x="92" y="68" width="16" height="64" rx="8" fill="url(#wlg2-cross)" />
                <rect x="68" y="92" width="64" height="16" rx="8" fill="url(#wlg2-cross)" />
              </svg>
              <span class="wordmark-name">MedTriage</span>
            </RouterLink>
            <p>多模态智能分诊与就医导航 · 结果需医生确认</p>
          </div>
          <nav class="footer-nav" aria-label="页脚导航">
            <div class="footer-col">
              <span>系统</span>
              <a href="#modules">筛查能力</a>
              <a href="#agent">AI 智能分诊</a>
              <a href="#flow">工作流程</a>
              <RouterLink to="/app">分诊工作台</RouterLink>
            </div>
            <div class="footer-col">
              <span>账户</span>
              <RouterLink to="/login">登录</RouterLink>
              <RouterLink :to="{ path: '/login', query: { tab: 'register' } }">注册</RouterLink>
            </div>
            <div class="footer-col">
              <span>合规</span>
              <a href="#compliance">安全边界</a>
            </div>
          </nav>
        </div>
        <div class="footer-legal">
          <span>结果仅为筛查参考，不构成诊断与治疗建议 · 急症请立即就医</span>
          <span class="mono">MEDTRIAGE © 2026</span>
        </div>
      </div>
    </footer>
  </div>
</template>
