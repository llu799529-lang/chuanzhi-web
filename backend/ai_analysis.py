"""火山方舟大模型多模态分析（文本与视觉模型分别配置）。

入口：
  analyze_image(image_bytes, mime)   上传图自动判别：眼底彩照 / 化验单 / 其他
  analyze_symptom(text)              症状文字 → 结构化分诊

返回纯 dict（前端直接渲染），全部经规范化校验，异常向上抛出由调用方降级。
"""
import base64
import html
import json
import math

import guardrails
import lab_check
import llm
import rag
import safety

DR_LABELS = ["无病变", "轻度NPDR", "中度NPDR", "重度NPDR", "增殖期PDR"]
DR_LABELS_LONG = ["无病变", "轻度非增殖期", "中度非增殖期", "重度非增殖期", "增殖期"]

# 分级 → (科室, 紧急度文案, 紧急度色)  确定性映射，与本地规则引擎口径一致
FUNDUS_TRIAGE = [
    ("眼科", "绿色 · 每年例行复查一次", "green"),
    ("眼科", "绿色 · 6–12 个月内复查", "green"),
    ("眼科 · 眼底病专科", "黄色 · 3–6 个月内复查，优先选择三级医院", "yellow"),
    ("眼科 · 眼底病专科", "橙色 · 2 周内就诊，散瞳详查 + OCT", "orange"),
    ("眼科 · 眼底病专科", "红色 · 立即就诊，警惕视力骤降", "red"),
]

IMAGE_SYSTEM = """你是 MedTriage 多模态智能分诊与就医导航系统的图像分析助手，具备眼底阅片与化验单解读能力。
用户上传一张图片，你先判断图片类型，再按对应格式输出。只输出一个 JSON 对象，禁止任何解释、markdown 或代码围栏。

【第一步 · 判别类型】
- 眼底彩照（视网膜环形视野图像）→ kind = "fundus"
- 化验单 / 检验报告 / 体检报告（含项目、数值、参考范围的表格类图片）→ kind = "lab"
- 其他（生活照、文档、截图等与医疗筛查无关）→ kind = "other"

【kind = "fundus"】按国际 DR 临床分级标准输出，字段如下：
{
 "kind": "fundus",
 "probabilities": [p0,p1,p2,p3,p4],
 "level": 2,
 "confidence": 0.87,
 "summary": "20–40 字总结眼底所见",
 "lesions": [{"type":"微血管瘤","count":6,"desc":"暗红色小圆点，边界清晰","loc":"颞上血管弓周围"}],
 "criteria": [{"hit":true,"text":"微血管瘤超过 5 处，满足中度标准"}],
 "risks": [{"level":"high","text":"视网膜出血征象明显","tag":"重点管理"}],
 "advice": ["眼科复查：3 个月内完成散瞳眼底检查 + OCT"],
 "followup": "3–6 个月内"
}
规则：
- probabilities 为 DR 0–4 各级概率百分比（0–100，一位小数，合计约 100），level 对应项必须最高。
- lesions 的 type 限选：微血管瘤 / 点状出血 / 硬性渗出 / 棉絮斑 / 视网膜内微血管异常 / 静脉串珠 / 新生血管 / 纤维增生 / 玻璃体积血；按严重程度排序，无病变则空数组。
- criteria 3–4 条，同时覆盖阳性（hit=true）与阴性（hit=false）发现。
- risks 2–3 条，level 限选 high / mid / low。
- advice 2–3 条，每条以「要点：说明」格式；followup 为复查时限。
- 示意图或低质量图片仍按可见特征判断，并在 summary 中注明质量局限。

【kind = "lab"】输出：
{
 "kind": "lab",
 "report_title": "报告名称，如 血常规 + 生化全套",
 "patient": {"gender": "男", "age": 68},
 "sampled_at": "2026-09-12 08:30",
 "reported_at": "2026-09-12 14:20",
 "confidence": 98.2,
 "dept": "建议就诊科室",
 "urgency": "橙色 · 建议 2 周内就诊",
 "items": [{"name":"空腹血糖","value":"7.8","unit":"mmol/L","ref":"3.9–6.1","flag":"high"}],
 "abnormal_count": 3,
 "judgments": [{"q":"空腹血糖 7.8、糖化 7.2%，说明什么？","a":"两项都明显偏高，反映近 2–3 个月血糖持续控制欠佳。","level":"mid","tag":"关注"}],
 "advice": ["建议 2–3 条，每条以「要点：说明」格式"],
 "followup": "2 周内"
}
规则：
- items 尽量完整识别可见指标（最多 12 项），value 只填数值，ref 填参考范围；flag 限选 high / low / normal。
- patient / sampled_at / reported_at 只在图片中可见时填写（gender 限 男/女，age 为整数岁，时间为原文格式），看不到则填 null。
- confidence 为整体识别置信度百分比（0–100，一位小数），按图片清晰度与字段完整程度估计。
- judgments 2–4 条，level 限选 high / mid / low；q 为患者视角的通俗问题（结合具体数值），a 为通俗解答（80 字内，说清含义与下一步）。
- urgency 颜色从绿 / 黄 / 橙 / 红中选，按异常指标的严重程度决定。

【kind = "other"】输出：
{"kind": "other", "summary": "说明图片内容与无法分析的原因", "advice": ["请上传眼底彩照或化验单照片"]}"""

