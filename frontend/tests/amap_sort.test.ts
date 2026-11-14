import { describe, expect, it } from "vitest";
import { confToPois, deptHit, hospitalProfile, sortPois } from "@/lib/amap";

/**
 * 医院排序链路：后端 depts → POI → hospitalProfile → deptHit → sortPois。
 *
 * 回归背景：hospitalProfile 只会按医院名字猜科室，对「市第一人民医院」
 * 这类综合医院给出的是写死的一组内科名。演示数据里 3 家园有 2 家是这种
 * 综合医院，于是选「皮肤科 / 儿科 / 全科」时三家全不命中、顺序不变，
 * 页面却写着「适合皮肤科优先」。修法是让后端直接给 depts，前端优先采用。
 */

const CONF = {
  hospitals: [
    {
      name: "市第一人民医院", level: "三甲", distance_km: 1.8,
      depts: ["心血管内科", "神经内科", "消化内科", "呼吸内科", "骨科", "普外科"],
    },
    {
      name: "XX区皮肤病医院", level: "专科", distance_km: 4.9,
      depts: ["皮肤科", "医学美容"],
    },
    {
      name: "XX社区卫生服务中心", level: "社区", distance_km: 0.8,
      depts: ["全科", "全科门诊", "慢病随访", "预防保健"],
    },
  ],
};

describe(" hospitalProfile 优先采用后端给出的科室", () => {
  it("有 depts 时不再按名字猜", () => {
    const p = hospitalProfile("市第一人民医院", "三甲", ["皮肤科"]);
    expect(p.depts).toEqual(["皮肤科"]);
  });

  it("没有 depts 时回落到名字推断（高德 POI 就没有这个字段）", () => {
    const p = hospitalProfile("XX区眼科专科医院", "专科");
    expect(p.depts).toContain("眼底病");
  });
});

describe("sortPois 按后端科室重排", () => {
  const pois = confToPois(CONF);

  it("confToPois 要把 depts 透传下来", () => {
    expect(pois[0].depts).toContain("心血管内科");
  });

  it("皮肤科：皮肤病医院排到第一", () => {
    const ranked = sortPois(pois, "皮肤科");
    expect(ranked[0].name).toBe("XX区皮肤病医院");
  });

  it("全科：社区卫生中心排到第一", () => {
    const ranked = sortPois(pois, "全科");
    expect(ranked[0].name).toBe("XX社区卫生服务中心");
  });

  it("神经内科：市第一人民医院排到第一", () => {
    const ranked = sortPois(pois, "神经内科");
    expect(ranked[0].name).toBe("市第一人民医院");
  });

  it("命中的排前面、未命中的按距离兜底，且不丢弃", () => {
    const ranked = sortPois(pois, "皮肤科");
    expect(ranked).toHaveLength(pois.length);
    const hits = ranked.map((p) => deptHit(hospitalProfile(p.name, p.type, p.depts).depts, p.name, "皮肤科") >= 0);
    expect(hits[0]).toBe(true);
    // 未命中的部分距离必须单调不减
    const tail = ranked.filter((_, i) => !hits[i]).map((p) => p.distance);
    expect(tail).toEqual([...tail].sort((a, b) => (a ?? 0) - (b ?? 0)));
  });
});
