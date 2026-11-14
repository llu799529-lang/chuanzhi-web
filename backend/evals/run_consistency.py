"""分级一致性评测：规则引擎 vs 大模型，量「两套引擎是否互相印证」。

为什么做这个
-----------
项目对外讲的是「双引擎」：规则引擎（triage.SYMPTOM_LIBRARY，36 条症状）负责
可预期、可审计；大模型负责覆盖长尾口语。但两个引擎给出不同科室时，用户只看到
一个答案——如果没人量过一致性，「双引擎」就只是一句宣传语。

指标
----
  agree_rate   两引擎科室一致率（主科室相同）
  near_rate    宽松一致率（一方的主科室出现在另一方的次要科室里）
  urgency_delta 紧急度打分差（green0/yellow1/orange2/red3），正数=规则更保守
  unsafe_df    危险差（规则判橙/红，模型判绿/黄）——这是最不能接受的方向

用法（需要 ARK_API_KEY）：
    python evals/run_consistency.py
输出：evals/consistency_report.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
QUERIES = os.path.join(EVALS_DIR, "blind_queries.json")
OUT_PATH = os.path.join(EVALS_DIR, "consistency_report.json")

ORDER = {"green": 0, "yellow": 1, "orange": 2, "red": 3}

# 科室同义组：两组里只要各出现一个就算一致。
# 这不是放水——「心内科 / 心血管内科」「耳鼻喉科 / 耳鼻咽喉科」在挂号系统里
# 本来就是同一个科室的两种叫法，不一视同仁会让一致率被字面差异吃掉。
DEPT_GROUPS = [
    {"心内科", "心血管内科", "心内"},
    {"呼吸内科", "呼吸科", "呼吸与危重症医学科"},
    {"神经内科", "神内"},
    {"消化内科", "消化科"},
    {"耳鼻喉科", "耳鼻咽喉科", "五官科"},
    {"皮肤科", "皮肤病科"},
    {"骨科", "骨外科", "创伤骨科"},
    {"风湿免疫科", "风湿科"},
    {"肾内科", "肾脏内科"},
    {"内分泌科", "内分泌"},
    {"精神心理科", "心理科", "精神科"},
    {"发热门诊", "感染科", "传染科"},
    {"普外科", "普通外科", "外科"},
    {"眼科", "眼科（常规体检）", "眼科（优先）"},
    {"全科", "全科医学科", "家庭医学科", "急诊科"},
]


def _canon(dept: str) -> str:
    d = (dept or "").strip()
    for grp in DEPT_GROUPS:
        for name in grp:
            if name in d:
                return sorted(grp)[0]
    return d


def _urgency_of(result: dict) -> str:
    """把两种返回形态统一成 green/yellow/orange/red 四档。"""
    u = result.get("urgency") or ""
    if u in ORDER:
        return u
    label = result.get("urg") or result.get("urgency_label") or ""
    for k, word in (("red", "红"), ("orange", "橙"), ("yellow", "黄"), ("green", "绿")):
        if word in label:
            return k
    return "yellow"


def run():
    import ai_analysis
    import llm
    import triage

    if not llm.llm_available():
        print("[跳过] 未设置 ARK_API_KEY，一致性评测需要调用大模型。")
        return None

    data = json.load(open(QUERIES, encoding="utf-8"))
    rows = []
    for batch in data["batches"]:
        for item in batch["queries"]:
            q = item["query"]
            rule = triage.triage_symptom(q)
            try:
                ai = ai_analysis.analyze_symptom(q)
            except Exception as e:
                rows.append({"query": q, "error": str(e)})
                continue
            r_dept, a_dept = _canon(rule.get("department", "")), _canon(ai.get("dept", ""))
            r_u, a_u = _urgency_of(rule), _urgency_of(ai)
            rows.append({
                "query": q,
                "rule_dept": rule.get("department", ""),
                "ai_dept": ai.get("dept", ""),
                "rule_urgency": r_u,
                "ai_urgency": a_u,
                "agree": r_dept == a_dept,
                "near": a_dept == _canon(rule.get("secondary", "")),
                "urgency_delta": ORDER[r_u] - ORDER[a_u],
                "unsafe": ORDER[r_u] >= 2 and ORDER[a_u] <= 1,
            })

    valid = [r for r in rows if "error" not in r]
    n = len(valid)
    agree = sum(1 for r in valid if r["agree"])
    near = sum(1 for r in valid if r["agree"] or r["near"])
    safe_delta = sum(1 for r in valid if r["urgency_delta"] >= 0)
    unsafe = [r for r in valid if r["unsafe"]]
    summary = {
        "n": n,
        "agree": agree,
        "agree_rate": round(agree / n, 3) if n else 0.0,
        "near_rate": round(near / n, 3) if n else 0.0,
        "rule_not_less_conservative": round(safe_delta / n, 3) if n else 0.0,
        "unsafe_count": len(unsafe),
        "errors": len(rows) - n,
    }
    out = {"summary": summary, "rows": rows}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"一致率 {agree}/{n} = {summary['agree_rate']}（宽松 {summary['near_rate']}）")
    print(f"危险差 {len(unsafe)} 条（规则橙/红 → 模型绿/黄）")
    for r in unsafe:
        print(f"  ! {r['query']}: 规则 {r['rule_dept']}/{r['rule_urgency']} → 模型 {r['ai_dept']}/{r['ai_urgency']}")
    mismatch = [r for r in valid if not r["agree"]][:12]
    if mismatch:
        print("\n科室不一致样例：")
        for r in mismatch:
            print(f"  {r['query'][:26]:<28} 规则 {r['rule_dept']:<10} 模型 {r['ai_dept']}")
    print(f"\n明细已写入 {OUT_PATH}")
    return out


if __name__ == "__main__":
    run()
