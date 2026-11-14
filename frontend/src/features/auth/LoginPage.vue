<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRouter, useRoute } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { api, ApiError } from "@/lib/api";

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();

// 从旧版迁移时按 ?tab= 硬读了 location.search，切路由到 /login 时该参数并不存在，
// 改为读路由 query，同时保留直接带 ?tab=register 访问的兼容。
const mode = ref<"login" | "register">(
  new URLSearchParams(location.search).get("tab") === "register" ? "register" : "login",
);
if (auth.loggedIn) router.replace({ name: "workbench" });

// 旧版 login.html 的 <body> 无 class，直接吃全局 body 样式（style.css 的 --paper 底 + 光晕层）。
// Vue 版要在登录页还原那层底，同时不能污染工作台的 body 样式。
onMounted(() => document.body.classList.add("auth-page"));
onBeforeUnmount(() => document.body.classList.remove("auth-page"));

const loading = ref(false);
const alertMsg = ref("");
const showAlert = ref(false);

const form = reactive({ username: "", password: "", regUsername: "", regPassword: "", agreeTerms: false });
const errors = reactive<Record<string, string>>({ username: "", password: "", regUsername: "", regPassword: "" });

function switchTo(m: "login" | "register") {
  mode.value = m;
  clearErrors();
}

function setErr(field: keyof typeof errors, msg: string) {
  errors[field] = msg;
}

function clearErrors() {
  errors.username = "";
  errors.password = "";
  errors.regUsername = "";
  errors.regPassword = "";
  showAlert.value = false;
}

function validate(): boolean {
  clearErrors();
  let ok = true;
  if (mode.value === "login") {
    const u = form.username.trim();
    if (!u) { setErr("username", "请输入用户名"); ok = false; }
    else if (u.length < 2 || u.length > 20) { setErr("username", "用户名需 2–20 个字符"); ok = false; }
    if (!form.password) { setErr("password", "请输入密码"); ok = false; }
  } else {
    const u = form.regUsername.trim();
    if (!u) { setErr("regUsername", "请输入用户名"); ok = false; }
    else if (u.length < 2 || u.length > 20) { setErr("regUsername", "用户名需 2–20 个字符"); ok = false; }
    if (!form.regPassword) { setErr("regPassword", "请输入密码"); ok = false; }
    else if (form.regPassword.length < 6) { setErr("regPassword", "密码至少 6 位"); ok = false; }
    if (!form.agreeTerms) {
      alertMsg.value = "请先阅读并同意《用户协议》与《隐私政策》";
      showAlert.value = true;
      ok = false;
    }
  }
  return ok;
}