SYMPTOM_SYSTEM = """你是 MedTriage 智能分诊助手的症状分诊模块。用户用文字描述症状，你输出结构化分诊建议。
只输出一个 JSON 对象，禁止任何解释文字。字段如下：
{
 "hits": ["头晕", "晨起加重"],
 "echo": "症状归类名称，如「眩晕 / 头晕」",
 "dept": "建议就诊科室（首诊）",
 "urg": "黄色 · 建议 1 周内就诊",
 "alt": "备选科室或需补充的信息（如 伴耳鸣听力下降也可看耳鼻喉科；信息不足时说明需补充时间、部位、诱因）",
 "suspects": [
   ["良性阵发性位置性眩晕", 45, "支持点：起床体位变化时诱发"],
   ["第二可能方向", 30, "支持点说明"],
   ["第三可能方向", 15, "支持点说明"]
 ],
 "tests": ["前庭功能检查 · 评估眩晕来源", "头颅 CT/MRI · 排除中枢性病变"],
 "prep": ["就诊准备 3–4 条"],
 "reds": ["红旗信号：出现请立即就医，2–4 条"]
}
规则：
- hits 为从描述中识别的 2–4 个症状关键词。
- suspects 按可能性降序 3 条，第二项为百分比整数（合计 ≤ 100）。
- tests 3–4 条，格式「检查名 · 目的」。
- urg 颜色从绿 / 黄 / 橙 / 红中选，依据病情紧迫程度克制判断，不夸大。
- 出现红旗症状（剧烈胸痛、意识障碍、肢体偏瘫、呼吸困难、剧烈头痛伴呕吐等）时 urg 用红色。
- 若消息附带【知识库检索结果】，优先结合其科室方向、疾病特征与红旗信号组织回答；与描述细节不符时可以修正，但不要凭空编造知识库外的疾病名。"""


# ------------------------------------------------------------------ 工具
def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _s(v, default="") -> str:
    return str(v).strip() if v is not None else default


def _clip(v, lo, hi) -> float:
    return max(lo, min(hi, v))


def urgency_key(text: str) -> str:
    """从紧急度文案提取颜色键（入库 records.urgency 用）。"""
    for k, kw in [("red", "红"), ("orange", "橙"), ("yellow", "黄"), ("green", "绿")]:
        if kw in text:
            return k
    return "green"


def _norm_probs(raw) -> list[float]:
    probs = []
    for i in range(5):
        v = 0.0
        if isinstance(raw, (list, tuple)):
            if i < len(raw):
                v = _num(raw[i])
        elif isinstance(raw, dict):
            v = _num(raw.get(str(i), raw.get(i, 0)))
        probs.append(max(0.0, v))
    total = sum(probs)
    if total <= 0:
        raise ValueError("probabilities 全为 0")
    probs = [round(p / total * 100, 1) for p in probs]
    top = probs.index(max(probs))
    probs[top] = round(probs[top] + (100 - sum(probs)), 1)  # 归一化到恰好 100
    return probs


