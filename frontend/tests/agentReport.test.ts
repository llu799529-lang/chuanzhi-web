import * as reportLib from "@/lib/agentReport";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { AGENT_TOOL_DESC, citationsBlock, formatChatText, reflectionFooter, renderAgentReport, reportActs, splitFinal } from "@/lib/agentReport";
const fixtures = JSON.parse(readFileSync(new URL("./fixtures/legacy-reports.json", import.meta.url), "utf8"));

describe("original workbench report parity", () => {
  it.each(fixtures)("$kind: preserves original markup, classes, ordering and all supplied values", (fixture) => {
    const payload = {kind:fixture.kind, data:fixture.data, plain:"这段额外生成的文字不能新增一块卡片"};
    const before = JSON.stringify(payload);
    expect(renderAgentReport(payload)).toBe(fixture.expected);
    expect(JSON.stringify(payload)).toBe(before);
  });
  it("does not nest a second bubble or introduce a summary card", () => {
    const html=renderAgentReport({kind:"symptom",data:fixtures[0].data,plain:"额外总结"});
    expect(html).not.toMatch(/msg-bubble|rp-hero|report-plain|AI 综合分析/);
  });
  it("keeps a text-only answer as text, without fabricating clinical fields", () => {
    const html=renderAgentReport({kind:"chat",plain:"你好 **朋友**"});
    expect(html).toBe("<p>你好 <strong>朋友</strong></p>");
    expect(renderAgentReport({kind:"symptom",data:{}})).not.toMatch(/0%|全科|2 周内|按建议科室/);
  });
  it("uses safe markup with exact supplied data, without executing source HTML", () => {
    const html=renderAgentReport({kind:"symptom",data:{dept:'<img src=x onerror="boom">',suspects:[['测试',35,'<script>']]} });
    expect(html).toContain("35%");
    expect(html).toContain("&lt;img");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<script>");
  });
  it("maps q/a judgment fields for actual backend reports", () => {
    const html=renderAgentReport({kind:"lab",data:{judgments:[{q:"指标为什么偏高？",a:"应结合其他检查",level:"mid"}]}});
    expect(html).toContain("应结合其他检查");
  });
  it("keeps actions outside the report and accepts only known navigation targets", () => {
    expect(reportActs({kind:"chat",acts:[{a:"eye",t:"眼底"}]})).toEqual([]);
    expect(reportActs({kind:"symptom",acts:[{a:"hospital",t:"附近医院",dept:"神经内科"},{a:"javascript:x",t:"错误"}]}))
      .toEqual([{a:"hospital",t:"附近医院",dept:"神经内科"}]);
  });
});

describe("safe text formatting", () => {
  it("formats paragraphs, bold and lists while escaping HTML", () => {
    const html=formatChatText("你好 **重点**\n第二行\n\n- 带报告\n- <img src=x>\n\n1. 先挂号\n2. 再就诊");
    expect(html).toContain("<strong>重点</strong>");
    expect(html).toContain("第二行");
    expect(html).toContain("<li>带报告</li>");
    expect(html).not.toContain("<img");
  });
  it.each([null,undefined,{},[],{text:"错误形状"}])("does not stringify unsupported input %j", value=> {
    expect(formatChatText(value)).toBe("");
  });
});
it("lists the actual six backend tools",()=>{
 expect(Object.keys(AGENT_TOOL_DESC)).toEqual(["get_history","analyze_image","search_kb","calc_risk","find_hospital","ask_user"]);
});