async function onSubmit() {
  if (!validate()) return;
  loading.value = true;
  showAlert.value = false;
  try {
    const u = mode.value === "login" ? form.username.trim() : form.regUsername.trim();
    const p = mode.value === "login" ? form.password : form.regPassword;
    const data = await api<{ token: string; username: string }>(`/api/auth/${mode.value}`, {
      method: "POST",
      body: { username: u, password: p },
    });
    auth.save(data);
    const redirect = (route.query.redirect as string) || "/app";
    router.push(redirect);
  } catch (e) {
    alertMsg.value = e instanceof ApiError ? e.message : String(e);
    showAlert.value = true;
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="wrap auth-wrap">
    <section class="lay-04">
      <!-- 旧版 login.html 的离线渐变定义：logo 用 url(#mLight) 等引用，
           删掉这块 SVG 会让 logo 全部渲染成黑色，必须原样保留 -->
      <svg class="logo-defs" aria-hidden="true" focusable="false">
        <defs>
          <linearGradient id="mDeep" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#0a2440" />
            <stop offset="18%" stop-color="#1a4a76" />
            <stop offset="36%" stop-color="#4f8ec2" />
            <stop offset="48%" stop-color="#7fa8cc" />
            <stop offset="56%" stop-color="#3f7cb0" />
            <stop offset="76%" stop-color="#14395c" />
            <stop offset="100%" stop-color="#0c2844" />
          </linearGradient>
          <linearGradient id="mCard" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#0a2440" />
            <stop offset="18%" stop-color="#1a4a76" />
            <stop offset="36%" stop-color="#4f8ec2" />
            <stop offset="48%" stop-color="#7fa8cc" />
            <stop offset="56%" stop-color="#3f7cb0" />
            <stop offset="76%" stop-color="#14395c" />
            <stop offset="100%" stop-color="#0c2844" />
          </linearGradient>
          <linearGradient id="mMid" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#7db0d8" />
            <stop offset="26%" stop-color="#aacfeb" />
            <stop offset="50%" stop-color="#c8dff0" />
            <stop offset="74%" stop-color="#6fa2cb" />
            <stop offset="100%" stop-color="#93bfe0" />
          </linearGradient>
          <linearGradient id="mLight" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#cfe4f6" />
            <stop offset="30%" stop-color="#eaf4fc" />
            <stop offset="55%" stop-color="#dceaf7" />
            <stop offset="82%" stop-color="#bcd8ee" />
            <stop offset="100%" stop-color="#dcecf9" />
          </linearGradient>
          <linearGradient id="mCross" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#cfe0f0" />
            <stop offset="35%" stop-color="#c4d9eb" />
            <stop offset="65%" stop-color="#b8d0e6" />
            <stop offset="100%" stop-color="#c9ddee" />
          </linearGradient>
          <filter id="softShadow" x="-30%" y="-30%" width="160%" height="160%">
            <feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="#2a5a8a" flood-opacity="0.18" />
          </filter>
        </defs>
      </svg>

      <div class="bg-grid"></div>
      <div class="megatype">MED<span class="solid">TRI</span>AGE</div>

      <div class="top-bar">
        <RouterLink class="logo" to="/" aria-label="返回 MedTriage 首页">
          <svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" filter="url(#softShadow)" aria-hidden="true">
            <rect
              x="53"
              y="53"
              width="94"
              height="94"
              rx="26"
              fill="url(#mLight)"
              stroke="url(#mDeep)"
              stroke-width="2.5"
              transform="rotate(-18 100 100) translate(-16 -16)"
            />
            <rect
              x="53"
              y="53"
              width="94"
              height="94"
              rx="26"
              fill="url(#mMid)"
              stroke="url(#mDeep)"
              stroke-width="2"
              transform="rotate(-9 100 100) translate(-8 -8)"
            />
            <rect x="53" y="53" width="94" height="94" rx="26" fill="url(#mCard)" stroke="url(#mCross)" stroke-width="3" />
            <rect x="92" y="68" width="16" height="64" rx="8" fill="url(#mCross)" />
            <rect x="68" y="92" width="64" height="16" rx="8" fill="url(#mCross)" />
          </svg>
          <span class="name">MedTriage</span>
        </RouterLink>
        <div class="actions">
          <RouterLink to="/#modules">筛查能力</RouterLink>
          <RouterLink to="/#flow">工作流程</RouterLink>
          <RouterLink to="/" class="pill">返回首页</RouterLink>
        </div>
      </div>

      <div class="center-cols">
        <div class="pitch">
          <div class="label">眼底图糖尿病视网膜病变筛查</div>
          <h2>眼底一照，<br />看清<em>糖网风险</em>。</h2>
          <p>眼底彩照、化验单，都可以上传。系统给出 DR 分级、病灶热力图、随访节奏与就医提示。<strong>不诊断、不处方</strong>，只做筛查参考，所有结果需医生确认。</p>
          <div class="tags">
            <span>DR 分级筛查</span>
            <span>病灶热力图</span>
            <span>化验单识别</span>
            <span>随访建议</span>
          </div>
        </div>

        <div class="panel">
          <div class="auth-alert" :class="{ show: showAlert }" role="alert">{{ alertMsg }}</div>

          <form @submit.prevent="onSubmit" novalidate>
            <div v-if="mode === 'login'" class="form-view">
              <div class="cap">Sign In</div>
              <h3>登录</h3>
              <p class="sub">使用账户继续糖网筛查与报告解读</p>

              <div class="fi" :class="{ err: !!errors.username }">
                <input type="text" placeholder=" " v-model="form.username" autocomplete="username" maxlength="20" id="username" />
                <label for="username">用户名</label>
                <p class="field-msg">{{ errors.username }}</p>
              </div>
              <div class="fi" :class="{ err: !!errors.password }">
                <input type="password" placeholder=" " v-model="form.password" autocomplete="current-password" id="password" />
                <label for="password">密码</label>
                <p class="field-msg">{{ errors.password }}</p>
              </div>
              <div class="row">
                <span>账户仅用于保存您的筛查历史</span>
                <RouterLink to="/#compliance">合规与免责声明</RouterLink>
              </div>
              <button class="btn" :class="{ loading }" type="submit" :disabled="loading">登录</button>
              <div class="foot">
                还没有账号？<a href="javascript:void(0)" class="link" @click="switchTo('register')">立即注册</a>
              </div>
            </div>

            <div v-else class="form-view">
              <div class="cap">Sign Up</div>
              <h3>注册</h3>
              <p class="sub">30 秒完成，开始使用</p>

              <div class="fi" :class="{ err: !!errors.regUsername }">
                <input type="text" placeholder=" " v-model="form.regUsername" autocomplete="off" maxlength="20" id="regUsername" />
                <label for="regUsername">用户名（2–20 个字符）</label>
                <p class="field-msg">{{ errors.regUsername }}</p>
              </div>
              <div class="fi" :class="{ err: !!errors.regPassword }">
                <input type="password" placeholder=" " v-model="form.regPassword" autocomplete="new-password" id="regPassword" />
                <label for="regPassword">密码（至少 6 位）</label>
                <p class="field-msg">{{ errors.regPassword }}</p>
              </div>
              <label class="terms">
                <input type="checkbox" v-model="form.agreeTerms" />
                <span
                  >我已阅读并同意 <RouterLink to="/#compliance">《用户协议》</RouterLink> 与
                  <RouterLink to="/#compliance">《隐私政策》</RouterLink>，理解本系统仅提供筛查参考，所有结果需医生确认。</span
                >
              </label>
              <button class="btn" :class="{ loading }" type="submit" :disabled="loading">创建账号</button>
              <div class="foot">
                已有账号？<a href="javascript:void(0)" class="link" @click="switchTo('login')">立即登录</a>
              </div>
            </div>
          </form>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* ============================================================
   登录 / 注册页 —— 样式逐条对齐 frontend-legacy/login.html 的内联 <style>
   差异来源：Vue 版重写过一版，把 ::after 扫光、megatype 描边、
   logo svg、uppercase 按钮等规则漏掉了，这里全部还原。
   ============================================================ */

/* ---- 旧版 .wrap ---- */
.wrap {
  max-width: 1480px;
  margin: 0 auto;
  padding: 60px 32px 100px;
}

/* ---- 旧版 .lay-04：金属光泽渐变底 ---- */
.lay-04 {
  position: relative;
  min-height: 800px;
  border-radius: 32px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.85);
  background: linear-gradient(
    145deg,
    #f4faff 0%,
    #e2eefa 16%,
    #cfe3f6 32%,
    #eaf4fd 46%,
    #d6e8f8 58%,
    #bcd6ee 72%,
    #d8e8f6 86%,
    #eef7fe 100%
  );
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.95) inset,
    0 30px 70px -40px rgba(40, 90, 140, 0.45);
}

/* ---- 旧版 .lay-04::after：11s 循环扫光（Vue 版此前完全丢失）---- */
.lay-04::after {
  content: "";
  position: absolute;
  top: -120%;
  left: 0;
  width: 45%;
  height: 340%;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.3) 32%,
    rgba(255, 255, 255, 0.75) 50%,
    rgba(255, 255, 255, 0.3) 68%,
    transparent 100%
  );
  transform: translateX(-170%) skewX(-18deg);
  animation: sheen 11s linear infinite;
  pointer-events: none;
  mix-blend-mode: screen;
  z-index: 3;
}
@keyframes sheen {
  0% {
    transform: translateX(-170%) skewX(-18deg);
    opacity: 0;
  }
  5% {
    opacity: 1;
  }
  22% {
    transform: translateX(330%) skewX(-18deg);
    opacity: 1;
  }
  27% {
    opacity: 0;
  }
  100% {
    transform: translateX(330%) skewX(-18deg);
    opacity: 0;
  }
}

