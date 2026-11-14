<script setup lang="ts">
/**
 * 工作台外壳：侧栏 / 顶栏 / 页面容器 / 额度。
 * 设计沿用 frontend/app.html 定稿（styles/workbench.css 为机械提取，未改任何数值）。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { useRecordsStore, fmtTime, URG_TEXT, type MedRecord } from "@/stores/records";
import { PAGE_META, useWorkbenchStore, type PageKey } from "@/stores/workbench";
import ChatPage from "./pages/ChatPage.vue";
import WorkPage from "./pages/WorkPage.vue";
import EyePage from "./pages/EyePage.vue";
import LabPage from "./pages/LabPage.vue";
import SymptomPage from "./pages/SymptomPage.vue";
import MultiPage from "./pages/MultiPage.vue";
import HistoryPage from "./pages/HistoryPage.vue";
import HospitalPage from "./pages/HospitalPage.vue";
import GuidePage from "./pages/GuidePage.vue";
import { useHealth } from "@/composables/useHealth";
import "@/styles/workbench.css";

const router = useRouter();
const auth = useAuthStore();
const rec = useRecordsStore();
const wb = useWorkbenchStore();
const { data: health, isPending: healthPending, error: healthError } = useHealth();

const userMenuOpen = ref(false);
const infoOpen = ref(false);
const uploadOpen = ref(false);
const search = ref("");
const searchFocused = ref(false);

const searchOpen = computed(() => searchFocused.value && search.value.trim().length > 0);
const usageWidth = computed(
  () => `${rec.usage.month_used > 0 ? Math.max(rec.usagePct, 3) : 0}%`,
);

interface SearchHit {
  key: string;
  title: string;
  sub: string;
  page: PageKey;
}

const searchResults = computed<SearchHit[]>(() => {
  const q = search.value.trim().toLowerCase();
  if (!q) return [];
  return rec.records
    .filter((r: MedRecord) =>
      [r.input_type, r.department, r.summary].some((v) => (v || "").toLowerCase().includes(q)),
    )
    .slice(0, 6)
    .map((r) => ({
      key: String(r.id),
      title: `${r.input_type}${r.level != null ? ` · DR ${r.level} 级` : ""}`,
      sub: `${r.department} · ${URG_TEXT[r.urgency] ?? "常规"} · ${fmtTime(r.created_at)}`,
      page: r.input_type.includes("眼底") ? ("eye" as PageKey) : ("history" as PageKey),
    }));
});

function onSearchBlur() {
  setTimeout(() => (searchFocused.value = false), 160);
}

function openSearch(hit: SearchHit) {
  wb.go(hit.page);
  search.value = "";
  searchFocused.value = false;
}

function go(page: PageKey) {
  wb.go(page);
  userMenuOpen.value = false;
}

/**
 * 带科室参数的页面跳转。
 *
 * 报告页（症状分诊 / 眼底 / 化验单）都写了「建议科室：X」，也都有
 * 「按科室找医院」按钮；如果跳转时不把 X 带过去，医院页只能沿用
 * localStorage 里上一次选的科室，用户看到的就是没按本次结论排过序的列表。
 * 不带科室时 dept 为空串，等价于普通 go()。
 */
function goWithDept(page: PageKey, dept?: string) {
  wb.goWithDept(page, dept || "");
  userMenuOpen.value = false;
}

function goHome() {
  router.push({ name: "landing" });
}

async function onLogout() {
  try {
    const { api } = await import("@/lib/api");
    await api("/api/auth/logout", { method: "POST" });
  } catch {
    /* 网络异常也允许本地退出 */
  }
  auth.clear();
  router.push({ name: "login" });
}

function toggleUserMenu(e: MouseEvent) {
  e.stopPropagation();
  userMenuOpen.value = !userMenuOpen.value;
}

function onDocClick() {
  userMenuOpen.value = false;
}

onMounted(() => {
  void rec.load().catch(() => undefined);
  document.addEventListener("click", onDocClick);
});

/** 顶栏「上传报告」：跳到眼底筛查页的上传入口（该页自带拖拽与文件选择） */
function gotoUpload() {
  uploadOpen.value = false;
  wb.go("eye");
}
</script>