describe("status banner for non-LLM reports", () => {
  const data = { dept: "急诊科", urg: "红色", suspects: [] as unknown[] };
  it("is absent for legacy payloads (byte-for-byte unchanged)", () => {
    expect(renderAgentReport({ kind: "symptom", data })).not.toMatch(/inline-red"><h5>红旗|离线模式/);
  });
  it("shows an urgent banner for rule-gate reports and says no model was called", () => {
    const html = renderAgentReport({ kind: "symptom", data, engine: "safety_gate" });
    expect(html).toContain("120");
    expect(html).toContain("未调用大模型");
    expect(html.indexOf("inline-red")).toBeLessThan(html.indexOf("result-card"));
  });
  it("labels offline reports and escapes rule evidence from user text", () => {
    const html = renderAgentReport({
      kind: "symptom", data, offline: true,
      safety_flags: [{ label: "胸痛 / 胸闷", severity: "urgent", evidence: '<img src=x onerror="boom">' }],
    });
    expect(html).toContain("离线模式");
    expect(html).toContain("&lt;img");
    expect(html).not.toContain("<img");
  });
  it("never decorates plain chat replies", () => {
    expect(renderAgentReport({ kind: "chat", plain: "你好", offline: true })).toBe("<p>你好</p>");
  });
});

describe("reflection (rule-based self-check) rendering", () => {
  const data = { dept: "呼吸内科", urg: "黄色", suspects: [] as unknown[] };
  const reflection = {
    source: "rule", verdict: "attention",
    checks: [
      { id: "evidence", label: "必要证据", status: "ok", detail: "已检索知识库" },
      { id: "red_flag", label: "红旗提示", status: "fail", detail: "规则检测到红旗，但报告文字里没有就医提示" },
      { id: "grounding", label: "知识库落点", status: "info", detail: "1/3 句能在知识库找到落点（下界，不是正确率）" },
    ],
    addendum: "规则检测到：胸痛 / 胸闷。请尽快就医（橙色）<script>",
  };
  it("is absent for legacy payloads", () => {
    expect(renderAgentReport({ kind: "symptom", data })).not.toMatch(/自检|规则补充提示/);
    expect(reflectionFooter({ kind: "symptom" })).toBe("");
  });
  it("lists only the checks that need attention, counts info as passed, and says it is not LLM self-grading", () => {
    const html = renderAgentReport({ kind: "symptom", data, reflection });
    expect(html).toContain("自检提示");
    expect(html).toContain("红旗提示：规则检测到红旗");
    expect(html).not.toContain("必要证据：");
    expect(html).toContain("3 项核查：2 项通过 / 1 项需留意");
    expect(html).toContain("不是大模型自评");
  });
  it("puts the rule addendum above the report and escapes it", () => {
    const html = renderAgentReport({ kind: "symptom", data, reflection });
    expect(html.indexOf("规则补充提示")).toBeLessThan(html.indexOf("result-card"));
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
  });
  it("shows only the summary line when everything passes", () => {
    const html = renderAgentReport({ kind: "symptom", data, reflection: { checks: [{ label: "必要证据", status: "ok", detail: "x" }] } });
    expect(html).not.toContain("自检提示");
    expect(html).toContain("1 项核查：1 项通过 / 0 项需留意");
  });
  it("never decorates plain chat replies", () => {
    expect(renderAgentReport({ kind: "chat", plain: "你好", reflection })).toBe("<p>你好</p>");
  });
});

describe("knowledge-base reference line", () => {
  const base = { dept: "眼科", urg: "黄色", suspects: [] as unknown[] };
  it("is absent when the hit has no source (legacy payloads unchanged)", () => {
    const html = renderAgentReport({ kind: "symptom", data: { ...base, kb_hits: [{ category: "白内障", dept: "眼科", matched: ["看不清"] }] } });
    expect(html).toContain("白内障");
    expect(html).not.toContain("参考文献");
  });
  it("shows only the first source, escaped, and never claims verbatim origin", () => {
    const html = renderAgentReport({
      kind: "symptom",
      data: { ...base, kb_hits: [{ category: "青光眼", dept: "眼科", matched: [], source: ["《中国青光眼指南（2020年）》（某学会；2020）<b>", "《第二条》"] }] },
    });
    expect(html).toContain("参考文献：《中国青光眼指南（2020年）》");
    expect(html).toContain("&lt;b&gt;");
    expect(html).not.toContain("第二条");
    expect(html).not.toContain("<b>（");
  });
});

describe("inline citation markers", () => {
  it("turns [n] into a superscript marker and leaves other brackets alone", () => {
    const html = formatChatText("建议到呼吸内科就诊[1]，做胸片[2]。数组 [a] 和 [123] 不处理。");
    expect(html).toContain('<sup class="cite" title="知识库依据 1">[1]</sup>');
    expect(html).toContain('<sup class="cite" title="知识库依据 2">[2]</sup>');
    expect(html).toContain("[a]");
    expect(html).toContain("[123]");
    expect(html).not.toMatch(/<sup[^>]*>\[a\]/);
  });
  it("still escapes surrounding HTML", () => {
    const html = formatChatText("<img src=x onerror=1>[1]");
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img");
  });
});

describe("citationsBlock", () => {
  const evidence = [
    { n: 1, id: "K07", category: "咳嗽 · 咳痰", dept: "呼吸内科", cited: true,
      sources: [{ title: "咳嗽的诊断与治疗指南（2021）", issuer: "中华医学会呼吸病学分会哮喘学组", year: 2021, verify_url: "https://example.org/a" }] },
    { n: 2, id: "K27", category: "儿童发热 · 惊厥", dept: "儿科", cited: false, sources: [] },
  ];
  const payload = { kind: "symptom", data: { dept: "呼吸内科", urg: "黄色" }, citations: { evidence, cited: [1], invalid_removed: [], support: { checked: 2, supported: 1, unsupported: [] } } };
  it("is absent for legacy payloads and for empty evidence", () => {
    expect(citationsBlock({ kind: "symptom" })).toBe("");
    expect(citationsBlock({ citations: { evidence: [] } })).toBe("");
    expect(renderAgentReport({ kind: "symptom", data: { dept: "x" } })).not.toContain("参考依据");
  });
  it("lists every evidence entry, marks the cited ones, and shows the source with a verify link", () => {
    const html = citationsBlock(payload);
    expect(html).toContain("参考依据");
    expect(html).toContain("[1]");
    expect(html).toContain("咳嗽 · 咳痰 → 呼吸内科");
    expect(html).toContain("已引用");
    expect(html.match(/已引用/g)).toHaveLength(1);                 // 只有被引用的那条
    expect(html).toContain("《咳嗽的诊断与治疗指南（2021）》（中华医学会呼吸病学分会哮喘学组；2021）");
    expect(html).toContain('href="https://example.org/a" target="_blank" rel="noopener noreferrer"');
  });
  it("always states that the references are topic-level, and shows the support lower bound", () => {
    const html = citationsBlock(payload);
    expect(html).toContain("主题级");
    expect(html).toContain("1/2 处引用在句中能找到该条目的术语（下界，不是正确率）");
  });
  it("reports removed invalid markers", () => {
    const html = citationsBlock({ citations: { evidence, invalid_removed: [7, 9] } });
    expect(html).toContain("已清除 2 个不存在的引用编号（7、9）");
  });
  it.each(["javascript:alert(1)", "data:text/html,<script>1</script>", "//evil.example", "ftp://x", "https://a b", 'https://x"onmouseover="1'])(
    "never renders a link for unsafe url %j", (url) => {
      const html = citationsBlock({ citations: { evidence: [{ n: 1, category: "x", sources: [{ title: "T", verify_url: url }] }] } });
      expect(html).not.toContain("<a ");
      expect(html).not.toContain("javascript:");
    });
  it("escapes titles, issuers and categories", () => {
    const html = citationsBlock({ citations: { evidence: [{ n: 1, category: "<b>x</b>", dept: "<i>d</i>",
      sources: [{ title: "<script>1</script>", issuer: "<img src=x>", year: 2020, verify_url: "https://ok.example/p" }] }] } });
    expect(html).not.toMatch(/<(b|i|script|img)[ >]/);
    expect(html).toContain("&lt;script&gt;");
  });
  it("tolerates malformed evidence entries without throwing", () => {
    expect(() => citationsBlock({ citations: { evidence: [null, 1, "x", { n: "a" }, { n: 1 }, { n: 1, category: "ok", sources: [null, { title: "" }] }] } })).not.toThrow();
  });
  it("renderAgentReport places the citation block after the report and before the self-check", () => {
    const html = renderAgentReport({ ...payload, reflection: { checks: [{ label: "必要证据", status: "ok", detail: "x" }] } });
    expect(html.indexOf("result-card")).toBeLessThan(html.indexOf("参考依据"));
    expect(html.indexOf("参考依据")).toBeLessThan(html.indexOf("自检 ·"));
  });
});

describe("splitFinal", () => {
  const card = { dept: "呼吸内科", urg: "黄色", suspects: [] as unknown[] };
  it("keeps the model's prose as its own bubble when there is also a structured card", () => {
    const r = splitFinal({ kind: "symptom", plain: "建议先到呼吸内科[1]。", data: card });
    expect(r.prose).toContain('<sup class="cite"');
    expect(r.card).toContain("result-card");
    expect(r.card).not.toContain("建议先到呼吸内科");             // 卡片里不重复文字
  });
  it("has no separate prose for chat replies, text-only reports, or an empty plain", () => {
    expect(splitFinal({ kind: "chat", plain: "你好", data: card }).prose).toBe("");
    expect(splitFinal({ kind: "symptom", plain: "导航结果", data: {} }).prose).toBe("");
    expect(splitFinal({ kind: "symptom", plain: "   ", data: card }).prose).toBe("");
  });
  it("text-only reports still carry the citations footer in the single bubble", () => {
    const r = splitFinal({ kind: "symptom", plain: "去市一院[1]", data: {}, citations: { evidence: [{ n: 1, category: "x", cited: true }] } });
    expect(r.prose).toBe("");
    expect(r.card).toContain("参考依据");
  });
  it("card is byte-identical to renderAgentReport", () => {
    const p = { kind: "symptom", plain: "x", data: card };
    expect(splitFinal(p).card).toBe(renderAgentReport(p));
  });
});

describe("repair note in the self-check footer", () => {
  const checks = [{ label: "红旗提示", status: "ok", detail: "x" }];
  it("says a repair was accepted", () => {
    const html = reflectionFooter({ reflection: { checks }, repair: { attempted: true, accepted: true, reasons: ["红旗提示"] } });
    expect(html).toContain("已据此重写一次并通过复检");
  });
  it("says a rejected repair kept the draft", () => {
    const html = reflectionFooter({ reflection: { checks }, repair: { attempted: true, accepted: false, reasons: ["越界表述"] } });
    expect(html).toContain("重写一次未改善，已保留原文并追加规则提示");
  });
  it("is silent when no repair was attempted", () => {
    expect(reflectionFooter({ reflection: { checks } })).not.toContain("重写");
  });
});

describe("红旗规则依据", () => {
  it("急症卡与红旗信号都列出对应的指南名称（转义）", () => {
    const basis = [{ title: "急性胸痛急诊诊疗专家共识", url: "https://example.org" }, { title: "<b>x</b>" }];
    expect(reportLib.statusBanner({ engine: "safety_gate", safety_basis: basis })).toContain("规则依据：《急性胸痛急诊诊疗专家共识》、《&lt;b&gt;x&lt;/b&gt;》");
    const flagged = reportLib.statusBanner({ safety_flags: [{ label: "胸痛", severity: "urgent" }], safety_basis: basis });
    expect(flagged).toContain("规则依据：");
  });

  it("没有登记依据时不渲染依据行", () => {
    expect(reportLib.statusBanner({ engine: "safety_gate" })).not.toContain("规则依据");
    expect(reportLib.statusBanner({ engine: "safety_gate", safety_basis: [] })).not.toContain("规则依据");
  });
});