# ------------------------------------------------------------------ 图像分析
def analyze_image(image_bytes: bytes, mime: str = "image/jpeg",
                  username: str | None = None) -> dict:
    """上传图统一入口：自动判别 fundus / lab / other，返回规范化 dict。

    `username` 只用于用量计量（写 llm_usage 表的归属列）。不传也能跑，
    但那条记录会归到 None 名下——实测发现图像分析是所有调用里**最贵的一次**
    （多模态模型），归不到人头上等于最该记的那笔没记。
    """
    data = llm.chat_json(IMAGE_SYSTEM, "请分析这张图片。",
                         image_b64=base64.b64encode(image_bytes).decode(),
                         username=username)
    kind = _s(data.get("kind"), "other")
    if kind == "fundus":
        return _norm_fundus(data)
    if kind == "lab":
        return _norm_lab(data)
    return _norm_other(data)


def _norm_fundus(data: dict) -> dict:
    probs = _norm_probs(data.get("probabilities"))
    level = int(_clip(round(_num(data.get("level"), -1)), -1, 9))
    if not 0 <= level <= 4:
        level = probs.index(max(probs))
    # probabilities 与 level 对齐：确保 level 项为最高
    top = probs.index(max(probs))
    if top != level:
        probs[level], probs[top] = probs[top], probs[level]

    dept, urgency, color = FUNDUS_TRIAGE[level]
    lesions = []
    for les in (data.get("lesions") or [])[:6]:
        if not isinstance(les, dict):
            continue
        name = _s(les.get("type"))
        if not name:
            continue
        try:
            count = max(1, int(_num(les.get("count"), 1)))
        except ValueError:
            count = 1
        lesions.append({"type": name, "count": count, "desc": _s(les.get("desc")), "loc": _s(les.get("loc"))})

    criteria = []
    for c in (data.get("criteria") or [])[:5]:
        if isinstance(c, dict) and _s(c.get("text")):
            criteria.append({"hit": bool(c.get("hit")), "text": _s(c.get("text"))})
        elif isinstance(c, str) and c.strip():
            criteria.append({"hit": True, "text": c.strip()})

    risks = []
    for r in (data.get("risks") or [])[:4]:
        if not isinstance(r, dict) or not _s(r.get("text")):
            continue
        lv = _s(r.get("level"), "mid")
        if lv not in ("high", "mid", "low"):
            lv = "mid"
        risks.append({"level": lv, "text": _s(r.get("text")), "tag": _s(r.get("tag"), "关注")})

    advice = [a for a in (_s(x) for x in (data.get("advice") or [])[:4]) if a]
    if not advice:
        advice = ["眼科复查：按分级随访计划完成散瞳眼底检查"]
    return {
        "kind": "fundus",
        "probabilities": probs,
        "level": level,
        "level_label": DR_LABELS[level],
        "level_label_long": DR_LABELS_LONG[level],
        "confidence": round(_clip(_num(data.get("confidence"), 0.8), 0.05, 0.99), 2),
        "summary": _s(data.get("summary")),
        "lesions": lesions,
        "criteria": criteria,
        "risks": risks,
        "advice": advice,
        "followup": _s(data.get("followup"), "遵医嘱复查"),
        "department": dept,
        "urgency_label": urgency,
        "urgency": color,
    }


