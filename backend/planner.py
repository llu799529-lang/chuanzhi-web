"""Agent 的显式规划（plan）与自检（reflect）。全部是确定性规则，零模型开销，离线可测。

为什么不让模型来做
------------------
评分细则要看 Agent「规划、工具调用、自主决策」。但让模型额外生成一次计划，等于每次对话多一次调用——
在额度紧张时不划算，而且模型写出的计划无法验证。所以这里的取舍是：

  · 规划（make_plan）：按输入类型给出**预期工作流**，作为 `plan` 事件推给前端展示。
    它是规则规划，不是模型规划——事件里写明 source=rule。模型仍然自主决定实际调用哪些工具、什么顺序，
    规划只是「预期」，偏离不算错（SYSTEM 提示词里的决策原则就是这份预期的来源）。
  · 自检（reflect）：报告生成后，对照**工具真实返回的结果**做一致性核查，作为 `reflect` 事件推送，
    并随 final 一起下发。它不改写模型文字（沿用本项目「只标注、不改写」的原则），
    发现问题时通过 `addendum` 另行追加一条规则生成的提示。

自检的 6 项（每项独立、可复现，全部不调用模型）：
  evidence    必要证据是否齐全（上传了图 → 要有图像分析；纯文字症状 → 要检索过知识库）
  grade       报告里出现的 DR 分级数字，必须能在本次眼底分析 / 历史记录里找到
  red_flag    规则检测到红旗时，报告文字里必须有「就医」类提示
  urgency     分析结果的紧急度不得低于红旗规则给出的下限
  overreach   越界表述（确诊/处方/劝阻就医/具体剂量）
  grounding   句子在知识库里有多少落点——只作信息展示，不是正确率（见 quality/verifier.py）
"""
from __future__ import annotations

import re

import guardrails
import rag
import safety
from quality import verifier

# 「就医导航类」请求里会出现的功能词。agent2._pure_navigation 与本模块共用同一份，避免两处各写一遍后慢慢不一致。
NAV_FILLERS = ["请问", "麻烦", "帮我", "推荐", "查找", "查询", "搜索", "看看",
               "附近", "周边", "有哪些", "有没有", "哪一家", "哪家", "哪个",
               "去哪里", "在哪里", "哪里", "去哪", "什么科", "挂号", "就诊", "就医",
               "医院", "门诊", "科室", "应该", "可以", "需要", "我想", "我要",
               "比较好", "能看", "看病", "挂", "的", "吗", "呢", "有", "去", "我"]
_NAV_TRIGGERS = ("医院", "挂", "哪里", "去哪", "哪家", "附近")
_CARE_WORDS = ("就医", "急诊", "120", "就诊", "门诊", "医院", "尽快去看", "医生")


def _timely_care(plain: str, flags: list) -> bool:
    """只核对规则要求的就医时效，不把出现医院/医生一词当成建议已落实。"""
    emergency = safety.has_emergency(flags)
    timing = r"立即|立刻|马上|现在|120|急诊" if emergency else r"立即|立刻|马上|现在|120|急诊|尽快|及时|今天|当天|24\s*小时内|一天内|一日内"
    for clause in re.split(r"[。！？!?；;，,\n]", plain):
        if not any(w in clause for w in _CARE_WORDS):
            continue
        if re.search(r"(?:不必|不用|无需|不要|不需要|没必要|不建议).{0,10}(?:就医|就诊|医院|急诊|医生|拨打|120)", clause):
            continue
        if re.search(timing, clause):
            return True
    return False


def is_navigation_only(text: str) -> bool:
    """只问「去哪家医院 / 挂什么科」，没有任何症状描述。"""
    t = (text or "").strip()
    if not t or not any(w in t for w in _NAV_TRIGGERS):
        return False
    for w in sorted(set(NAV_FILLERS), key=len, reverse=True):
        t = t.replace(w, "")
    t = re.sub(r"[一-龥]{1,6}科", "", t)          # 「眼科」「消化内科」这类科室名
    return not re.sub(r"[\s，,。.!！?？；;、]", "", t)