<template>
  <div class="app vW">
    <aside class="sb mt-silver">
      <i class="mirror-line"></i>
      <div class="sb-head">
        <div class="mk">
        <svg viewBox="20 26 127 127" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <defs>
            <linearGradient id="wlg-deep" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#0a2440"/><stop offset="18%" stop-color="#1a4a76"/>
              <stop offset="36%" stop-color="#4f8ec2"/><stop offset="48%" stop-color="#dbeefd"/>
              <stop offset="56%" stop-color="#3f7cb0"/><stop offset="76%" stop-color="#14395c"/>
              <stop offset="100%" stop-color="#0c2844"/>
            </linearGradient>
            <linearGradient id="wlg-card" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#0a2440"/><stop offset="18%" stop-color="#1a4a76"/>
              <stop offset="36%" stop-color="#4f8ec2"/><stop offset="48%" stop-color="#7fa8cc"/>
              <stop offset="56%" stop-color="#3f7cb0"/><stop offset="76%" stop-color="#14395c"/>
              <stop offset="100%" stop-color="#0c2844"/>
            </linearGradient>
            <linearGradient id="wlg-mid" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#7db0d8"/><stop offset="26%" stop-color="#aacfeb"/>
              <stop offset="50%" stop-color="#ffffff"/><stop offset="74%" stop-color="#6fa2cb"/>
              <stop offset="100%" stop-color="#93bfe0"/>
            </linearGradient>
            <linearGradient id="wlg-light" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#cfe4f6"/><stop offset="30%" stop-color="#edf6fd"/>
              <stop offset="55%" stop-color="#ffffff"/><stop offset="82%" stop-color="#bcd8ee"/>
              <stop offset="100%" stop-color="#dcecf9"/>
            </linearGradient>
            <linearGradient id="wlg-cross" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#cfe0f0"/><stop offset="35%" stop-color="#c4d9eb"/>
              <stop offset="65%" stop-color="#b8d0e6"/><stop offset="100%" stop-color="#c9ddee"/>
            </linearGradient>
          </defs>
          <rect x="53" y="53" width="94" height="94" rx="26" fill="url(#wlg-light)" stroke="url(#wlg-deep)" stroke-width="2.5" transform="rotate(-18 100 100) translate(-16 -16)"/>
          <rect x="53" y="53" width="94" height="94" rx="26" fill="url(#wlg-mid)" stroke="url(#wlg-deep)" stroke-width="2" transform="rotate(-9 100 100) translate(-8 -8)"/>
          <rect x="53" y="53" width="94" height="94" rx="26" fill="url(#wlg-card)" stroke="url(#wlg-cross)" stroke-width="3"/>
          <rect x="92" y="68" width="16" height="64" rx="8" fill="url(#wlg-cross)"/>
          <rect x="68" y="92" width="64" height="16" rx="8" fill="url(#wlg-cross)"/>
        </svg>
      </div>
      <span class="nm mt-text">MedTriage</span>
    </div>

    <div class="sb-group">
      <div class="gl">主流程</div>
      <nav class="sb-nav">
        <a class="sb-item" :class="{ on: wb.page === 'chat' }" @click="go('chat')">
          <svg viewBox="0 0 24 24" stroke-width="1.75">
            <path d="M12 3.2l1.8 5 5 1.8-5 1.8-1.8 5-1.8-5-5-1.8 5-1.8z"/>
            <path d="M18.6 14.6l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9z"/>
          </svg>
          <span class="tx">Agent助手</span>
          <span class="tag-ai">AI</span>
        </a>
        <a class="sb-item" :class="{ on: wb.page === 'work' }" @click="go('work')">
          <svg viewBox="0 0 24 24" stroke-width="1.75">
            <rect x="3.5" y="3.5" width="7" height="7" rx="2"/>
            <rect x="13.5" y="3.5" width="7" height="7" rx="2"/>
            <rect x="3.5" y="13.5" width="7" height="7" rx="2"/>
            <rect x="13.5" y="13.5" width="7" height="7" rx="2"/>
          </svg>
          <span class="tx">工作台</span>
        </a>
        <a class="sb-item" :class="{ on: wb.page === 'eye' }" @click="go('eye')">
          <svg viewBox="0 0 24 24" stroke-width="1.75">
            <path d="M2.5 12S5.8 5.5 12 5.5 21.5 12 21.5 12 18.2 18.5 12 18.5 2.5 12 2.5 12z"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
          <span class="tx">眼底筛查</span>
          <span class="cnt" v-show="rec.eyeRecords.length">{{ rec.eyeRecords.length }}</span>
        </a>
        <a class="sb-item" :class="{ on: wb.page === 'lab' }" @click="go('lab')">
          <svg viewBox="0 0 24 24" stroke-width="1.75">
            <path d="M14 2.5H7.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V8z"/>
            <path d="M14 2.5V8h4.5"/>
            <path d="M9 13.5h6M9 17h4"/>
          </svg>
          <span class="tx">化验单</span>
          <span class="cnt" v-show="rec.labRecords.length">{{ rec.labRecords.length }}</span>
        </a>
        <a class="sb-item" :class="{ on: wb.page === 'symptom' }" @click="go('symptom')">
          <svg viewBox="0 0 24 24" stroke-width="1.75">
            <path d="M20 11.5a7.5 7.5 0 0 1-11 6.6L4.5 20l1.4-4.2A7.5 7.5 0 1 1 20 11.5z"/>
            <path d="M9 11h.01M12 11h.01M15 11h.01"/>
          </svg>
          <span class="tx">症状分诊</span>
        </a>
        <a class="sb-item" :class="{ on: wb.page === 'multi' }" @click="go('multi')">
          <svg viewBox="0 0 24 24" stroke-width="1.75">
            <rect x="3" y="3" width="8" height="8" rx="2"/>
            <rect x="13" y="13" width="8" height="8" rx="2"/>
            <path d="M15.5 3.5l5 5M20.5 3.5l-5 5M3.5 15.5l5 5M8.5 15.5l-5 5"/>
          </svg>
          <span class="tx">多模态综合分析</span>
        </a>
      </nav>
    </div>

    <div class="sb-group">
      <div class="gl">资料</div>
      <nav class="sb-nav">
        <a class="sb-item" :class="{ on: wb.page === 'guide' }" @click="go('guide')">
          <svg viewBox="0 0 24 24" stroke-width="1.75">
            <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/>
            <path d="M4 20.5A2.5 2.5 0 0 0 6.5 23H20v-5M9 7.5h7M9 11h5"/>
          </svg>
          <span class="tx">使用指南</span>
          <span class="cnt" v-show="!rec.records.length">新</span>
        </a>
        <a class="sb-item" :class="{ on: wb.page === 'history' }" @click="go('history')">
          <svg viewBox="0 0 24 24" stroke-width="1.75">
            <path d="M3 12a9 9 0 1 0 3-6.7L3 8"/>
            <path d="M3 4v4h4"/>
            <path d="M12 7.5v4.8l3 2"/>
          </svg>
          <span class="tx">历史记录</span>
        </a>
        <a class="sb-item" :class="{ on: wb.page === 'hospital' }" @click="go('hospital')">
          <svg viewBox="0 0 24 24" stroke-width="1.75">
            <path d="M12 21.5s7-6.5 7-11.5a7 7 0 1 0-14 0c0 5 7 11.5 7 11.5z"/>
            <circle cx="12" cy="10" r="2.5"/>
          </svg>
          <span class="tx">附近医院</span>
        </a>
      </nav>
    </div>

    <div class="sb-foot">
      <div class="sb-user" ref="userEl" @click="toggleUserMenu">
        <div class="avatar">{{ auth.initial }}</div>
        <div class="u"><b>{{ auth.displayName }}</b><span>MedTriage · 分诊工作台</span></div>
        <span class="dots">⋯</span>
        <div class="sb-user-menu" :class="{ open: userMenuOpen }">
          <button type="button" @click="goHome">
            <svg viewBox="0 0 24 24"><path d="M3 11.5L12 4l9 7.5M5.5 10v9h13v-9"/></svg>
            返回首页
          </button>
          <button type="button" class="out" @click="onLogout">
            <svg viewBox="0 0 24 24"><path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 17l-5-5 5-5M5 12h11"/></svg>
            退出登录
          </button>
        </div>
      </div>
      <div class="sb-usage">
        <div class="k"><span>本月额度</span><span>{{ rec.usagePct }}%</span></div>
        <div class="bar"><i :style="{ width: usageWidth }"></i></div>
        <div class="n"><b>{{ rec.usage.month_used }}</b> / <span>{{ rec.usage.month_quota }}</span> 次筛查</div>
      </div>
    </div>
  </aside>

  <div class="vW-main mt-silver">
    <header class="tb blue">
      <i class="mirror-line dark"></i>
      <div class="crumbs"><span>{{ wb.parent }}</span> <span class="sep">/</span> <b>{{ wb.crumb }}</b></div>
      <div class="search" :class="{ focus: searchFocused }">
        <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
        <input v-model="search" type="text" aria-label="全局搜索：报告、医院、指标" placeholder="搜索报告、医院、指标…" autocomplete="off" spellcheck="false" @focus="searchFocused = true" @blur="onSearchBlur" />
        <span class="kbd">⌘K</span>
        <div class="tb-drop" v-show="searchOpen && searchResults.length">
          <button v-for="r in searchResults" :key="r.key" type="button" @mousedown.prevent="openSearch(r)">
            <b>{{ r.title }}</b><span>{{ r.sub }}</span>
          </button>
        </div>
      </div>
      <div class="right">
        <button class="tb-icon" type="button" title="历史记录" @click="go('history')">
          <span class="dotmark" v-show="rec.recheckRecords.length"></span>
          <svg viewBox="0 0 24 24"><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0"/></svg>
        </button>
        <button class="tb-icon" type="button" title="系统信息" @click="infoOpen = !infoOpen">
          <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/></svg>
        </button>
        <button class="btn-metal" type="button" @click="uploadOpen = true; gotoUpload()">
          <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg>
          <span>上传报告</span>
        </button>
        <div class="tb-who"><div class="avatar">{{ auth.initial }}</div><span>{{ auth.displayName }}</span></div>
      </div>
    </header>

    <div class="content">
      <nav class="mobile-nav" aria-label="工作台导航">
        <button v-for="(meta, key) in PAGE_META" :key="key" type="button"
          :aria-current="wb.page === key ? 'page' : undefined" @click="go(key)">{{ meta.label }}</button>
        <button type="button" @click="onLogout">退出登录</button>
      </nav>
      <div class="ws-page chat" :class="{ on: wb.page === 'chat' }">
        <ChatPage :active="wb.page === 'chat'" @go="goWithDept" />
      </div>
      <div class="ws-page" :class="{ on: wb.page === 'work' }">
        <WorkPage @go="go" />
      </div>
      <div class="ws-page" :class="{ on: wb.page === 'eye' }">
        <EyePage :active="wb.page === 'eye'" @go="goWithDept" />
      </div>
      <div class="ws-page" :class="{ on: wb.page === 'lab' }">
        <LabPage :active="wb.page === 'lab'" @go="goWithDept" />
      </div>
      <div class="ws-page sxp" :class="{ on: wb.page === 'symptom' }">
        <SymptomPage @go="goWithDept" />
      </div>
      <div class="ws-page" :class="{ on: wb.page === 'multi' }">
        <MultiPage :active="wb.page === 'multi'" @go="go" />
      </div>
      <div class="ws-page" :class="{ on: wb.page === 'history' }">
        <HistoryPage @go="go" />
      </div>
      <div class="ws-page" :class="{ on: wb.page === 'hospital' }">
        <HospitalPage :active="wb.page === 'hospital'" />
      </div>
      <div class="ws-page" :class="{ on: wb.page === 'guide' }">
        <GuidePage :active="wb.page === 'guide'" @go="go" />
      </div>
    </div>
  </div>