/* ---- 巨型字：描边空心 + .solid 半透明填充（Vue 版渲染成了实心小字）---- */
.megatype {
  position: absolute;
  left: -40px;
  top: -30px;
  font-family: "Segoe UI", Arial, sans-serif;
  font-size: clamp(200px, 28vw, 420px);
  font-weight: 900;
  letter-spacing: -0.08em;
  line-height: 0.82;
  color: transparent;
  -webkit-text-stroke: 1.5px rgba(79, 142, 194, 0.2);
  user-select: none;
  pointer-events: none;
  z-index: 1;
  white-space: nowrap;
}
.megatype .solid {
  color: rgba(79, 142, 194, 0.06);
  -webkit-text-stroke: 0;
}

/* ---- 网格底纹 ---- */
.bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(80, 140, 200, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(80, 140, 200, 0.06) 1px, transparent 1px);
  background-size: 64px 64px;
  pointer-events: none;
  opacity: 0.5;
  z-index: 0;
}

/* ---- 离线渐变定义的承载容器（不可见，但不能 display:none，否则渐变失效）---- */
.logo-defs {
  position: absolute;
  width: 0;
  height: 0;
  overflow: hidden;
}

/* ---- 顶栏 ---- */
.top-bar {
  position: relative;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 44px 56px;
}
.top-bar .logo {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
}
.top-bar .logo svg {
  width: 38px;
  height: 38px;
  transform: translateY(-2px);
}
.top-bar .logo .name {
  font-family: "Segoe UI", Arial, sans-serif;
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: #0c2844;
}
.top-bar .actions {
  display: flex;
  align-items: center;
  gap: 26px;
  font-size: 12px;
  letter-spacing: 0.1em;
  color: #8aa8c4;
}
.top-bar .actions a {
  color: inherit;
  text-decoration: none;
  transition: color 0.25s;
}
.top-bar .actions a:hover {
  color: #2f6ea8;
}
.top-bar .actions .pill {
  padding: 9px 20px;
  border: 1px solid #c8ddf0;
  border-radius: 100px;
  color: #3d6285;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.6);
}