def _norm_lab(data: dict) -> dict:
    items = []
    for it in (data.get("items") or [])[:12]:
        if not isinstance(it, dict) or not _s(it.get("name")):
            continue
        flag = _s(it.get("flag"), "normal")
        if flag not in ("high", "low", "normal"):
            flag = "normal"
        items.append({
            "name": _s(it.get("name")), "value": _s(it.get("value")),
            "unit": _s(it.get("unit")), "ref": _s(it.get("ref")), "flag": flag,
        })
    abnormal = sum(1 for it in items if it["flag"] != "normal")
    value_checks = lab_check.annotate(items)       # 识别结果与单位 / 参考范围 / 人体可能范围对不上的，标注待核对

    # 患者信息（图片可见时才有）
    raw_pat = data.get("patient")
    patient = {"gender": "", "age": ""}
    if isinstance(raw_pat, dict):
        g = _s(raw_pat.get("gender"))
        if g in ("男", "女"):
            patient["gender"] = g
        age = _s(raw_pat.get("age"))
        if age and age.replace("岁", "").isdigit():
            patient["age"] = age.replace("岁", "")
    elif isinstance(raw_pat, str) and raw_pat.strip():
        patient["gender"] = raw_pat.strip() if raw_pat.strip() in ("男", "女") else ""

    # 保留模型给出的百分比；字段完整不等于识别准确，不能据此加分。
    # 缺失或不可用的估值用 null 表示未知，兼容前端已有的无置信度展示。
    raw_confidence = data.get("confidence")
    confidence = _num(raw_confidence, None)
    if isinstance(raw_confidence, bool) or confidence is None or not math.isfinite(confidence):
        confidence = None
    else:
        confidence = round(_clip(confidence, 0, 100), 1)

    judgments = []
    for j in (data.get("judgments") or [])[:4]:
        if not isinstance(j, dict):
            continue
        answer = _s(j.get("a")) or _s(j.get("text"))
        if not answer:
            continue
        lv = _s(j.get("level"), "mid")
        if lv not in ("high", "mid", "low"):
            lv = "mid"
        judgments.append({
            "q": _s(j.get("q")), "a": answer, "level": lv,
            "text": answer, "tag": _s(j.get("tag"), "关注"),
        })

    urgency = _s(data.get("urgency"), "黄色 · 建议 1–2 周内就诊")
    return {
        "kind": "lab",
        "report_title": _s(data.get("report_title"), "检验报告"),
        "patient": patient,
        "sampled_at": _s(data.get("sampled_at")) if data.get("sampled_at") else "",
        "reported_at": _s(data.get("reported_at")) if data.get("reported_at") else "",
        "confidence": confidence,
        "items": items,
        "abnormal_count": abnormal,
        "value_checks": value_checks,
        "judgments": judgments,
        "advice": [a for a in (_s(x) for x in (data.get("advice") or [])[:4]) if a] or ["携带报告原件，按医嘱复查异常指标"],
        "followup": _s(data.get("followup"), "2 周内"),
        "department": _s(data.get("dept"), "全科"),
        "urgency_label": urgency,
        "urgency": urgency_key(urgency),
    }


def _norm_other(data: dict) -> dict:
    return {
        "kind": "other",
        "summary": _s(data.get("summary"), "这张图片不是眼底彩照或化验单，无法进行医疗筛查分析。"),
        "advice": [a for a in (_s(x) for x in (data.get("advice") or [])[:3]) if a] or ["请上传眼底彩照或化验单照片"],
    }


# ------------------------------------------------------------------ 症状分析
#
# 三级降级链（现场答辩防翻车的关键）：
#   1) 大模型正常返回           → degraded=False
#   2) 大模型超时/报错/输出不合法 → 用知识库规则引擎兜底，degraded=True + degrade_reason
#   3) 知识库也没命中           → 返回全科兜底卡，明确告知信息不足
# 任何一档都必须返回可用结构——前端永远拿到一张能渲染的分诊卡。

_DEPT_BY_URGENCY = {"red": "急诊科（首诊）", "orange": "专科门诊", "yellow": "全科", "green": "全科"}


