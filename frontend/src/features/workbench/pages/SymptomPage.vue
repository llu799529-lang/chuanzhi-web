<script setup lang="ts">
/**
 * 症状分诊：症状标签 + 自由描述 → 规则引擎 / 大模型分诊气泡流。
 * 版式沿用 app.html 的 sxp 布局，交互由响应式状态驱动。
 */
import { computed, nextTick, ref, watch } from "vue";
import { api } from "@/lib/api";
import { useWorkbenchStore, type PageKey } from "@/stores/workbench";

/** 红旗规则对应的国内指南（主题级）：列在红旗提示最后一行，说明这条提醒有据可查。 */
function basisItem(basis?: { title?: string }[]): string {
  const titles = (basis ?? []).map((b) => (b.title || "").trim()).filter(Boolean).slice(0, 3);
  return titles.length ? `<li class="basis">规则依据：${titles.map((t) => `《${attr(t)}》`).join("、")}</li>` : "";
}

// 第三个参数是「带着哪个科室去」。分诊出神经内科，医院页却按默认眼科展示，
// 就是把分诊里最有用的那个结论丢掉了 —— 科室必须跟着跳转走。
const emit = defineEmits<{ go: [page: PageKey, dept?: string] }>();

/** 塞进 HTML 属性前的最小转义：科室名来自模型输出，不能直接拼进属性。 */
function attr(s: string): string {
  return (s || "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

interface Rule {
  keys: string[];
  dept: string;
  alt: string;
  urg: string;
  echo: string;
  suspects: [string, number, string][];
  tests: string[];
  prep: string[];
  reds: string[];
}

const GROUPS: { title: string; hint?: string; items: string[] }[] = [
  { title: "常见症状", hint: "点头即可添加", items: ["头晕", "头痛", "发热", "乏力", "咳嗽", "胸闷", "胸痛", "心慌", "气短"] },
  { title: "消化系统", items: ["恶心", "呕吐", "腹痛", "腹泻", "便秘", "腹胀", "食欲不振"] },
  { title: "神经 / 五官", items: ["视力模糊", "耳鸣", "眩晕", "麻木", "失眠", "记忆力下降"] },
  { title: "其他", items: ["皮疹", "关节痛", "水肿", "体重下降"] },
];

/** 规则库（与原生版一致，演示用规则引擎；接大模型时保留为降级兜底） */
const RULES: Rule[] = [
  {
    keys: ["胸痛", "胸闷", "心慌", "心悸", "气短", "胸口", "心前区", "憋气"],
    dept: "心内科",
    alt: "若剧痛持续不缓解，直接前往急诊科",
    urg: "橙色 · 建议 24–48 小时内就诊",
    echo: "胸部 / 循环系统症状",
    suspects: [
      ["稳定型心绞痛", 34, "活动后胸闷胸痛、休息数分钟可缓解，中年以上人群常见，建议尽早评估。"],
      ["心律失常", 26, "心慌伴脉搏不齐时建议做动态心电图捕捉发作。"],
      ["焦虑相关躯体症状", 18, "情绪紧张时加重，排除器质性病变后可就诊心理科。"],
    ],
    tests: ["心电图 + 动态心电图", "心肌酶谱", "心脏彩超", "血压 / 血脂 / 血糖"],
    prep: ["记录发作时间、持续时长与诱因", "就诊前避免剧烈运动与浓茶咖啡", "带上既往心电图（如有）"],
    reds: ["胸痛持续超过 15 分钟不缓解", "伴大汗、濒死感、放射至左臂", "伴呼吸困难或意识模糊", "心慌伴晕厥"],
  },
  {
    keys: ["头晕", "头痛", "眩晕", "麻木", "记忆力下降", "失眠"],
    dept: "神经内科",
    alt: "头痛伴视力变化可考虑眼科会诊",
    urg: "黄色 · 建议 1 周内就诊",
    echo: "神经 / 头部症状",
    suspects: [
      ["原发性头痛（紧张型 / 偏头痛）", 32, "与睡眠、压力相关，记录头痛日记有助于分型。"],
      ["颈椎相关眩晕", 24, "转头时加重、伴颈肩僵硬，可先做颈椎影像。"],
      ["体位性低血压", 18, "起床时头晕明显，建议测卧位与立位血压。"],
      ["睡眠障碍相关", 14, "长期失眠可加重头昏，先评估睡眠质量。"],
    ],
    tests: ["头颅 CT / MRI（医生评估后）", "颈椎正侧位片", "卧位 + 立位血压", "血脂 / 血糖 / 同型半胱氨酸"],
    prep: ["记录头痛或头晕发作的时间与诱因", "测量并记录血压变化", "整理用药清单（含保健品）"],
    reds: ["突发剧烈头痛（雷击样）", "伴肢体无力、口角歪斜、言语不清", "伴发热与颈部僵硬", "意识改变或抽搐"],
  },
  {
    keys: ["发热", "咳嗽", "咽痛", "流涕", "咳痰", "气喘"],
    dept: "呼吸内科",
    alt: "伴咽痛明显也可先到全科门诊",
    urg: "黄色 · 建议 3 天内就诊",
    echo: "呼吸系统症状",
    suspects: [
      ["上呼吸道感染", 38, "多由病毒引起，以休息、补水为主，注意体温变化。"],
      ["支气管炎", 24, "咳嗽超过 2 周或伴黄痰建议胸片检查。"],
      ["过敏性鼻炎", 16, "遇冷空气、粉尘加重的流涕喷嚏，可做过敏原筛查。"],
      ["肺炎（需排除）", 8, "高热不退、气促或胸痛时需及时影像学检查。"],
    ],
    tests: ["血常规 + C 反应蛋白", "胸片 / 胸部 CT", "甲乙流抗原", "肺功能（气促时）"],
    prep: ["记录体温曲线与咳嗽性质", "就诊时佩戴口罩，减少交叉感染", "列出已服用的药物与剂量"],
    reds: ["呼吸困难或口唇发紫", "持续高热超过 3 天不退", "咳血或胸痛明显", "老人、孕妇、婴幼儿症状加重"],
  },
  {
    keys: ["恶心", "呕吐", "腹痛", "腹泻", "便秘", "腹胀", "食欲不振"],
    dept: "消化内科",
    alt: "右下腹固定压痛需警惕阑尾炎",
    urg: "黄色 · 建议 1 周内就诊",
    echo: "消化系统症状",
    suspects: [
      ["急性胃肠炎", 34, "多有饮食不洁史，注意补液与电解质。"],
      ["功能性消化不良", 22, "餐后腹胀、早饱，规律饮食后可观察 1–2 周。"],
      ["胃食管反流病", 20, "反酸烧心为主，避免饱餐、睡前进食与高脂饮食。"],
      ["胆囊 / 胰腺疾病", 12, "右上腹痛或进食油腻后加重，需腹部超声排查。"],
    ],
    tests: ["血常规 + C 反应蛋白", "便常规 + 潜血", "腹部超声", "幽门螺杆菌呼气试验（医生评估后）"],
    prep: ["记录症状与进食、排便的关系", "就诊前避免自行服用止痛药，以免掩盖病情", "如需腹部超声，当天保持空腹"],
    reds: ["腹痛剧烈、持续不缓解", "呕血或黑便", "腹部发硬、拒按", "伴高热或皮肤、眼睛发黄"],
  },
  {
    keys: ["视力模糊", "眼干", "眼痛", "复视", "畏光", "流泪", "听力下降", "耳鸣"],
    dept: "眼科",
    alt: "听力下降为主可考虑耳鼻喉科",
    urg: "黄色 · 建议 1 周内就诊",
    echo: "眼 / 耳症状",
    suspects: [
      ["干眼症", 32, "眼干、异物感，长时间用屏后加重，注意休息与人工泪液。"],
      ["屈光不正（近视 / 远视变化）", 26, "视物模糊但休息后好转，验光即可明确。"],
      ["视疲劳", 20, "与用眼过度、睡眠不足相关，先调整用眼习惯观察 1–2 周。"],
      ["眼表炎症（结膜炎等）", 13, "伴眼红、分泌物增多时需要眼科裂隙灯检查。"],
    ],
    tests: ["视力 + 验光检查", "眼压测量", "泪膜破裂时间（干眼评估）", "裂隙灯检查"],
    prep: ["就诊前停戴隐形眼镜 1–2 天", "记录症状与用屏时长的关系", "带上既往验光单（如有）"],
    reds: ["视力突然下降或视野缺损", "眼痛伴剧烈头痛、恶心", "眼睛红痛伴大量脓性分泌物", "外伤后视物异常"],
  },
  {
    keys: ["皮疹", "瘙痒", "关节痛", "水肿", "体重下降", "盗汗", "乏力"],
    dept: "全科医疗科",
    alt: "关节肿痛明显可考虑风湿免疫科",
    urg: "黄色 · 建议 1 周内就诊",
    echo: "皮肤 / 全身症状",
    suspects: [
      ["过敏性皮疹 / 荨麻疹", 34, "与食物、药物或接触物相关，注意记录发作前 24 小时接触史。"],
      ["骨关节炎 / 劳损", 25, "关节痛在活动后加重、休息缓解，可先减少负重活动。"],
      ["甲状腺功能异常", 20, "乏力、体重变化、水肿都可能与甲状腺相关，抽血即可初筛。"],
      ["贫血或慢性消耗性疾病", 11, "持续乏力、体重下降需血常规等基础检查排查。"],
    ],
    tests: ["血常规 + 尿常规", "甲状腺功能（TSH 等）", "类风湿因子 + CRP（关节痛时）", "肝肾功能"],
    prep: ["皮疹拍照记录形态与分布变化", "记录体重变化曲线", "列出近期新增的药物 / 食物"],
    reds: ["皮疹伴发热、关节肿痛", "突发全身风团伴喉头发紧、呼吸困难", "单侧小腿肿胀疼痛（警惕血栓）", "体重短期内快速下降"],
  },
];

const FALLBACK: Rule = {
  dept: "全科医疗科",
  alt: "也可先到内科门诊",
  urg: "黄色 · 建议 1 周内就诊",
  echo: "综合评估",
  keys: [],
  suspects: [
    ["信息不足，需补充描述", 60, "补充时间、部位、诱因、伴随症状与已测指标，判断会明显更准。"],
    ["常见感染 / 疲劳相关", 24, "注意休息与补水，观察 1–2 天症状变化。"],
    ["慢性病早期表现", 9, "如症状持续超过 2 周或进行性加重，建议面诊评估。"],
  ],
  tests: ["血常规 + 尿常规", "血糖血脂", "基础体格检查"],
  prep: ["补充症状的持续时间、部位与诱因", "记录体温变化", "带上既往病史资料"],
  reds: ["症状进行性加重或持续不缓解", "出现高热、意识改变等危险信号", "突发剧烈疼痛或功能障碍"],
};

const text = ref("");
const selected = ref<string[]>([]);
const busy = ref(false);

interface Bubble {
  id: number;
  role: "user" | "bot";
  html?: string;
  typing?: boolean;
}
const bubbles = ref<Bubble[]>([]);
const flowEl = ref<HTMLDivElement | null>(null);
let seq = 0;

const canRun = computed(() => text.value.trim().length > 0 && !busy.value);

function toggleChip(word: string) {
  const idx = selected.value.indexOf(word);
  if (idx >= 0) {
    selected.value.splice(idx, 1);
    text.value = text.value
      .replace(new RegExp(`[、，,]?\\s*${word}\\s*[、，,]?`, "g"), " ")
      .replace(/\s+/g, " ")
      .replace(/^[、，,\s]+|[、，,\s]+$/g, "");
  } else {
    selected.value.push(word);
    const cur = text.value.trim();
    const sep = cur && !/[、，,]\s*$/.test(cur) ? "，" : "";
    text.value = cur + sep + word;
  }
}

function addTemplate(tpl: string) {
  text.value = text.value.trim() + tpl;
}

function clearAll() {
  text.value = "";
  selected.value = [];
}

async function scrollFlow() {
  await nextTick();
  flowEl.value?.scrollTo({ top: flowEl.value.scrollHeight, behavior: "smooth" });
}

function push(msg: Omit<Bubble, "id">) {
  const id = ++seq;
  bubbles.value.push({ ...msg, id });
  void scrollFlow();
  return id;
}

function replace(id: number, msg: Omit<Bubble, "id">) {
  const i = bubbles.value.findIndex((b) => b.id === id);
  if (i >= 0) bubbles.value[i] = { ...msg, id };
  void scrollFlow();
}

function match(txt: string): { rule: Rule; hits: string[] } {
  let best = FALLBACK;
  let bestHits: string[] = [];
  for (const r of RULES) {
    const hits = r.keys.filter((k) => txt.includes(k));
    if (hits.length > bestHits.length) {
      best = r;
      bestHits = hits;
    }
  }
  return { rule: best, hits: bestHits };
}

/** 优先调大模型结构化分诊；失败降级到本地规则引擎（保证演示永不空转） */
async function run() {
  const txt = text.value.trim();
  if (!txt || busy.value) return;
  busy.value = true;
  bubbles.value = [];

  const escaped = txt.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const brief = escaped.length > 60 ? `${escaped.slice(0, 60)}…` : escaped;
  const m = match(txt);

  push({ role: "user", html: `<p>${brief}</p>` });
  const loadId = push({
    role: "bot",
    html: `<p>已收到你的描述，正在结合分诊知识库分析…</p><div class="typing"><i></i><i></i><i></i></div>`,
  });

  let rule = m.rule;
  let echo = m.hits.length ? m.rule.echo : m.rule.echo;
  let source = "规则引擎";
  let alarm = "";
  try {
    const res = await api<{
      dept?: string;
      urg?: string;
      alt?: string;
      echo?: string;
      suspects?: [string, number, string][];
      tests?: string[];
      prep?: string[];
      reds?: string[];
      degraded?: boolean;
      source?: string;
      safety?: { floor?: string; raised?: boolean; flags?: { label?: string; evidence?: string; severity?: string }[]; basis?: { title?: string }[] };
    }>("/api/ai/symptom", { method: "POST", body: { text: txt } });
    // 红旗闸门直接给出的急症卡故意不带「可能性百分比」（suspects 为空）：
    // 之前只认 suspects 非空，会把急症结论丢掉、退回本地规则——这里必须采用。
    const gate = res.source === "safety_gate";
    const flags = res.safety?.flags ?? [];
    if (flags.length) {
      const red = res.safety?.floor === "red";
      alarm =
        `<div class="inline-red"><h5>${red ? "红旗预警 · 请立即行动" : "红旗信号 · 规则检测"}</h5><ul>` +
        (red ? "<li>请立即拨打 120 或前往急诊，不要自行驾车。</li>" : "") +
        flags
          .slice(0, 4)
          .map((f) => `<li>${attr(f.label || "")}${f.evidence ? `（命中：${attr(f.evidence)}）` : ""}</li>`)
          .join("") +
        basisItem(res.safety?.basis) +
        "</ul></div>";
    }
    if (res.suspects?.length || gate) {
      source = gate ? "红旗规则（未调用大模型）" : res.degraded ? "知识库规则（大模型暂不可用）" : "大模型";
      rule = {
        ...rule,
        dept: res.dept || rule.dept,
        urg: res.urg || rule.urg,
        alt: res.alt || rule.alt,
        echo: res.echo || rule.echo,
        suspects: res.suspects ?? [],
        tests: res.tests?.length ? res.tests : rule.tests,
        prep: res.prep?.length ? res.prep : rule.prep,
        reds: res.reds?.length ? res.reds : rule.reds,
      };
      echo = res.echo || rule.echo;
    }
  } catch {
    /* 大模型不可用：保留规则结果 */
  }
  echo = rule.echo;

  const head = m.hits.length
    ? `<p>已收到你的描述：<strong>${m.hits.join(" · ")}</strong>，识别到 ${m.hits.length} 个关键症状，初步归入「${echo}」。</p>`
    : `<p>已收到你的描述：<strong>${brief}</strong>，暂未匹配到典型症状关键词，将按综合方向分析。</p>`;

  const suspectsHtml = rule.suspects.length
    ? `<p style="margin-top:12px;"><strong>疑似方向（按可能性排序）：</strong></p>` +
      `<div class="inline-notes">` +
      rule.suspects
        .map(
          (s, i) =>
            `<div class="note"><b><span>${i + 1} · ${s[0]}</span><span class="pct">可能性 ${s[1]}%</span></b><p>${s[2]}</p></div>`,
        )
        .join("") +
      `</div>`
    : "";
  const resultHtml =
    alarm +
    `<p>以下是<strong>分诊结果</strong>：</p>` +
    `<div class="inline-result"><div class="lbl">分诊结论</div><div class="dept">${rule.dept}</div>` +
    `<div class="urg">${rule.urg} · ${rule.alt}</div></div>` +
    suspectsHtml +
    `<p style="margin-top:12px;"><strong>建议检查：</strong></p>` +
    `<div class="sx-pills">${rule.tests.map((t) => `<i>${t}</i>`).join("")}</div>` +
    `<div class="inline-tips"><h6>就诊准备 · 建议这样做</h6><ul>${rule.prep.map((p) => `<li>${p}</li>`).join("")}</ul></div>` +
    `<div class="inline-red"><h5>红旗信号 · 出现请立即就医</h5><ul>${rule.reds.map((x) => `<li>${x}</li>`).join("")}</ul></div>` +
    `<p style="margin-top:10px;font-size:11.5px;color:var(--faint)">分诊来源：${source}</p>` +
    `<div class="sx-acts"><button type="button" data-act="hospital" data-dept="${attr(rule.dept)}">找附近医院 →</button></div>`;

  replace(loadId, { role: "bot", html: head + resultHtml });
  busy.value = false;

  // 结果内「找附近医院」按钮
  await nextTick();
  flowEl.value?.querySelectorAll<HTMLButtonElement>("[data-act='hospital']").forEach((b) => {
    b.onclick = () => emit("go", "hospital", b.dataset.dept || "");
  });
}

function onFlowClick(e: MouseEvent) {
  const btn = (e.target as HTMLElement).closest<HTMLButtonElement>("[data-act='hospital']");
  if (btn) emit("go", "hospital", btn.dataset.dept || "");
}

// 工作台 / 使用指南的「填入示例」：切到本页时把示例文字放进输入框（不自动提交，是否发送由用户决定）
const wbStore = useWorkbenchStore();
watch(
  () => wbStore.page,
  (p) => {
    if (p !== "symptom") return;
    const t = wbStore.takeText("symptom");
    if (t) text.value = t;
  },
  { immediate: true },
);
</script>

<template>
  <div class="page-t">
    <div>
      <h1 class="engrave">症状分诊</h1>
      <p>描述你的症状，AI 结合规则引擎给出疑似方向、建议科室与紧急程度</p>
    </div>
  </div>
  <div class="frame">
    <div class="canvas">
      <div class="two-col">
        <div>
          <div class="plate" style="padding: 20px">
            <div class="sec-h"><h3>描述症状</h3><span class="side">支持自然语言 · 越具体越准</span></div>
            <textarea
              v-model="text"
              class="sx-input"
              aria-label="症状描述输入框，请描述症状出现时间、部位、诱因与伴随情况"
              placeholder="例如：最近三天头晕，早上起床时明显，没有呕吐，血压 130/85，既往有高血压……"
            ></textarea>

            <div v-for="g in GROUPS" :key="g.title" class="chip-group">
              <div class="chip-group-title">{{ g.title }} <span v-if="g.hint" class="cnt">{{ g.hint }}</span></div>
              <div class="sx-chips">
                <button
                  v-for="w in g.items"
                  :key="w"
                  class="sx-chip"
                  :class="{ on: selected.includes(w) }"
                  type="button"
                  @click="toggleChip(w)"
                >
                  {{ w }}
                </button>
                <button v-if="g.title === '其他'" class="sx-chip more" type="button" @click="($event.target as HTMLElement).blur()">
                  + 更多症状
                </button>
              </div>
            </div>

            <div class="guide">
              <div class="gem-avatar sm"><div class="dia"></div></div>
              <div class="txt">
                <b>不知道怎么描述？试试按这几点补充</b>
                <p>时间、部位、诱因、伴随症状、已测指标——填得越全，判断越准。</p>
                <div class="tpl">
                  <button type="button" @click="addTemplate('，持续了 天')">多久了</button>
                  <button type="button" @click="addTemplate('，在 情况下明显')">什么情况下明显</button>
                  <button type="button" @click="addTemplate('，还伴有 ')">有没有伴随症状</button>
                  <button type="button" @click="addTemplate('，最近测血压 / 血糖是 ')">最近测的指标</button>
                  <button type="button" @click="addTemplate('，既往有 ')">既往病史</button>
                </div>
              </div>
            </div>

            <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px">
              <button class="btn-silver" type="button" @click="clearAll">清空</button>
              <button class="btn-metal" type="button" :disabled="!canRun" @click="run">
                <svg viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
                <span>{{ busy ? "分析中…" : "开始分诊" }}</span>
              </button>
            </div>
          </div>
          <div class="disclaimer" style="margin-top: 14px">本结果仅为筛查参考，不是诊断，需医生确认。急症请立即拨打 120。</div>
        </div>

        <div ref="flowEl" class="out-side" @click="onFlowClick">
          <div v-if="!bubbles.length" class="plate" style="text-align: center; padding: 46px 20px">
            <div class="gem-avatar" style="margin: 0 auto 14px"><div class="dia"></div></div>
            <div style="font-size: 13px; color: var(--muted); line-height: 1.8">
              在左侧描述症状后，点击「开始分诊」<br />结果会以对话形式显示在这里
            </div>
          </div>
          <div v-for="b in bubbles" :key="b.id" class="bubble-row" :class="{ me: b.role === 'user' }">
            <div class="gem-avatar"><div class="dia"></div></div>
            <div class="bubble-content">
              <div class="bubble" v-html="b.html"></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