# ---------------------------------------------------------------- 规划
def make_plan(text: str, has_image: bool = False, flags=None, can_ask: bool = True,
              hospital_search: bool = True) -> dict:
    said = (text or "").strip()
    flags = list(flags or [])
    steps: list[dict] = []

    def add(tool: str, label: str, why: str, required: bool = False) -> None:
        steps.append({"n": len(steps) + 1, "tool": tool, "label": label, "why": why, "required": required})

    if flags:
        add("safety_gate", "红旗信号复核", "规则已检测到：" + "、".join(f.label for f in flags[:2]) + "；紧急度不会低于橙色", True)
    if has_image:
        intent = "image"
        if can_ask:
            add("ask_user", "必要时追问背景", "病程 / 血糖控制 / 视力变化会影响风险判断（最多问一次）")
        add("get_history", "查询历史记录", "与上次结果对比")
        add("analyze_image", "图像分析", "自动判别眼底彩照 / 化验单", True)
        add("search_kb", "检索知识库", "为报告提供科室、检查与红旗依据", True)
        add("calc_risk", "进展风险评估", "规则引擎；信息不足时如实返回「待评估」")
    elif is_navigation_only(said):
        intent = "navigation"
        if hospital_search:      # 没有医院检索服务时不规划这一步：由回答下方的「查看附近医院」按钮承接
            add("find_hospital", "检索医院", "按建议科室查找；没有定位就不编造距离", True)
    else:
        intent = "symptom"
        add("search_kb", "检索知识库", "症状 → 科室 / 检查 / 红旗信号的依据", True)
        add("calc_risk", "进展风险评估", "仅糖网进展相关；信息不足返回「待评估」")
        if any(w in said for w in _NAV_TRIGGERS) and hospital_search:
            add("find_hospital", "检索医院", "用户同时问了去哪看")
    add("report", "生成综合报告", "只使用上面工具返回的事实", True)
    add("reflect", "自检", "对照工具结果核查：证据 / 分级数字 / 红旗 / 紧急度 / 越界表述")
    return {"source": "rule", "intent": intent, "steps": steps,
            "note": "规则规划：按输入类型预设的预期工作流；模型仍自主决定实际调用顺序，偏离不算错。"}


# ---------------------------------------------------------------- 自检
_GRADE_CTX = re.compile(r"DR|糖网|视网膜|病变|分级|NPDR|PDR|增殖|眼底")
_GRADE_NOISE = re.compile(r"高血压|血压|心功能|肿瘤|肌力")


_CLAUSE_END = "，,。；;！!？?\n"


def _clause_around(text: str, start: int, end: int) -> str:
    """包含 [start, end) 的那一个分句。用分句而不是固定窗口：「较上次的 1 级上升到 2 级的糖尿病视网膜病变」
    里的「1 级」离「视网膜」超过 8 个字，窗口会漏；而分句边界又能把「高血压 2 级，眼底 DR 3 级」分开。"""
    left = max((text.rfind(ch, 0, start) for ch in _CLAUSE_END), default=-1) + 1
    rights = [i for i in (text.find(ch, end) for ch in _CLAUSE_END) if i >= 0]
    return text[left: min(rights) if rights else len(text)]


def mentioned_grades(text: str) -> set[int]:
    """报告文字里提到的 DR 分级数字。只认带眼底语境的「N 级」，避免把「高血压 2 级」「3 级医院」当成分级。"""
    text = text or ""
    out: set[int] = set()
    for m in re.finditer(r"DR\s*([0-4])(?!\d)", text, re.I):
        out.add(int(m.group(1)))
    for m in re.finditer(r"(?<![\d.])([0-4])\s*级(?!医院|甲|乙|以上|以下|别)", text):
        clause = _clause_around(text, m.start(), m.end())
        if _GRADE_CTX.search(clause) and not _GRADE_NOISE.search(clause):
            out.add(int(m.group(1)))
    return out


def _known_grades(s: dict) -> tuple[set[int], bool]:
    """本次眼底分析 + 历史记录里出现过的分级；第二个返回值表示「是否有任何眼底依据」。"""
    levels: set[int] = set()
    a = s.get("analysis")
    if isinstance(a, dict) and a.get("kind") == "fundus" and isinstance(a.get("level"), int):
        levels.add(a["level"])
    for r in s.get("history") or []:
        if isinstance(r, dict) and isinstance(r.get("level"), int):
            levels.add(r["level"])
    return levels, bool(levels)


def _check(cid: str, label: str, status: str, detail: str) -> dict:
    return {"id": cid, "label": label, "status": status, "detail": detail}


# 重写文字能修好的问题。urgency（分析数据里的紧急度）、evidence（没检索/没分析图）靠重写修不了，不在此列。
REPAIRABLE = ("red_flag", "overreach", "grade")


def repairable(reflection: dict | None) -> list[dict]:
    """自检里「文字能修」且未通过的检查项。"""
    return [c for c in (reflection or {}).get("checks", []) if c["id"] in REPAIRABLE and c["status"] in ("warn", "fail")]


def attention_count(reflection: dict | None) -> int:
    return sum(1 for c in (reflection or {}).get("checks", []) if c["status"] in ("warn", "fail"))


