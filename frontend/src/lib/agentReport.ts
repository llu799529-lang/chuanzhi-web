/**
 * Agent 报告的文本与卡片渲染。
 *
 * 版式**逐字对齐** frontend-legacy/js/app.js 的 symptomAiReport / aiImageReport：
 * 同一个 result-card、data-block、advice-block 结构，同样的类名，所以样式表里的
 * 规则（蓝色渐变大卡、浅蓝数据块）能原样命中。不要在这里自创卡片结构——
 * 一旦换类名，Vue 版就会和旧版长得不一样。
 *
 * 注意：外层气泡由 ChatPage 的模板统一包（<div class="msg-bubble" v-html>），
 * 这里只返回**气泡内部**的内容，不要再包一层 msg-bubble。
 */

/** 工具名 → 中文描述。与旧版 AGENT_TOOLS 完全一致。 */
export const AGENT_TOOL_DESC: Record<string, string> = {
  get_history: "查询历史记录",
  analyze_image: "图像分析 · 自动判别",
  search_kb: "知识库 RAG 检索",
  calc_risk: "进展风险评估",
  find_hospital: "附近医院检索",
  ask_user: "向用户追问",
};

const ESC: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(input: string): string {
  return String(input ?? "").replace(/[&<>"']/g, (ch) => ESC[ch] ?? ch);
}

/**
 * 轻量 Markdown → HTML。只处理 LLM 实际会吐的几种：
 * **粗体**、`行内代码`、- / 1. 列表、空行分段。
 * 先整体转义再做替换，所以替换出的标签一定是我们自己生成的，内容里的
 * <script> 早已变成 &lt;script&gt;。
 */
export function formatChatText(text: unknown): string {
  const raw = typeof text === "string" ? text : "";
  if (!raw.trim()) return "";

  const inline = (s: string): string =>
    escapeHtml(s)
      .replace(/`([^`]+)`/g, '<code class="md-code">$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      // 知识库引用编号 [1] → 上标。编号是否真实存在由后端校验并清理（citations.sanitize），这里只负责展示。
      .replace(/\[(\d{1,2})\]/g, '<sup class="cite" title="知识库依据 $1">[$1]</sup>')
      .replace(/(?<![*\w])\*([^*\n]+)\*(?!\*)/g, "<em>$1</em>");

  const out: string[] = [];
  let list: "ul" | "ol" | null = null;

  const closeList = (): void => {
    if (list) {
      out.push(`</${list}>`);
      list = null;
    }
  };

  for (const line of raw.split(/\r?\n/)) {
    const t = line.trim();
    if (!t) {
      closeList();
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(t);
    if (heading) {
      closeList();
      const level = Math.min(heading[1].length + 2, 5);
      out.push(`<h${level} class="md-h">${inline(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = /^[-*·]\s+(.*)$/.exec(t);
    if (bullet) {
      if (list !== "ul") {
        closeList();
        out.push('<ul class="md-list">');
        list = "ul";
      }
      out.push(`<li>${inline(bullet[1])}</li>`);
      continue;
    }
    const ordered = /^(\d+)[.)]\s+(.*)$/.exec(t);
    if (ordered) {
      if (list !== "ol") {
        closeList();
        out.push('<ol class="md-list">');
        list = "ol";
      }
      out.push(`<li>${inline(ordered[2])}</li>`);
      continue;
    }
    closeList();
    out.push(`<p>${inline(t)}</p>`);
  }
  closeList();
  return out.join("");
}

/* ---------------- 类型守卫 ---------------- */

function rec(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function str(v: unknown): string {
  return typeof v === "string" ? v : typeof v === "number" ? String(v) : "";
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function list(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function strList(v: unknown): string[] {
  return list(v)
    .map((x) => (typeof x === "string" ? x : ""))
    .filter((x) => x.length > 0);
}

const DR_SHORT = ["无病变", "轻度非增殖期", "中度非增殖期", "重度非增殖期", "增殖期"];
const LESION_CLS = ["hot", "red", "yellow", "blue"];

function confidenceText(v: unknown): string {
  const n = num(v);
  if (n === null) return "";
  return n <= 1 ? `${(n * 100).toFixed(1)}%` : `${n}`;
}

const DISCLAIMER =
  '<p style="margin-top:12px;font-size:10.5px;color:var(--faint);text-align:center;' +
  'letter-spacing:.02em;">AI 输出仅为筛查参考，不是诊断，需医生确认 · 急症请拨打 120</p>';

/* ---------------- 复用的段落 ---------------- */

/** 建议科室大卡（蓝色渐变）—— 三种报告共用，字段名不同。 */
function resultCard(opts: {
  dept: string;
  urg: string;
  conf?: string;
}): string {
  return (
    '<div class="result-card">' +
    '<div class="lbl">建议就诊科室</div>' +
    `<div class="dept">${escapeHtml(opts.dept)}</div>` +
    `<div class="urg">${escapeHtml(opts.urg)}</div>` +
    (opts.conf ? `<span class="conf">${escapeHtml(opts.conf)}</span>` : "") +
    "</div>"
  );
}

/** 只读的条目行（rk + rv），用于「建议检查」「指标解读」「知识库参考」。 */
function dataRow(rk: string, rv: string, warn = false): string {
  return (
    `<div class="data-row"><span class="rk">${escapeHtml(rk)}</span>` +
    `<span class="rv${warn ? " warn" : ""}">${rv}</span></div>`
  );
}

/** 带圆点的风险 / 疑似方向行。 */
function riskRow(dot: string, name: string, desc: string, tag: string, bold = false): string {
  dot = ["high", "mid", "low"].includes(dot) ? dot : "low";
  return (
    `<div class="risk-row"><span class="dot ${dot}"></span>` +
    `<span class="n">${bold ? `<b>${escapeHtml(name)}</b>` : escapeHtml(name)}${desc ? ` · ${escapeHtml(desc)}` : ""}</span>` +
    `<span class="tag ${dot}">${escapeHtml(tag)}</span></div>`
  );
}

/** 带标题的建议块（就诊准备 / 下一步建议 / 红旗信号）。 */
function adviceBlock(title: string, when: string, items: string[], urgent = false): string {
  return (
    `<div class="advice-block"${urgent ? ' style="border-left-color:#D9443C;"' : ""}>` +
    `<div class="head"><b>${escapeHtml(title)}</b>` +
    `<span class="when${urgent ? " red" : ""}">${escapeHtml(when)}</span></div>` +
    "<ul>" +
    items.map((x) => `<li>${escapeHtml(x)}</li>`).join("") +
    "</ul></div>"
  );
}

/* ---------------- 各 kind 的报告 ---------------- */

/** 纯聊天：就是一段话，不套卡片。 */
function chatText(plain: string): string {
  return formatChatText(plain);
}

/** 非医疗图片：说明 + 下一步。 */
function otherReport(d: Record<string, unknown>, plain: string): string {
  const advice = strList(d.advice);
  return (
    (plain ? formatChatText(plain) : `<p>${escapeHtml(str(d.summary) || "这张图片不是眼底彩照或化验单，无法进行医疗筛查分析。")}</p>`) +
    adviceBlock("下一步", "重新上传", advice.length ? advice : ["请上传眼底彩照或化验单照片"]) +
    DISCLAIMER
  );
}

/** 眼底：分析完成 → 科室大卡 → 分级概率 → 病灶 → 分级依据 → 危险因素 → 建议。 */
function fundusReport(d: Record<string, unknown>): string {
  const parts: string[] = [];

  parts.push(
    "<p>分析完成。" + (str(d.summary) ? escapeHtml(str(d.summary)) : "这张眼底彩照的<strong>详细报告</strong>如下：") + "</p>",
  );

  const conf = confidenceText(d.confidence);
  parts.push(
    resultCard({
      dept: str(d.department) || "眼科",
      urg: str(d.urgency_label),
      conf: conf ? `置信度 ${conf} · ${d.engine === "local" ? "本地专用分级模型" : "大模型视觉分析"}` : "",
    }),
  );

  const probs = list(d.probabilities).map((x) => num(x) ?? 0);
  if (probs.length) {
    const level = num(d.level);
    const rows = probs
      .map((p, i) => {
        const hl = i === level ? " hl" : "";
        return (
          '<div class="prob-row"><div class="top">' +
          `<span class="k">DR ${i} · ${escapeHtml(DR_SHORT[i] ?? "")}</span>` +
          `<span class="v${hl}">${p}%</span></div>` +
          `<div class="bar"><i${i === level ? "" : ' class="gray"'} style="width:${Math.min(p, 100)}%"></i></div></div>`
        );
      })
      .join("");
    parts.push(
      '<div class="data-block"><div class="k">DR 分级概率 <span class="tag">' +
        (d.engine === "local" ? "EfficientNet-B3 本地模型" : "大模型视觉分析") +
        `</span></div>${rows}</div>`,
    );
  }

  const lesions = list(d.lesions).map(rec).filter((l) => str(l.type));
  if (lesions.length) {
    const rows = lesions
      .map(
        (l, i) =>
          `<div class="lesion ${LESION_CLS[i % 4]}">` +
          `<span class="num">${String(i + 1).padStart(2, "0")}</span>` +
          `<div class="body"><b>${escapeHtml(str(l.type))} × ${num(l.count) ?? 0}</b>` +
          `<span>${escapeHtml(str(l.desc))}</span></div>` +
          `<span class="loc">${escapeHtml(str(l.loc))}</span></div>`,
      )
      .join("");
    parts.push(
      `<div class="data-block"><div class="k">病灶检出 <span class="tag">模型定位</span></div><div class="lesion-list">${rows}</div></div>`,
    );
  }

  const criteria = list(d.criteria).map(rec).filter((c) => str(c.text));
  if (criteria.length) {
    const rows = criteria
      .map(
        (c) =>
          `<div class="cri ${c.hit ? "ok" : "no"}"><span class="ck">${c.hit ? "✓" : "–"}</span>` +
          `<span class="tx">${escapeHtml(str(c.text))}</span></div>`,
      )
      .join("");
    const level = num(d.level);
    parts.push(
      `<div class="data-block"><div class="k">分级依据 <span class="tag">DR ${level ?? "–"} · ${escapeHtml(
        str(d.level_label) || DR_SHORT[level ?? 0] || "",
      )}</span></div><div class="criteria">${rows}</div></div>`,
    );
  }

  const risks = list(d.risks).map(rec).filter((r) => str(r.text));
  if (risks.length) {
    const rows = risks
      .map((r) => {
        const lv = str(r.level) || "low";
        return riskRow(lv, str(r.text), "", str(r.tag) || "关注");
      })
      .join("");
    parts.push(`<div class="data-block"><div class="k">危险因素评估</div>${rows}</div>`);
  }

  const advice = strList(d.advice);
  parts.push(
    adviceBlock("下一步建议", str(d.followup) || "遵医嘱复查", advice.length ? advice : ["按建议科室就诊，携带本次筛查报告"]),
  );

  parts.push(DISCLAIMER);
  return parts.join("");
}

/** 化验单：识别完成 → 科室大卡 → 指标解读 → 综合判断 → 建议。 */
function labReport(d: Record<string, unknown>): string {
  const parts: string[] = [];

  parts.push(
    `<p>识别完成。这张「${escapeHtml(str(d.report_title) || "检验报告")}」的<strong>详细报告</strong>如下：</p>`,
  );

  parts.push(
    resultCard({
      dept: str(d.department) || "全科",
      urg: str(d.urgency_label),
      conf: `${num(d.abnormal_count) ?? 0} 项指标异常`,
    }),
  );

  const items = list(d.items).map(rec).filter((it) => str(it.name));
  if (items.length) {
    const rows = items
      .map((it) => {
        const flag = str(it.flag).toLowerCase();
        const warn = flag === "high" || flag === "low";
        const arrow = flag === "high" ? " ↑" : flag === "low" ? " ↓" : "";
        const unit = str(it.unit) ? ` ${escapeHtml(str(it.unit))}` : "";
        const ref = str(it.ref) ? `（参考 ${escapeHtml(str(it.ref))}）` : "";
        const check = str(rec(it.check).text);
        const chk = check ? ` <span class="chk" title="${escapeHtml(check)}">⚠ 请核对</span>` : "";
        return dataRow(
          str(it.name),
          `${escapeHtml(str(it.value))}${unit}${arrow}${ref}${chk}`,
          warn || !!check,
        );
      })
      .join("");
    parts.push(
      `<div class="data-block"><div class="k">指标解读 <span class="tag">OCR · ${items.length} 项</span></div>${rows}</div>`,
    );
    const nChk = items.filter((it) => str(rec(it.check).text)).length;
    if (nChk) {
      parts.push(
        `<p class="chk-note">⚠ ${nChk} 项识别结果与单位、参考范围或人体可能范围对不上（标有“请核对”）：请对照化验单原件核对这些数字。</p>`,
      );
    }
  }

  // 后端有两种写法：{text, level, tag} 与 {q, a}（见 maps q/a judgment fields 测试），统一成同一形状。
  const judgments = list(d.judgments)
    .map(rec)
    .map((j) => ({ level: str(j.level), tag: str(j.tag), text: str(j.text) || str(j.a) }))
    .filter((j) => j.text);
  if (judgments.length) {
    const rows = judgments
      .map((j) => riskRow(j.level || "low", j.text, "", j.tag || "关注"))
      .join("");
    parts.push(`<div class="data-block"><div class="k">综合判断</div>${rows}</div>`);
  }

  const advice = strList(d.advice);
  parts.push(
    adviceBlock("下一步建议", str(d.followup) || "2 周内", advice.length ? advice : ["携带报告原件，按医嘱复查异常指标"]),
  );

  parts.push(DISCLAIMER);
  return parts.join("");
}

/** 症状：描述 → 科室大卡 → 疑似方向 → 建议检查 → 知识库 → 就诊准备 → 红旗信号。 */
function symptomReport(d: Record<string, unknown>): string {
  const parts: string[] = [];

  const hits = strList(d.hits);
  if (hits.length) {
    parts.push(
      `<p>已收到你的描述，识别到 <strong>${escapeHtml(hits.join(" · "))}</strong>，初步归入「${escapeHtml(
        str(d.echo) || "症状分诊",
      )}」。</p>`,
    );
  } else {
    parts.push("<p>已收到你的描述，以下是大模型的<strong>分诊分析</strong>：</p>");
  }

  parts.push(
    resultCard({
      dept: str(d.dept) || "全科",
      urg: str(d.urg) + (str(d.alt) ? ` · ${str(d.alt)}` : ""),
    }),
  );

  const suspects = list(d.suspects).map((x) => list(x));
  const suspectRows = suspects
    .map((s, i) => {
      const name = str(s[0]);
      const pct = num(s[1]);
      const desc = str(s[2]);
      if (!name) return "";
      const dot = i === 0 ? "mid" : "low";
      return riskRow(dot, name, desc, pct === null ? "–" : `${pct}%`, true);
    })
    .join("");
  if (suspectRows) {
    parts.push(
      `<div class="data-block"><div class="k">疑似方向 <span class="tag">按可能性排序</span></div>${suspectRows}</div>`,
    );
  }

  const tests = strList(d.tests);
  if (tests.length) {
    const rows = tests
      .map((t, i) => dataRow(`0${i + 1}`, escapeHtml(t)))
      .join("");
    parts.push(`<div class="data-block"><div class="k">建议检查</div>${rows}</div>`);
  }

  const kb = list(d.kb_hits).map(rec).filter((r) => str(r.dept) || str(r.category));
  if (kb.length) {
    const rows = kb
      .map((r) =>
        dataRow(
          str(r.dept),
          escapeHtml(str(r.category)) +
            (strList(r.matched).length
              ? ` · 命中：<strong>${escapeHtml(strList(r.matched).join("、"))}</strong>`
              : "") +
            // 参考依据是「主题级」文献名，只表示该主题有可对照的指南/共识，不代表这条内容逐句出自它。
            (strList(r.source).length
              ? `<br><span style="color:var(--faint);font-size:11px;">参考文献：${escapeHtml(strList(r.source)[0])}</span>`
              : ""),
        ),
      )
      .join("");
    parts.push(
      `<div class="data-block"><div class="k">知识库参考 <span class="tag">RAG 检索 · 内置医学知识库</span></div>${rows}</div>`,
    );
  }

  const prep = strList(d.prep);
  if (prep.length) parts.push(adviceBlock("就诊准备", "建议这样做", prep));

  const reds = strList(d.reds);
  if (reds.length) parts.push(adviceBlock("红旗信号 · 出现请立即就医", "紧急", reds, true));

  parts.push(DISCLAIMER);
  return parts.join("");
}

/**
 * `final` 事件 → 气泡内部 HTML（不含外层 msg-bubble）。
 *
 * 入参是 SSE 里 `final` 的整体 data：{ kind, plain, data, risk?, guard?, acts? }。
 * `data` 是嵌套的（后端 _final_data 的返回值），业务字段都在这一层下面。
 */
export function renderAgentReport(payload: Record<string, unknown>): string {
  const kind = str(payload.kind) || "symptom";
  const d = rec(payload.data);
  const plain = str(payload.plain);

  if (kind === "chat") return chatText(plain);
  const banner = statusBanner(payload);
  const foot = citationsBlock(payload) + reflectionFooter(payload);
  if (kind === "other") return banner + otherReport(d, plain) + foot;
  if (kind === "fundus") return banner + (Object.keys(d).length ? fundusReport(d) : formatChatText(plain)) + foot;
  if (kind === "lab") return banner + (Object.keys(d).length ? labReport(d) : formatChatText(plain)) + foot;
  return banner + (Object.keys(d).length ? symptomReport(d) : formatChatText(plain)) + foot;
}

/**
 * `final` 事件拆成「文字气泡」+「结构化卡片」两部分。
 *
 * 之前有结构化数据时，卡片会**整个替换**掉流式生成的文字：用户看着一段话逐字出现，final 一到就消失，
 * Agent 最有特色的「大白话综合报告」最终看不到。现在有卡片且有文字时，文字单独留作一个气泡，卡片另起一个；
 * 没有卡片（纯文字/导航类）或 chat 类仍是单个气泡。`card` 永远是原来的 renderAgentReport 输出（保持渲染一致）。
 */
export function splitFinal(payload: Record<string, unknown>): { prose: string; card: string } {
  const kind = str(payload.kind) || "symptom";
  const plain = str(payload.plain).trim();
  const hasCard = kind !== "chat" && Object.keys(rec(payload.data)).length > 0;
  return { prose: hasCard && plain ? formatChatText(plain) : "", card: renderAgentReport(payload) };
}

const SAFE_URL = /^https?:\/\/[^\s"'<>]+$/i;

/**
 * 报告底部的「参考依据」：检索到的知识库条目（带编号）、每条的参考文献、可点开的核实链接。
 * 链接只放行 http(s)；点击新开页且 noopener。没有 `citations` 字段（旧载荷 / 无检索）返回空串。
 */
export function citationsBlock(payload: Record<string, unknown>): string {
  const c = rec(payload.citations);
  const evidence = list(c.evidence).map(rec).filter((e) => num(e.n) !== null && str(e.category));
  if (!evidence.length) return "";
  const rows = evidence
    .map((e) => {
      const srcs = list(e.sources)
        .map(rec)
        .filter((s) => str(s.title))
        .slice(0, 2)
        .map((s) => {
          const title = str(s.title);
          const shown = title.startsWith("《") || /^[\x00-\x7f]/.test(title) ? title : `《${title}》`;
          const meta = [str(s.issuer), s.year != null ? String(s.year) : ""].filter(Boolean).join("；");
          const url = str(s.verify_url);
          const link = SAFE_URL.test(url)
            ? ` <a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">核实 ↗</a>`
            : "";
          return `<div class="cite-src">${escapeHtml(shown)}${meta ? `（${escapeHtml(meta)}）` : ""}${link}</div>`;
        })
        .join("");
      const dept = str(e.dept);
      return dataRow(
        `[${num(e.n)}]`,
        escapeHtml(str(e.category)) +
          (dept ? ` → ${escapeHtml(dept)}` : "") +
          (e.cited === true ? ' <span class="tag">已引用</span>' : "") +
          srcs,
      );
    })
    .join("");
  const notes: string[] = [];
  const invalid = list(c.invalid_removed).filter((x) => typeof x === "number");
  if (invalid.length) notes.push(`已清除 ${invalid.length} 个不存在的引用编号（${invalid.join("、")}）。`);
  const sup = rec(c.support);
  if (num(sup.checked)) {
    notes.push(`${num(sup.supported) ?? 0}/${num(sup.checked)} 处引用在句中能找到该条目的术语（下界，不是正确率）。`);
  }
  notes.push("参考文献为主题级：只表示该主题有可对照的指南 / 共识，并不代表这句话逐字出自该文献。");
  return (
    `<div class="data-block cite-block"><div class="k">参考依据 <span class="tag">知识库 · 可核实</span></div>${rows}` +
    `<div class="cite-note">${notes.map(escapeHtml).join("")}</div></div>`
  );
}

/**
 * 报告底部的自检摘要（后端 planner.reflect 的结果，规则核查，不是大模型自评）。
 * 有 warn/fail 时列出具体项；没有 `reflection` 字段的旧载荷返回空串。
 */
function repairNote(payload: Record<string, unknown>): string {
  const rp = rec(payload.repair);
  if (rp.attempted !== true) return "";
  const why = strList(rp.reasons).join("、") || "问题";
  return rp.accepted === true
    ? `。自检发现「${escapeHtml(why)}」，已据此重写一次并通过复检`
    : `。自检发现「${escapeHtml(why)}」，重写一次未改善，已保留原文并追加规则提示`;
}

export function reflectionFooter(payload: Record<string, unknown>): string {
  const checks = list(rec(payload.reflection).checks).map(rec).filter((c) => str(c.label));
  if (!checks.length) return "";
  const bad = checks.filter((c) => str(c.status) === "warn" || str(c.status) === "fail");
  let out = "";
  if (bad.length) {
    out +=
      '<div class="inline-tips"><h6>自检提示</h6><ul>' +
      bad.map((c) => `<li>${escapeHtml(str(c.label))}：${escapeHtml(str(c.detail))}</li>`).join("") +
      "</ul></div>";
  }
  out +=
    '<p style="margin-top:10px;font-size:11px;color:var(--faint);">' +
    `自检 · ${checks.length} 项核查：${checks.length - bad.length} 项通过 / ${bad.length} 项需留意（规则核查，不是大模型自评）` +
    repairNote(payload) +
    "</p>";
  return out;
}

/**
 * 报告顶部的状态条：这份报告**不是**大模型生成的时候必须说清楚。
 *   engine === "safety_gate"  确定性红旗规则直接给出的急症指引（没调模型）
 *   offline === true          大模型不可用，知识库 + 规则引擎生成（工具是真的，没有模型润色）
 *   safety_flags 非空         模型照常出了结果，但规则检测到红旗并已抬高紧急度
 * 后端没带这些字段（旧载荷）时返回空串，报告标记与之前逐字节一致。
 */
/** 红旗规则对应的国内指南（后端 safety_basis，主题级对应）；没有登记来源时不显示。 */
function basisLine(payload: Record<string, unknown>): string {
  const titles = list(payload.safety_basis).map(rec).map((b) => str(b.title)).filter(Boolean).slice(0, 3);
  return titles.length ? `<li class="basis">规则依据：${titles.map((t) => `《${escapeHtml(t)}》`).join("、")}</li>` : "";
}

export function statusBanner(payload: Record<string, unknown>): string {
  const flags = list(payload.safety_flags).map(rec).filter((f) => str(f.label));
  if (str(payload.engine) === "safety_gate") {
    return (
      '<div class="inline-red"><h5>红旗预警 · 请立即行动</h5><ul>' +
      "<li>请立即拨打 120 或前往急诊，不要自行驾车。</li>" +
      "<li>以下内容由内置确定性规则直接生成，未调用大模型，不是诊断。</li>" +
      basisLine(payload) +
      "</ul></div>"
    );
  }
  let out = "";
  if (flags.length) {
    const urgent = flags.some((f) => str(f.severity) === "emergency");
    out +=
      `<div class="inline-red"><h5>${urgent ? "红旗信号" : "需要留意的信号"} · 规则检测</h5><ul>` +
      flags
        .slice(0, 4)
        .map((f) => `<li>${escapeHtml(str(f.label))}${str(f.evidence) ? `（命中：${escapeHtml(str(f.evidence))}）` : ""}</li>`)
        .join("") +
      basisLine(payload) +
      "</ul></div>";
  }
  const addendum = str(rec(payload.reflection).addendum);
  if (addendum) {
    out += `<div class="inline-red"><h5>规则补充提示</h5><ul><li>${escapeHtml(addendum)}</li></ul></div>`;
  }
  if (payload.offline === true) {
    out +=
      '<div class="inline-tips"><h6>离线模式</h6><ul>' +
      "<li>大模型暂时不可用，以下由内置知识库与规则引擎生成，未经大模型润色，仅作筛查参考。</li></ul></div>";
  }
  return out;
}

/** 报告底部的动作按钮（渲染在气泡**外面**，与旧版 .acts 的位置一致）。 */
export interface ReportAct {
  t: string;
  a: string;
  dept?: string;
}

export function reportActs(payload: Record<string, unknown>): ReportAct[] {
  if (payload.kind === "chat") return [];
  const pages = new Set(["eye", "lab", "symptom", "history", "hospital"]);
  return list(payload.acts)
    .map(rec)
    .filter((a) => str(a.t) && pages.has(str(a.a)))
    .map((a) => ({ t: str(a.t), a: str(a.a), dept: str(a.dept) || undefined }));
}