/* ---- 双栏主体 ---- */
.center-cols {
  position: relative;
  z-index: 5;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 80px;
  padding: 40px 80px 100px;
  align-items: center;
}

/* ---- 左侧文案 ---- */
.pitch .label {
  font-size: 10.5px;
  letter-spacing: 0.36em;
  font-weight: 700;
  text-transform: uppercase;
  color: #7fa2c2;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.pitch .label::before {
  content: "";
  width: 28px;
  height: 1px;
  background: #a9cbe8;
}
.pitch h2 {
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  font-size: clamp(38px, 4.2vw, 52px);
  font-weight: 800;
  letter-spacing: -0.032em;
  line-height: 1.14;
  color: #0c2844;
  margin-bottom: 24px;
}
.pitch h2 em {
  font-style: normal;
  background: linear-gradient(135deg, #2f6ea8 0%, #5a9ed0 50%, #2f8fff 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.pitch p {
  font-size: 14.5px;
  line-height: 2;
  color: #4d7295;
  max-width: 480px;
  margin-bottom: 32px;
  letter-spacing: 0.005em;
}
.pitch p strong {
  color: #1a4a76;
  font-weight: 700;
}
.pitch .tags {
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
}
.pitch .tags span {
  padding: 8px 16px;
  border-radius: 100px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid #d8e8f6;
  font-size: 11.5px;
  font-weight: 600;
  color: #3d6285;
  letter-spacing: 0.02em;
}

/* ---- 表单卡片 ---- */
.panel {
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid #dbeaf7;
  border-radius: 22px;
  padding: 48px 44px 42px;
  box-shadow:
    0 40px 90px -50px rgba(40, 90, 140, 0.6),
    0 0 120px -60px rgba(47, 143, 255, 0.4);
  position: relative;
}
.form-view {
  transition:
    opacity 0.28s ease,
    transform 0.28s ease;
}
.panel .cap {
  font-size: 10.5px;
  letter-spacing: 0.32em;
  text-transform: uppercase;
  color: #7fa2c2;
  margin-bottom: 16px;
}
.panel h3 {
  font-size: 26px;
  font-weight: 800;
  color: #0c2844;
  letter-spacing: -0.01em;
  margin-bottom: 8px;
}
.panel .sub {
  font-size: 12.5px;
  color: #8aa8c4;
  margin-bottom: 32px;
}

/* ---- 输入框 ---- */
.fi {
  position: relative;
  margin-bottom: 20px;
}
.fi input {
  width: 100%;
  height: 56px;
  padding: 22px 20px 8px 20px;
  border-radius: 12px;
  border: 1px solid #d0e4f4;
  color: var(--ink);
  background: #fff;
  font-family: inherit;
  font-size: 14.5px;
  outline: none;
  transition: all 0.3s;
}
.fi input::placeholder {
  color: transparent;
}
.fi input:focus {
  border-color: #7fb8dc;
  box-shadow: 0 0 0 4px rgba(47, 143, 255, 0.08);
}
.fi label {
  position: absolute;
  left: 20px;
  top: 18px;
  font-size: 14.5px;
  color: #a8c0d4;
  pointer-events: none;
  transition:
    top 0.22s,
    font-size 0.22s,
    color 0.22s,
    font-weight 0.22s,
    letter-spacing 0.22s;
}
.fi input:focus + label,
.fi input:not(:placeholder-shown) + label {
  top: 7px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: #3d6285;
}
.fi .field-msg {
  font-size: 11px;
  color: #c23a24;
  margin: 6px 0 0 4px;
  line-height: 1.5;
  /* 旧版没有 min-height：无错误时高度为 0，不占位。
     加上 min-height 会让每个输入框整体高 20px、面板高 40px、内容整体下移 20px。 */
}
.fi.err input {
  border-color: #d9a09a;
  box-shadow: 0 0 0 4px rgba(194, 58, 36, 0.07);
}
.fi.err label {
  color: #c23a24 !important;
}

/* ---- 全局错误条 ---- */
.auth-alert {
  display: none;
  margin-bottom: 20px;
  padding: 12px 16px;
  border-radius: 12px;
  background: rgba(194, 58, 36, 0.06);
  border: 1px solid rgba(194, 58, 36, 0.22);
  color: #a3321f;
  font-size: 12.5px;
  line-height: 1.6;
}
.auth-alert.show {
  display: block;
}

/* ---- 主按钮：旧版带 uppercase ---- */
.btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  height: 56px;
  border-radius: 12px;
  border: none;
  cursor: pointer;
  font-family: inherit;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  background: linear-gradient(135deg, #1a4a76 0%, #4f8ec2 38%, #2f6ea8 72%, #14395c 100%);
  color: #fff;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.3),
    0 18px 36px -14px rgba(30, 80, 130, 0.8);
  transition:
    transform 0.35s cubic-bezier(0.2, 0.8, 0.2, 1),
    box-shadow 0.35s;
  position: relative;
}
.btn:hover {
  transform: translateY(-2px);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.4),
    0 24px 46px -14px rgba(30, 80, 130, 0.9);
}
.btn[disabled] {
  opacity: 0.7;
  cursor: wait;
  transform: none;
}
.btn.loading {
  color: transparent;
  pointer-events: none;
}
.btn.loading::after {
  content: "";
  position: absolute;
  top: 50%;
  left: 50%;
  width: 16px;
  height: 16px;
  margin: -9px 0 0 -9px;
  border: 2px solid rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

/* ---- 登录页行内提示 / 协议 / 底部 ---- */
.panel .row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: #8aa8c4;
  margin: 0 0 24px;
}
.panel .row a {
  color: #3d6285;
  text-decoration: none;
  font-weight: 600;
}
.panel .row a:hover {
  color: #2f6ea8;
}
.terms {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  font-size: 11.5px;
  line-height: 1.7;
  color: #8aa8c4;
  margin: 0 0 22px;
  cursor: pointer;
}
.terms input {
  width: 14px;
  height: 14px;
  margin-top: 2px;
  accent-color: #2f6ea8;
  cursor: pointer;
  flex-shrink: 0;
}
.terms a {
  color: #2f6ea8;
  text-decoration: none;
  font-weight: 600;
}
.terms a:hover {
  text-decoration: underline;
}
.panel .foot {
  text-align: center;
  font-size: 12.5px;
  color: #8aa8c4;
  margin-top: 22px;
}
.panel .foot a {
  color: #2f6ea8;
}
.link {
  color: inherit;
  text-decoration: none;
  font-weight: 600;
  transition: opacity 0.2s;
}
.link:hover {
  opacity: 0.7;
}