def _rule_based_symptom(query: str, kb: list[dict], reason: str) -> dict:
    """规则引擎兜底：完全基于知识库条目组织，不依赖大模型。"""
    top = kb[0]["entry"] if kb else {}
    dept = top.get("dept", "全科")
    urgency = top.get("urgency", "yellow")
    if urgency == "red":
        dept = _DEPT_BY_URGENCY["red"]

    urg_text = {
        "red": "红色 · 建议立即急诊就医",
        "orange": "橙色 · 建议 24–48 小时内就诊",
        "yellow": "黄色 · 建议 1 周内就诊",
        "green": "绿色 · 可择期门诊",
    }.get(urgency, "黄色 · 建议 1 周内就诊")

    suspects = []
    for d in (top.get("diseases") or [])[:3]:
        name = d.get("name", "") if isinstance(d, dict) else str(d)
        if name:
            suspects.append([name, 0, ""])
    if suspects:
        base = [45, 30, 15]
        for i, s in enumerate(suspects):
            s[1] = base[i] if i < len(base) else 10
            d = (top.get("diseases") or [])[i]
            s[2] = d.get("feature", "") if isinstance(d, dict) else ""

    matched = []
    for r in kb[:2]:
        matched.extend(r.get("matched") or [])

    result = {
        "kind": "symptom",
        "hits": list(dict.fromkeys(matched))[:4],
        "echo": query[:20] or "症状分诊",
        "dept": dept,
        "urg": urg_text,
        "alt": top.get("alt_dept", "") or "",
        "suspects": suspects or [["综合评估方向", 40, "信息有限，建议补充时间、部位与诱因"]],
        "tests": (top.get("tests") or [])[:4] or ["血常规", "基础生化"],
        "prep": ["整理症状出现时间、部位、诱因与伴随情况"],
        "reds": (top.get("reds") or [])[:4],
        "urgency": urgency,
        "degraded": True,
        "degrade_reason": reason,
        "degrade_note": "AI 分析暂不可用，以下是基于内置医学知识库的规则匹配结果，仅供参考，请以医生面诊为准。",
    }
    if kb:
        result["kb_hits"] = rag.refs_payload(kb)
    return result


def analyze_symptom(text: str, username: str | None = None) -> dict:
    """症状文字 → 结构化分诊。

    流水线：红旗闸门（确定性规则）→ RAG 检索 → 大模型 → 红旗托底 → （失败时）规则降级。
      · 命中红色急症：直接返回急症卡，**不调模型**（更快、免费，且不会被模型漏判）；
      · 命中橙色信号：模型照常出结果，之后紧急度被「只升不降」地托到橙色以上；
      · 模型不可用（无 Key / 额度耗尽 / 超时 / 输出畸形）：保留检索依据，降级到知识库规则。
    """
    query = text.strip()
    flags = safety.detect(query)
    kb = rag.retrieve(query)  # RAG：先检索内置知识库（本地计算，永不会失败）
    if safety.has_emergency(flags):
        guardrails.log_event("ai.symptom.safety_gate", flags=[f.id for f in flags])
        return safety.emergency_symptom_card(query, flags, rag.refs_payload(kb) if kb else None)
    injection = guardrails.detect_injection(query)
    if injection:
        guardrails.log_event("ai.symptom.injection_suspected", rules=injection)
    prompt = guardrails.fence_user_text(query, injection) if injection else "患者描述：" + query
    if kb:
        prompt += "\n\n" + rag.format_context(kb)
    if flags:
        prompt += "\n\n" + safety.prompt_note(flags)
    try:
        data = llm.chat_json(SYMPTOM_SYSTEM, prompt, username=username)
        card = _norm_symptom(data, kb)
    except Exception as e:  # 调用、JSON 解析或字段校验失败 → 保留检索依据降级
        reason = f"{type(e).__name__}: {str(e)[:120]}"
        guardrails.log_event("ai.symptom.degraded", reason=reason, has_kb=bool(kb))
        card = _rule_based_symptom(query, kb, reason)
    if injection:
        card["injection_suspected"] = injection
    return safety.apply_floor(card, flags)


