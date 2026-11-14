import { beforeEach, describe, expect, it, vi } from "vitest";
import { clahe, enhance, redFree } from "@/lib/fundusImage";
import { combineEyes, isGradable, pairSummary } from "@/lib/bilateral";
import { fundusPairStore, fundusStore, normalizeFundus, type FundusReport } from "@/lib/fundus";

function memoryStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() {
      return m.size;
    },
    clear: () => m.clear(),
    getItem: (k: string) => (m.has(k) ? (m.get(k) as string) : null),
    key: (i: number) => [...m.keys()][i] ?? null,
    removeItem: (k: string) => void m.delete(k),
    setItem: (k: string, v: string) => void m.set(k, String(v)),
  };
}

function eye(level: number, extra: Partial<FundusReport> = {}): FundusReport {
  const r = normalizeFundus(
    { level, image_quality: "可评估", urgency: (["green", "green", "yellow", "orange", "red"] as const)[level],
      urgency_label: ["常规", "常规", "黄色", "橙色", "红色"][level], advice: `建议${level}`, department: "眼科" },
    "eye",
  );
  return { ...r, ...extra };
}

describe("专业阅片：图像增强（纯函数）", () => {
  it("CLAHE 拉开低对比度区域的灰度跨度", () => {
    const w = 64;
    const h = 64;
    const g = new Uint8ClampedArray(w * h);
    for (let i = 0; i < g.length; i++) g[i] = 100 + ((i % w) * 20) / w; // 100–120 的弱渐变
    const span = (a: Uint8ClampedArray) => Math.max(...a) - Math.min(...a);
    expect(span(clahe(g, w, h, { tiles: 4, clip: 3 }))).toBeGreaterThan(28); // 原始跨度只有 20
    expect(span(clahe(g, w, h, { tiles: 4, clip: 60 }))).toBeGreaterThan(150); // 截断放宽 ≈ 普通直方图均衡
  });

  it("背景（视网膜外的黑色）不参与、保持黑色；无赤光输出灰度", () => {
    const w = 32;
    const h = 32;
    const px = new Uint8ClampedArray(w * h * 4);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const j = (y * w + x) * 4;
        const inside = (x - 16) ** 2 + (y - 16) ** 2 < 144;
        px.set(inside ? [180, 80 + x, 40, 255] : [0, 0, 0, 255], j);
      }
    }
    const rf = redFree(px, w, h);
    expect([rf[0], rf[1], rf[2]]).toEqual([0, 0, 0]);
    const c = (16 * w + 16) * 4;
    expect(rf[c]).toBe(rf[c + 1]);
    expect(rf[c + 1]).toBe(rf[c + 2]);
    const en = enhance(px, w, h);
    expect([en[0], en[1], en[2]]).toEqual([0, 0, 0]);
    expect(en[c]).toBeGreaterThan(en[c + 2]); // 红色调保持（色度不变）
  });
});

describe("双眼联合筛查", () => {
  it("按较重的一只眼给建议，并提示两眼差异", () => {
    const b = combineEyes(eye(1), eye(3));
    expect(b.worse).toBe("left");
    expect(b.level).toBe(3);
    expect(b.urgency).toBe("orange");
    expect(b.advice).toBe("建议3");
    expect(b.notes.join()).toContain("相差 2 级");
  });

  it("边界病例按升级后的级别比较", () => {
    const b = combineEyes(eye(2, { escalatedTo: 3 }), eye(2));
    expect(b.worse).toBe("right");
    expect(b.notes.join()).toContain("边界");
  });

  it("不可评估的眼不参与分级，整体至少黄色并提示重拍；质量偏低照常分级", () => {
    const blurry = eye(0, { quality: "不可评估", qualityReasons: ["清晰度不足"], retake: true });
    const b = combineEyes(eye(0), blurry);
    expect(isGradable(blurry)).toBe(false);
    expect(b.gradable).toBe(1);
    expect(b.worse).toBe("right");
    expect(b.urgency).toBe("yellow");
    expect(b.notes.join()).toContain("不可评估不等于正常");
    expect(isGradable(eye(1, { quality: "质量偏低", retake: true }))).toBe(true);
    const none = combineEyes(blurry, { ...blurry });
    expect(none.level).toBe(null);
    expect(none.headline).toContain("都不可评估");
  });

  it("给医生的双眼摘要包含两眼与结论", () => {
    const s = pairSummary(eye(2), eye(0, { quality: "不可评估", retake: true }));
    expect(s).toContain("右眼（OD）：DR 2 级");
    expect(s).toContain("左眼（OS）：照片不可评估");
  });
});

describe("眼底结果缓存：双眼结果同样按账号隔离；新字段从接口带进视图模型", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", memoryStorage());
    localStorage.setItem("mt_username", "alice");
  });

  it("双眼结果只给本账号", () => {
    fundusPairStore.set({ right: eye(1), left: eye(2) });
    expect(fundusPairStore.get()?.left.level).toBe(2);
    localStorage.setItem("mt_username", "bob");
    expect(fundusPairStore.get()).toBe(null);
  });

  it("存储写满时逐级瘦身，先丢阅片大图", () => {
    const real = localStorage.setItem.bind(localStorage);
    vi.spyOn(localStorage, "setItem").mockImplementation((k: string, v: string) => {
      if (v.includes("BIG-IMAGE")) throw new Error("QuotaExceededError");
      real(k, v);
    });
    fundusStore.set(eye(2, { viewImage: "BIG-IMAGE", heatmap: "HM" }));
    const got = fundusStore.get();
    expect(got?.viewImage).toBe(null);
    expect(got?.heatmap).toBe("HM");
  });

  it("normalizeFundus 带上质量、热力层、眼别与边界升级", () => {
    const r = normalizeFundus(
      { level: 2, image_quality: "质量偏低", quality_reasons: ["偏暗"], retake: true, heatmap_layer: "L",
        heatmap_status: "gradcam", escalated_to: 3, eye: "left" },
      "eye",
      { viewImage: "V" },
    );
    expect([r.quality, r.qualityReasons[0], r.retake, r.heatLayer, r.escalatedTo, r.eye, r.viewImage]).toEqual(
      ["质量偏低", "偏暗", true, "L", 3, "left", "V"],
    );
    const p = normalizeFundus(
      { level: 2, probabilities: [0.05, 0.1, 0.5, 0.3, 0.05].map((x, i) => ({ level: i, probability: x })) }, "eye");
    expect(p.probs).toEqual([5, 10, 50, 30, 5]);
    expect(normalizeFundus({ level: 1, probabilities: [10, 60, 20, 5, 5] }, "chat").probs).toEqual([10, 60, 20, 5, 5]);
  });
});