/* ---- 响应式：与旧版断点一致 ---- */
@media (max-width: 1000px) {
  .center-cols {
    grid-template-columns: 1fr;
    gap: 50px;
    padding: 30px 40px 60px;
  }
  .megatype {
    font-size: 260px;
  }
  .top-bar {
    padding: 30px 36px;
  }
  .top-bar .actions .pill {
    display: none;
  }
}
@media (max-width: 640px) {
  .wrap {
    padding: 30px 16px 60px;
  }
  .center-cols {
    padding: 20px 24px 50px;
    gap: 36px;
  }
  .top-bar {
    padding: 22px 24px;
  }
  .top-bar .actions {
    gap: 16px;
  }
  .panel {
    padding: 36px 26px 32px;
  }
  .panel h3 {
    font-size: 22px;
  }
  .pitch h2 {
    font-size: 30px;
  }
}

/* ---- 视口居中（实测反馈：登录页偏上、外框底边被截）：外框按视口高度铺满，内容在框内垂直居中 ---- */
.auth-wrap {
  --auth-pad: clamp(14px, 3vh, 40px);
  min-height: 100vh;
  min-height: 100dvh;
  box-sizing: border-box;
  padding-top: var(--auth-pad);
  padding-bottom: var(--auth-pad);
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.auth-wrap > .lay-04 {
  min-height: calc(100vh - 2 * var(--auth-pad));
  min-height: calc(100dvh - 2 * var(--auth-pad));
  display: flex;
  flex-direction: column;
}
.auth-wrap .center-cols {
  flex: 1;
  align-content: center;
  padding-top: clamp(8px, 2vh, 40px);
  padding-bottom: clamp(28px, 7vh, 100px);
}
@media (max-height: 820px) {
  .auth-wrap .top-bar {
    padding-top: 24px;
    padding-bottom: 24px;
  }
}
</style>