def _norm_symptom(data: dict, kb: list[dict]) -> dict:
    """校验模型输出的容器与数值类型，再组织兼容既有接口的分诊卡。"""
    if not isinstance(data, dict):
        raise ValueError("symptom output must be a JSON object")
    for key in ("hits", "suspects", "tests", "prep", "reds"):
        value = data.get(key)
        if value is not None and not isinstance(value, (list, tuple)):
            raise ValueError(f"{key} must be an array")
        if key != "suspects" and value is not None and any(not isinstance(x, str) for x in value):
            raise ValueError(f"{key} must contain text")
    for key in ("echo", "dept", "urg", "alt"):
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{key} must be text")

    suspects = []
    for s in (data.get("suspects") or [])[:3]:
        if isinstance(s, (list, tuple)) and len(s) >= 2 and _s(s[0]):
            name, raw_pct, desc = s[0], s[1], s[2] if len(s) > 2 else ""
        elif isinstance(s, dict) and _s(s.get("name")):
            name, raw_pct, desc = s["name"], s.get("pct", 30), s.get("desc")
        else:
            raise ValueError("invalid suspect entry")
        if not isinstance(name, str) or (desc is not None and not isinstance(desc, str)):
            raise ValueError("suspect name and description must be text")
        pct = float(raw_pct)
        if isinstance(raw_pct, bool) or not math.isfinite(pct):
            raise ValueError("suspect percentage must be finite")
        suspects.append([_s(name), int(_clip(round(pct), 1, 95)), _s(desc)])
    suspects.sort(key=lambda x: -x[1])
    if not suspects:
        suspects = [["综合评估方向", 40, "信息有限，建议补充时间、部位与诱因"]]

    urg = _s(data.get("urg"), "黄色 · 建议 1–2 周内就诊")
    result = {
        "kind": "symptom",
        "hits": [h for h in (_s(x) for x in (data.get("hits") or [])[:4]) if h],
        "echo": _s(data.get("echo"), "症状分诊"),
        "dept": _s(data.get("dept"), "全科"),
        "urg": urg,
        "alt": _s(data.get("alt"), ""),
        "suspects": suspects,
        "tests": [t for t in (_s(x) for x in (data.get("tests") or [])[:4]) if t],
        "prep": [p for p in (_s(x) for x in (data.get("prep") or [])[:4]) if p] or ["整理症状出现时间、部位、诱因与伴随情况"],
        "reds": [r for r in (_s(x) for x in (data.get("reds") or [])[:4]) if r],
        "urgency": urgency_key(urg),
        "degraded": False,
    }
    if kb:  # RAG 检索命中 → 附知识库参考供前端展示
        result["kb_hits"] = rag.refs_payload(kb)
    return result


# ------------------------------------------------------------------ 多模态综合分析
MULTIMODAL_SYSTEM = """你是 MedTriage 多模态智能分诊系统的综合分析助手。系统会把用户近期的筛查记录汇总成 JSON 交给你，你做跨模态交叉分析，输出结构化「发现」列表供前端按聊天气泡渲染。只输出一个 JSON 对象，禁止解释文字与代码围栏。

输入字段说明：
- records：历史记录数组，每条含 input_type（眼底彩照/化验单/症状描述）、level（DR 分级 0-4，仅眼底记录有）、department、urgency（green/yellow/orange/red）、summary、created_at
- lab_detail：最近一次化验单完整明细（可能为 null），含 items（name/value/unit/ref/flag）、abnormal_count、judgments（q/a 通俗解读）、patient、sampled_at 等

输出格式：
{
 "intro": "开场白：概括用户最近的记录构成并给出总体结论，100 字内，可用 <b> 标注结论关键词",
 "findings": [
   {
    "severity": "crit",
    "label": "发现 1 · 最需要关注",
    "title": "一句话标题（纯文本）",
    "text": "120 字内正文，解释为什么，可用 <b> 强调关键数值",
    "data": [{"k": "指标名", "v": "值与单位", "cls": "warn"}, {"k": "尿微量白蛋白", "v": "未检测", "cls": "dim"}],
    "when": "1 个月内",
    "when_cls": "red",
    "advice": ["建议条目，可用 <strong> 强调", "…"],
    "acts": [{"t": "预约眼科 OCT", "a": "oct", "primary": true}, {"t": "查看眼底报告", "a": "fundus"}]
   }
 ]
}
规则：
- findings 2–3 条（最多 3），按重要性降序；severity 限选 crit（红 · 最需要关注）/ warn（黄 · 早期可干预或需要鉴别）/ info（蓝 · 同步管理或常规提示）。
- 交叉分析是核心：优先找不同模态互相印证或加重的信号（如血糖高 + DR 分级进展、血脂异常 + 相关症状）；只有单一模态数据时，就围绕该模态的异常指标展开，禁止编造输入中不存在的数据或检查。
- data 每条发现 2–3 行（最多 3），cls 限选 warn（异常，橙）/ hl（重点，蓝）/ dim（未检测或参考项，灰），普通行留空字符串；k/v 为纯文本不含标签。
- advice 2 条（最多 2），每条一句话；when 为行动时限（如「2–4 周内」）；when_cls 限选 red / green / 空字符串（空 = 默认黄色）。
- intro 60 字内；text 80 字内。
- acts 每条发现最多 2 个按钮；a 必须从以下动作代码中选，按钮文字要与之匹配：
  oct（预约眼科 OCT）、fundus（查看眼底报告）、uacr（加做 UACR 检查）、whatUacr（了解什么是 UACR）、
  sx（查看症状分诊）、glucose（记录 7 天血糖）、lab（查看化验单）、history（查看历史记录）、hospital（查找附近医院）
- 引用指标必须带输入数据中的具体数值与单位，禁止编造；目标值等常识性内容可以给。
- 只依据给到的记录生成发现，不要假设用户有糖尿病、高血压等数据中未体现的病史；跨模态关联措辞保持克制（用「若」「同时存在时」）。"""