def reflect(s: dict, plain: str, citation: dict | None = None) -> dict:
    """报告生成后的自检。返回 {source, verdict, checks, addendum?}；永不修改 plain。

    `citation` 是 citations.analyze 的结果（有检索证据时才传）。引用检查只作信息展示（info），
    不参与「是否需要修复」：越界编号已被自动清除，词面支持度又是下界，都不该触发一次额外的模型调用。
    """
    plain = plain or ""
    checks: list[dict] = []
    flags = list(s.get("safety") or [])
    analysis = s.get("analysis") if isinstance(s.get("analysis"), dict) else None
    addendum_reasons: list[str] = []

    # 1) evidence
    if s.get("image"):
        if analysis and analysis.get("kind") in ("fundus", "lab", "other"):
            checks.append(_check("evidence", "必要证据", "ok", "已获得图像分析结果"))
        else:
            checks.append(_check("evidence", "必要证据", "warn", "上传了图片，但没有拿到图像分析结果，报告里的图像结论不可信"))
    elif s.get("hospital") and not analysis and not s.get("kb"):
        checks.append(_check("evidence", "必要证据", "ok", "就医导航类请求，无需知识库"))
    elif s.get("kb") or s.get("kb_calls"):
        checks.append(_check("evidence", "必要证据", "ok", "已检索知识库"))
    else:
        checks.append(_check("evidence", "必要证据", "warn", "没有检索知识库，报告缺少科室 / 检查 / 红旗依据"))

    # 2) grade
    mentioned = mentioned_grades(plain)
    known, has_basis = _known_grades(s)
    if not mentioned:
        checks.append(_check("grade", "分级数字一致", "ok", "报告未引用 DR 分级数字"))
    elif not has_basis:
        checks.append(_check("grade", "分级数字一致", "warn",
                             "报告提到 DR " + "、".join(map(str, sorted(mentioned))) + " 级，但本次没有眼底分析、历史里也没有分级记录"))
    elif mentioned - known:
        checks.append(_check("grade", "分级数字一致", "warn",
                             "报告提到 DR " + "、".join(map(str, sorted(mentioned - known))) + " 级，"
                             "与本次分析 / 历史记录（" + "、".join(map(str, sorted(known))) + " 级）不一致"))
    else:
        checks.append(_check("grade", "分级数字一致", "ok", "报告里的分级数字都能在分析 / 历史记录里找到"))

    # 3) red_flag
    if flags:
        if _timely_care(plain, flags):
            checks.append(_check("red_flag", "红旗提示", "ok", "报告包含与红旗规则相符的及时就医提示"))
        else:
            checks.append(_check("red_flag", "红旗提示", "fail", "规则检测到红旗，但报告缺少符合时效的就医提示"))
            addendum_reasons.append("报告正文未落实及时就医提示")
    else:
        checks.append(_check("red_flag", "红旗提示", "ok", "规则未检测到红旗信号"))

    # 4) urgency
    floor = safety.floor_urgency(flags)
    cur = (analysis or {}).get("urgency")
    if floor and cur in safety._RANK:
        if safety._RANK[cur] < safety._RANK[floor]:
            checks.append(_check("urgency", "紧急度下限", "fail", f"分析结果的紧急度（{cur}）低于红旗规则下限（{floor}）"))
            addendum_reasons.append("分析结果的紧急度偏低")
        else:
            checks.append(_check("urgency", "紧急度下限", "ok", f"分析结果的紧急度（{cur}）不低于规则下限（{floor}）"))
    else:
        checks.append(_check("urgency", "紧急度下限", "ok", "无红旗下限需要核对" if not floor else "本次无可比对的紧急度字段"))

    # 5) overreach
    hits = guardrails.scan_output(plain)
    if hits:
        checks.append(_check("overreach", "越界表述", "fail", "命中：" + "、".join(hits) + "，需人工复核"))
    else:
        checks.append(_check("overreach", "越界表述", "ok", "未发现确诊 / 处方 / 劝阻就医 / 具体剂量"))

    # 6) grounding（信息展示；剂量或确定性断言才升级为提示）
    try:
        v = verifier.verify(plain, rag.all_entries())
        if v["sentences"]:
            detail = f"{v['green']}/{v['sentences']} 句能在知识库找到落点（下界，不是正确率）"
            if v["red"]:
                checks.append(_check("grounding", "知识库落点", "warn", detail + f"；其中 {v['red']} 句含剂量或确定性断言"))
            else:
                checks.append(_check("grounding", "知识库落点", "info", detail))
    except Exception as e:      # 自检本身不能拖垮报告
        guardrails.log_event("agent.reflect.grounding_failed", error=f"{type(e).__name__}: {str(e)[:100]}")

    # 7) citation（仅信息）
    if citation and citation.get("evidence_n"):
        sup = citation.get("support") or {}
        parts = [f"引用了 {len(citation.get('cited', []))}/{citation['evidence_n']} 条检索证据"]
        if citation.get("invalid"):
            parts.append(f"清除了不存在的编号 {'、'.join(map(str, citation['invalid']))}")
        if sup.get("checked"):
            parts.append(f"{sup['supported']}/{sup['checked']} 处引用在句中能找到该条目的术语（下界，不是正确率）")
        if not citation.get("cited"):
            parts.append("报告没有标注任何引用")
        checks.append(_check("citation", "引用溯源", "info", "；".join(parts)))

    bad = [c for c in checks if c["status"] in ("warn", "fail")]
    out = {"source": "rule", "verdict": "attention" if bad else "pass", "checks": checks,
           "summary": {"total": len(checks), "ok": sum(c["status"] == "ok" for c in checks),
                       "info": sum(c["status"] == "info" for c in checks), "attention": len(bad)}}
    if addendum_reasons and flags:
        labels = "、".join(f.label for f in flags[:3])
        out["addendum"] = (f"规则检测到：{labels}（{'；'.join(addendum_reasons)}）。"
                           f"请尽快就医（{safety.URG_TEXT[floor]}）；本提示由规则生成，不依赖大模型。")
    return out
