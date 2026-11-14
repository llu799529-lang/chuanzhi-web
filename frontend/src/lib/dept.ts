/**
 * 分诊科室名 → 医院页科室选项 的归一化。
 *
 * 背景：分诊 / 眼底 / 化验单三个报告页都会输出一个「建议科室」，
 * 点「按科室找医院」时把它带进医院页；但医院页的下拉框用的是固定的
 * DEPT_OPTIONS（19 个选项名），分诊给的是模型/规则产出的自由文本
 * （「神经内科」「消化内科 / 普外科」「心内科」「全科医疗科」…）。
 * 不做归一化就会 `select` 里没有匹配项 → 下拉框显示空白，或者硬塞回
 * 上一次的科室。
 *
 * 单独成模块的原因：这段逻辑有两个独立的错误面——「匹配不上」和
 * 「匹配错了」——都需要用表驱动的测试钉住，放在 .vue 里测不到。
 */

/** 常用简称 → 规范名。只收录真正会出现的写法，不追求穷举。 */
const ALIAS: Record<string, string> = {
  心内: "心血管内科",
  神内: "神经内科",
  神外: "神经外科",
  消化: "消化内科",
  呼吸: "呼吸内科",
  内分泌: "内分泌科",
  全科医疗: "全科",
  全科医学: "全科",
};

/**
 * 归一化科室名。
 *
 * 处理三件事：
 * 1. 取第一个：「消化内科 / 普外科」→「消化内科」（多科室建议时优先第一个）
 * 2. 简称补全：「心内科」→「心血管内科」（先去掉「科」字查别名表）
 * 3. 保持原样：别名表没有的，不猜，原样返回
 */
export function canonDept(s: string): string {
  const first = (s || "").split(/[\/／、,，]/)[0].trim();
  if (!first) return "";
  const bare = first.replace(/科$/, "");
  return ALIAS[bare] || first;
}

/**
 * 把分诊科室映射到 DEPT_OPTIONS 中的某一项。
 *
 * 匹配方式（按优先级）：
 *   ① 完全相等
 *   ② 去掉「科」字后相等（心血管内科 ↔ 心血管）
 *   ③ 选项包含目标（全科医疗科 → 全科）
 *   ④ 目标包含选项（心血管内科门诊 → 心血管内科）
 *
 * ③④ 的「包含」不是随便取第一个命中项——那会出真错：
 * 「儿童呼吸科」同时被「儿科」和「呼吸内科」包含，按选项顺序先撞上「儿科」，
 * 于是一个呼吸问题被分到儿科。所以 ③④ 内部按**重叠字符数**从多到少排，
 * 取重叠最长的那个：「呼吸」3 个字赢过「儿科」的 2 个字。
 *
 * 全部落空时**返回原值**而不是回落到「眼科」：宁可显示一个下拉框里
 * 没有的科室，也不要显示一个错的科室——用户能看出「这个科室没得选」，
 * 但看不出「眼科是系统随便填的」。
 */
export function matchDept(raw: string, options: readonly string[]): string {
  const want = canonDept(raw);
  if (!want) return "";
  const wantBare = want.replace(/科$/, "");

  const exact = options.find((o) => o === want);
  if (exact) return exact;

  const sameBare = options.find((o) => o.replace(/科$/, "") === wantBare);
  if (sameBare) return sameBare;

  /** 两个字符串的公共子串长度（科室名都很短，暴力算足够） */
  const overlap = (a: string, b: string): number => {
    if (!a || !b) return 0;
    let best = 0;
    for (let i = 0; i < a.length; i++) {
      for (let j = i + 1; j <= a.length; j++) {
        const seg = a.slice(i, j);
        if (seg.length > best && b.includes(seg)) best = seg.length;
      }
    }
    return best;
  };

  const scored = options
    .map((o) => {
      const oBare = o.replace(/科$/, "");
      // ③ 选项包含目标 / ④ 目标包含选项，取两者较大的重叠长度
      const n = Math.max(
        wantBare.includes(oBare) ? oBare.length : 0,
        oBare.includes(wantBare) ? wantBare.length : 0,
        overlap(wantBare, oBare),
      );
      return { o, n };
    })
    .filter((x) => x.n >= 2) // 只重叠 1 个字（如「科」）不算匹配
    .sort((a, b) => b.n - a.n);

  return scored[0]?.o || want;
}