MMA_ACT_CODES = {"oct", "fundus", "uacr", "whatUacr", "sx", "glucose", "lab", "history", "hospital"}


def _safe_rich(v) -> str:
    """富文本清洗：整体转义后仅回放 <b>/<strong> 两种标签，防注入。"""
    s = _s(v)
    s = (s.replace("<b>", "\x01").replace("</b>", "\x02")
          .replace("<strong>", "\x03").replace("</strong>", "\x04"))
    s = html.escape(s, quote=False)
    return (s.replace("\x01", "<b>").replace("\x02", "</b>")
             .replace("\x03", "<strong>").replace("\x04", "</strong>"))


def analyze_multimodal(records: list, lab_detail: dict | None) -> dict:
    """历史记录（眼底/化验/症状）+ 最近化验单明细 → 大模型交叉分析。"""
    context = {"records": records or [], "lab_detail": lab_detail}
    data = llm.chat_json(MULTIMODAL_SYSTEM, json.dumps(context, ensure_ascii=False), temperature=0.25, max_tokens=1800)
    return _norm_multimodal(data)


def _norm_multimodal(data: dict) -> dict:
    findings = []
    for i, f in enumerate((data.get("findings") or [])[:4]):
        if not isinstance(f, dict) or not _s(f.get("title")):
            continue
        sev = _s(f.get("severity"), "info")
        if sev not in ("crit", "warn", "info"):
            sev = "info"
        rows = []
        for r in (f.get("data") or [])[:4]:
            if isinstance(r, dict) and _s(r.get("k")):
                cls = _s(r.get("cls"))
                if cls not in ("warn", "hl", "dim"):
                    cls = ""
                rows.append({"k": _s(r.get("k")), "v": _s(r.get("v")), "cls": cls})
        when_cls = _s(f.get("when_cls"))
        if when_cls not in ("red", "green", ""):
            when_cls = ""
        acts = []
        for a in (f.get("acts") or [])[:2]:
            if isinstance(a, dict) and _s(a.get("a")) in MMA_ACT_CODES and _s(a.get("t")):
                acts.append({"t": _s(a.get("t")), "a": _s(a.get("a")), "primary": bool(a.get("primary"))})
        advice = [_safe_rich(x) for x in (f.get("advice") or [])[:3] if _s(x)]
        findings.append({
            "severity": sev,
            "label": _s(f.get("label")) or ("发现 " + str(i + 1)),
            "title": _s(f.get("title")),
            "text": _safe_rich(f.get("text")),
            "data": rows,
            "when": _s(f.get("when")),
            "when_cls": when_cls,
            "advice": advice,
            "acts": acts,
        })
    return {"kind": "multimodal", "intro": _safe_rich(data.get("intro")), "findings": findings}