</div>

<div class="usage-float" aria-hidden="true">
  <span>本月额度</span>
  <span class="bar"><i :style="{ width: usageWidth }"></i></span>
  <b>{{ rec.usage.month_used }} / {{ rec.usage.month_quota }}</b>
</div>
<div v-if="infoOpen" class="r6-modal" role="dialog" aria-modal="true" aria-labelledby="system-info-title" @keydown.esc="infoOpen = false">
  <div class="r6-modal-mask" @click="infoOpen = false"></div>
  <div class="r6-modal-body" style="width:600px">
    <div class="r6-modal-head"><b id="system-info-title">系统信息</b><span>当前服务能力</span><button type="button" aria-label="关闭系统信息" @click="infoOpen = false">×</button></div>
    <div style="padding:20px;font-size:13px;line-height:1.8;overflow-wrap:anywhere">
      <p v-if="healthPending">正在读取服务状态…</p>
      <p v-else-if="healthError">无法读取状态，请确认后端服务已启动。</p>
      <dl v-else-if="health">
        <dt>大模型服务</dt><dd>{{ health.llm_enabled ? '已启用' : '未启用（症状与 Agent 可使用离线规则）' }}</dd>
        <dt>文本模型</dt><dd>{{ health.llm_model || '未配置' }}</dd>
        <dt>视觉模型</dt><dd>{{ health.llm_vision_model || '未配置' }}</dd>
        <dt>眼底推理</dt><dd>{{ health.fundus_mode === 'model' ? '本地真实模型' : '演示模式' }}</dd>
      </dl>
    </div>
  </div>
</div>
</template>
