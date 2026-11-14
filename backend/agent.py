"""MedTriage ReAct 自主规划 Agent（真实工具调用循环）。

链路：大模型逐步决策（Thought → Action）→ 真实工具执行 → Observation 回填 →
循环直到生成综合报告。工具全部为真实函数：
  get_history    查询 SQLite 历史筛查记录
  analyze_image  大模型多模态判图 + 本地分级模型覆盖（复用 screening.apply_local_model）
  search_kb      RAG 知识库检索（复用 rag.retrieve）
  calc_risk      规则引擎综合风险评估
事件流返回前端渲染（思考气泡 / 追问卡 / 工具卡 / 综合报告）。
"""
import re

import ai_analysis
import guardrails
import llm
import rag
import records
import screening

MAX_ROUNDS = 6

TOOL_NAMES = ["get_history", "analyze_image", "search_kb", "calc_risk", "gen_report"]
TOOL_LABELS = {
    "get_history": "查询历史记录",
    "analyze_image": "图像分析 · 自动判别",
    "search_kb": "知识库 RAG 检索",
    "calc_risk": "进展风险评估",
    "gen_report": "生成综合报告",
}

AGENT_SYSTEM = """你是 MedTriage 糖网筛查系统的 ReAct 规划 Agent，负责决定每一步做什么。
每一步只输出一个 JSON：{"thought":"一句简短思考","action":"动作名","args":{}}

可用动作：
- ask：向用户追问关键背景。args:{"question":"问题","hint":"为什么问，一句话","chips":["选项A","选项B",...]}
  仅当缺少真正影响判断的信息时用（糖尿病病程 / 血糖控制情况 / 视力变化 / 上次眼底检查时间）。
  规则：一次只问 1 个问题，chips 给 3-5 个选项；用户消息已含相关信息、用户表示不想提供、
  或本会话已追问过 → 绝对不要再问，直接进入工具调用。
- get_history：查询该用户历史筛查记录（无需参数）
- analyze_image：分析用户上传的图片，自动判别眼底彩照 / 化验单（无需参数；仅用户已上传图片时可用）
- search_kb：检索内置医学知识库。args:{"query":"检索词"}
- calc_risk：综合进展风险评估（无需参数；在已有图像分析或症状结果后调用）
- final：生成最终报告（信息足够时调用）

决策原则：
1. 用户上传了图片：若关键背景（病程 / 血糖 / 视力变化）未知且本会话未追问过 → 先 ask 一次；
   否则直接开始工具调用。
2. 典型顺序：get_history（有价值时）→ analyze_image（有图时）→ search_kb → calc_risk → final。
3. 纯文字症状描述：search_kb → calc_risk（可选）→ final。
4. thought 用一句大白话说清这一步为什么。
只输出一个 JSON 对象，禁止任何解释文字或代码围栏。"""

FINAL_SYSTEM = """你是 MedTriage 糖网筛查助手，现在汇总一次 ReAct 分析的全部结果，写给普通用户看。
只输出一个 JSON：
{"plain":"3-4 句大白话总结：先说结论（分级 / 主要问题），再说与上次相比的变化（如有历史），最后说该多快复查",
 "extra":["结合用户背景信息的补充建议 2-3 条，每条一句话大白话"],
 "attention":["需要特别注意的信号 1-3 条，没有则给空数组"]}
要求：
- 全部用大白话短句，像跟朋友解释体检报告；专业词第一次出现时用括号解释，
  例如「硬性渗出（血管渗漏出的脂质沉淀）」。
- 严格依据【用户描述】和各工具结果组织内容，禁止编造用户没提过的症状或数值；
  用户没上传图片就不要提图片；本次没有分级结果（纯文字咨询）就如实说明。
- 不诊断、不开药；急症信号（视力骤降、视野缺损等）要醒目提示立即就医。
- 分级、概率、病灶等具体数字必须与工具结果完全一致，禁止改动或编造。
只输出一个 JSON 对象。"""

SESSIONS: dict[str, dict] = {}


def reset(username: str) -> None:
    SESSIONS.pop(username, None)


def _new_session() -> dict:
    return {
        "image": None, "mime": "image/jpeg",
        "asked": False, "collected": [],
        "transcript": [], "used": [],
        "history": None, "analysis": None, "kb": None, "risk": None,
        "done": False,
    }


def _state_digest(s: dict) -> str:
    lines = [
        f"用户已上传图片：{'是' if s['image'] else '否'}",
        f"本会话已追问过：{'是' if s['asked'] else '否'}",
        f"已调用工具：{', '.join(s['used']) if s['used'] else '无'}",
    ]
    if s["collected"]:
        for q, a in s["collected"]:
            lines.append(f"用户已确认：{q} → {a}")
    return "\n".join(lines)


def _decide(s: dict) -> dict:
    content = "【当前状态】\n" + _state_digest(s) + "\n\n【对话与工具观察】\n"
    for m in s["transcript"][-12:]:
        role = {"user": "用户", "assistant": "你", "tool": "工具观察"}[m["role"]]
        content += f"{role}: {m['content']}\n"
    content += "\n请输出下一步决策 JSON。"
    try:
        data = llm.chat_json(AGENT_SYSTEM, content, temperature=0.3)
    except Exception:
        return {"thought": "决策调用失败，直接汇总生成报告。", "action": "final", "args": {}}
    action = str(data.get("action", "final")).strip()
    if action not in ("ask", "final", "get_history", "analyze_image", "search_kb", "calc_risk"):
        action = "final"
    if action == "analyze_image" and not s["image"]:
        action = "search_kb"
        data["args"] = {"query": "糖尿病视网膜病变"}
    return {
        "thought": str(data.get("thought", "")).strip() or "继续分析。",
        "action": action,
        "args": data.get("args") or {},
    }


def _fmt_history(s: dict) -> str:
    rows = s["history"] or []
    if not rows:
        return "该用户暂无历史筛查记录。"
    out = [f"返回 {len(rows)} 条历史："]
    for r in rows:
        lv = f" · DR {r['level']} 级" if r.get("level") is not None else ""
        out.append(f"{r['created_at'][:10]}{lv} · {r['department']}")
    return "\n".join(out)


def _fmt_analysis(s: dict) -> str:
    d = s["analysis"]
    if not d:
        return "尚未分析。"
    if d["kind"] == "fundus":
        les = " · ".join(f"{x['type']} {x['count']}" for x in d.get("lesions", [])[:4]) or "未见明显病灶"
        conf = d.get("confidence")
        conf_txt = f"{conf * 100:.1f}%" if isinstance(conf, (int, float)) and conf and conf <= 1 else str(conf)
        return (f"图片为眼底彩照。DR {d['level']} 级 · {d['level_label_long']} · "
                f"置信度 {conf_txt}\n病灶：{les}\n建议：{d['urgency_label']}")
    if d["kind"] == "lab":
        abn = [i for i in d.get("items", []) if i["flag"] != "normal"]
        items = " · ".join(f"{i['name']} {i['value']}" for i in abn[:4]) or "未见明显异常"
        checks = f"\n{d['value_checks']} 项数值与单位或参考范围对不上，需对照原单核对" if d.get("value_checks") else ""
        return (f"图片为化验单（{d['report_title']}）。{d['abnormal_count']} 项异常：{items}{checks}\n"
                f"建议：{d['department']} · {d['urgency_label']}")
    if d["kind"] == "symptom":
        sus = " · ".join(f"{s2[0]} {s2[1]}%" for s2 in d.get("suspects", [])[:3])
        return (f"纯文字症状分诊：{d.get('echo', '')} → 建议 {d.get('dept', '')}（{d.get('urg', '')}）\n"
                f"疑似方向：{sus}\n红旗信号：{'；'.join(d.get('reds', [])[:2]) or '无'}")
    return f"图片既非眼底彩照也非化验单：{d.get('summary', '')}"


def _parse_years(texts: str) -> int | None:
    m = re.search(r"糖尿病[^，。；;\d]{0,12}(\d+)\s*年", texts)
    return int(m.group(1)) if m else None


def _parse_hba1c(texts: str) -> float | None:
    m = re.search(r"(?:糖化(?:血红蛋白)?|hba1c)[^，。；;\d]{0,8}(\d+(?:\.\d+)?)", texts, re.I)
    return float(m.group(1)) if m else None


def _calc_risk(s: dict) -> dict:
    """规则引擎综合风险评估（真实计算，不调大模型）。"""
    # Only use user statements, never model-generated tool arguments as facts.
    texts = []
    for q, a in s.get("collected", []):
        # A question lists possibilities, not confirmed findings. Only attach a
        # field label when the answer itself explicitly supplies its value.
        if "糖尿病" in q and re.fullmatch(r"\s*\d+\s*年\s*", a):
            texts.append("糖尿病病程" + a)
        elif ("糖化" in q or "hba1c" in q.lower()) and re.fullmatch(r"\s*\d+(?:\.\d+)?\s*%?\s*", a):
            texts.append("糖化血红蛋白" + a)
        else:
            texts.append(a)
    for m in s.get("messages") or s.get("transcript") or []:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            if not m["content"].startswith("请基于以下工具结果"):
                texts.append(m["content"])
    # Conservative handling: uncertain/negated clauses are not positive findings.
    clauses = re.split(r"[，,。；;\n]|但是|但", "；".join(texts))
    collected = "；".join(c for c in clauses if not re.search(r"没有|无|未|否认|不确定|不伴", c))
    d = s["analysis"] or {}
    years = _parse_years(collected)
    hba = _parse_hba1c(collected)
    if hba is None:
        for it in (d.get("items") or []) if d.get("kind") == "lab" else []:
            if "糖化" in it["name"]:
                try:
                    hba = float(it["value"])
                    break
                except (ValueError, TypeError):
                    pass
    level = d.get("level") if d.get("kind") == "fundus" else None
    prev = None
    for r in (s.get("history") or []):
        if r.get("input_type") == "眼底彩照" and r.get("level") is not None:
            prev = r["level"]
            break
    return score_risk(
        years=years, hba1c=hba,
        vision_change=any(k in collected for k in ("模糊", "下降", "黑影", "飞蚊")),
        vision_sudden="突发" in collected or "骤" in collected,
        hypertension="高血压" in collected,
        dyslipidemia="高血脂" in collected or "血脂" in collected,
        level=level, prev_level=prev)


def score_risk(*, years=None, hba1c=None, vision_change=False, vision_sudden=False,
               hypertension=False, dyslipidemia=False, level=None, prev_level=None) -> dict:
    """糖网进展辅助规则的**唯一**评分实现（Agent 的 `_calc_risk` 与 MCP 的 `calc_risk` 共用）。

    原来这两处各写了一份，且已经不一致：MCP 版没有「信息不足 → 待评估」的处理，
    什么都没给时会返回「低风险」——对筛查工具来说这是最危险的一种错。现在只留这一份。
    入参是**已经解析好的特征**（解析 / 否定处理在 `_calc_risk` 里，因为那需要会话文本）。
    """
    score, reasons = 0, []
    if years:
        if years >= 10:
            score += 3
            reasons.append(f"糖尿病病程 {years} 年")
        elif years >= 5:
            score += 2
            reasons.append(f"糖尿病病程 {years} 年")
    if hba1c:
        if hba1c >= 8.0:
            score += 3
            reasons.append(f"糖化血红蛋白 {hba1c}%（明显偏高）")
        elif hba1c >= 7.0:
            score += 2
            reasons.append(f"糖化血红蛋白 {hba1c}%（未达标）")
    if vision_change:
        score += 2
        if vision_sudden:
            score += 2
            reasons.append("视力突发变化（急症信号）")
        else:
            reasons.append("近期视力变化")
    if hypertension:
        score += 1
        reasons.append("合并高血压")
    if dyslipidemia:
        score += 1
        reasons.append("合并血脂异常")
    if level is not None and prev_level is not None:
        if level > prev_level:
            score += 3
            reasons.append(f"分级较上次上升（{prev_level} → {level} 级）")
        elif level < prev_level:
            reasons.append(f"分级较上次好转（{prev_level} → {level} 级）")
    if level is not None and level >= 2:
        score += 2
        reasons.append(f"当前 DR {level} 级")

    if score >= 7:
        risk = "高"
    elif score >= 5:
        risk = "中高"
    elif score >= 3:
        risk = "中"
    else:
        risk = "低"
    assessable = bool(years or hba1c or level is not None or reasons)
    if not assessable:
        risk = "待评估"
        reasons = ["缺少本规则可用的糖网进展相关信息，不能据此判断低风险；请结合分诊建议。"]
    return {"risk": risk, "score": score, "reasons": reasons,
            "assessable": assessable, "scope": "糖网进展辅助规则（非通用急症风险或诊断）"}


def _run_tool(s: dict, username: str, action: str, args: dict) -> dict:
    if action == "get_history":
        s["history"] = records.recent(username, 5)
        call, argstxt, result = "get_history(limit=5)", "近 5 次筛查记录", _fmt_history(s)
        warn = False

    elif action == "analyze_image":
        # 模型在纯文字场景里也可能调 analyze_image（历史上就发生过）。
        # 此时 s["image"] 是 None，直接往下走会在 base64.b64encode(None) 处
        # 抛 TypeError，把整个 SSE 流打断，用户只看到「分析失败」。
        # 正确做法是把它当成一次「无图可分析」的工具结果交还给模型，
        # 让模型自己决定改用 search_kb，而不是让整条链路崩掉。
        if not s.get("image"):
            call, argstxt = "analyze_image(image)", "未上传图片"
            result = "当前会话没有已上传的图片，无法做图像分析。请改用 search_kb 依据症状检索，或提示用户上传眼底彩照 / 化验单。"
            warn = True
        else:
            d = ai_analysis.analyze_image(s["image"], s["mime"], username)
            # 本地专用模型分级优先：与 /api/ai/image 是**同一个实现**（screening.apply_local_model），
            # 大模型只负责判图类型和病灶描述。旧实现在这里自己调 triage_fundus 且漏传图像质量，糊图也会做边界升级。
            screening.apply_local_model(d, s["image"])
            local = d.get("kind") == "fundus" and d.get("engine") == "local"
            engine_note = "本地分级模型 + 大模型病灶描述" if local else "自动判别 · 大模型视觉"
            if local:
                hm, _status = screening.heatmap(s["image"], d["level"])
                if hm:
                    d["heatmap"] = hm
            s["analysis"] = d
            query = "眼底 彩照"
            call, argstxt, result = "analyze_image(image)", engine_note, _fmt_analysis(s)
            warn = d.get("kind") == "other"

    elif action == "search_kb":
        query = str(args.get("query", "")).strip() or "糖尿病视网膜病变"
        hits = rag.retrieve(query, top_k=3)
        s["kb"] = rag.refs_payload(hits)
        s["kb_context"] = rag.format_context(hits)[:12000]
        # 证据编号的唯一来源：与 kb_context 里的 [i] 编号同一份检索结果（见 citations.from_hits）
        s["evidence_hits"] = hits
        call = f'search_kb("{query}")'
        argstxt = "top_k: 3"
        if hits:
            lines = [f"命中 {len(hits)} 条："]
            for h in hits:
                e = h["entry"]
                lines.append(f"· {e.get('category', '')} → {e.get('dept', '')}"
                             + (f"（命中：{'、'.join(h['matched'][:3])}）" if h["matched"] else ""))
            result = "\n".join(lines) + "\n参考知识：\n" + s["kb_context"]
        else:
            result = "未命中相关知识条目。"
        warn = not hits

    elif action == "calc_risk":
        risk = _calc_risk(s)
        s["risk"] = risk
        call, argstxt = "calc_risk(history, current, symptoms)", "规则引擎 · 综合评估"
        result = f"综合进展风险：{risk['risk']}" + (f"\n依据：{'；'.join(risk['reasons'])}" if risk["reasons"] else "")
        warn = risk["risk"] in ("高", "中高")
    else:
        raise ValueError("未知工具：" + str(action))

    s["used"].append(action)
    # session 的字段契约由调用方（agent.py 的 ReAct 循环 / agent2.py 的 FC 循环）决定。
    # agent2 只维护 messages，没有 transcript；这里用 setdefault 而不是直接 append，
    # 否则复用 _run_tool 的 v2 链路会在工具执行完后 KeyError 崩掉整条 SSE 流。
    s.setdefault("transcript", []).append({"role": "tool", "content": f"[{action}] {result}"})
    return {"t": "tool", "name": action, "call": call, "args": argstxt, "result": result, "warn": warn}


def _final(s: dict, username: str) -> dict:
    """生成综合报告：结构化数据直接取真实工具结果，大白话由大模型汇总。"""
    d = s["analysis"]
    kind = d["kind"] if d else None
    user_texts = "；".join(m["content"] for m in s["transcript"] if m["role"] == "user")
    if not d:
        # 纯文字症状：final 前补一次症状分析（真实调用）
        d = ai_analysis.analyze_symptom(user_texts, username)
        kind = "symptom"

    obs = []
    if user_texts:
        obs.append("[用户描述] " + user_texts)
    if s["history"] is not None:
        obs.append("[get_history] " + _fmt_history(s))
    if d:
        obs.append("[analyze] " + _fmt_analysis({"analysis": d}))
    if s["kb"]:
        obs.append("[search_kb] " + (s.get("kb_context") or
                   "命中 " + "、".join(h["category"] for h in s["kb"])))
    if s["risk"]:
        r = s["risk"]
        obs.append(f"[calc_risk] 综合进展风险：{r['risk']}（{'; '.join(r['reasons'])}）")
    for q, a in s["collected"]:
        obs.append(f"[用户确认] {q} → {a}")

    prompt = "【工具结果与用户信息】\n" + "\n".join(obs) + "\n\n请生成汇总 JSON。"
    plain, extra, attention = "", [], []
    try:
        f = llm.chat_json(FINAL_SYSTEM, prompt, temperature=0.4)
        plain = str(f.get("plain", "")).strip()
        extra = [str(x).strip() for x in (f.get("extra") or [])[:3] if str(x).strip()]
        attention = [str(x).strip() for x in (f.get("attention") or [])[:3] if str(x).strip()]
    except Exception as e:
        # 大模型汇总失败 → 用户仍然拿到结构化报告，只是少了那段大白话。
        # 这是「降级」不是「失败」，但必须能看见，否则线上永远不知道模型在报错。
        guardrails.log_event("agent.final.degraded", user=username,
                             error=f"{type(e).__name__}: {str(e)[:120]}")
    if not plain:
        plain = "分析完成，详细结果见下方报告。"

    if kind in ("fundus", "lab"):
        data = d
    else:
        data = d
        if s["kb"] and "kb_hits" not in data:
            data["kb_hits"] = s["kb"]

    records.save(username, data)

    s["done"] = True
    ev = {"t": "report", "kind": kind, "data": data, "plain": plain, "extra": extra, "attention": attention}
    if s["risk"]:
        ev["risk"] = s["risk"]
    return ev


def _bg_mentioned(s: dict) -> bool:
    """用户消息里是否已带关键背景（病程 / 血糖 / 视力），有则跳过追问。"""
    txt = " ".join(m.get("content", "") for m in s["transcript"] if m["role"] == "user")
    return any(k in txt for k in ("年", "%", "血糖", "糖化", "病程", "视力"))


def handle_message(username: str, text: str, image: bytes | None, mime: str) -> dict:
    """【legacy】Agent v1：手写 ReAct JSON 协议，一次性返回全部事件。

    现在线上走的是 `agent2.stream()`（原生 Function Calling + SSE）。
    v1 保留有两个具体理由，不是为了兼容而兼容：
      1. `/api/agent/chat` 是非流式端点，老前端在 SSE 不可用时会退到它；
      2. `agent2` 复用了本模块的 `_run_tool` / `_fmt_*` / `_calc_risk` ——
         工具实现只有一份，两条链路共享。
    **新功能不要加在这里**：两套循环各自演化的代价已经出现过一次
    （落库字段一个用 `urgency_key` 一个用 `urg`），现在统一在 `records.py`。
    """
    """Agent 主入口：接收一条用户消息（文字 / 图片），推进 ReAct 直到追问或报告。"""
    if not llm.llm_available():
        raise RuntimeError("大模型未启用：请设置环境变量 ARK_API_KEY")

    s = SESSIONS.get(username)
    if s is None or s.get("done"):
        s = SESSIONS[username] = _new_session()
    if image:
        s["image"], s["mime"] = image, mime
    if text:
        t = text.strip()
        # 上一条是追问且本条是用户回答 → 记入已收集信息（供风险评估解析）
        if (s["asked"] and s["transcript"]
                and s["transcript"][-1]["role"] == "assistant"
                and s["transcript"][-1]["content"].startswith("[追问]")):
            s["collected"].append((s["transcript"][-1]["content"][4:].strip(), t))
        s["transcript"].append({"role": "user", "content": t})

    events: list[dict] = []

    # ---- 快速路径：带图消息 → 脚本化工具序列 ----
    # 原版每步都调大模型决策（6-7 次串行调用 ≈ 40 秒）；带图流程是固定的，
    # 直接按固定顺序执行工具，只保留 analyze_image 和 final 两次必要大模型调用。
    if s["image"] and "analyze_image" not in s["used"]:
        if not s["asked"] and not s["collected"] and not _bg_mentioned(s):
            q = "你确诊糖尿病多久了？"
            chips = ["5 年以内", "5–10 年", "10 年以上", "不确定 / 没查过", "跳过，直接分析"]
            s["asked"] = True
            s["transcript"].append({"role": "assistant", "content": f"[追问] {q}"})
            events.append({"t": "thought", "n": 1, "text": "先补充一个关键背景，风险评估会更准。"})
            events.append({
                "t": "ask", "question": q,
                "hint": "糖尿病病程直接影响糖网进展速度和复查频率",
                "chips": chips,
            })
            return {"phase": "asking", "tools": TOOL_LABELS, "events": events}

        step = 0

        def _think(txt: str) -> None:
            nonlocal step
            step += 1
            events.append({"t": "thought", "n": step, "text": txt})
            s["transcript"].append({"role": "assistant", "content": txt})

        _think("先查一下你的历史筛查记录，看看有没有可对比的结果。")
        events.append(_run_tool(s, username, "get_history", {}))
        _think("用本地分级模型定级，视觉大模型补充病灶描述。")
        events.append(_run_tool(s, username, "analyze_image", {}))
        kind = (s["analysis"] or {}).get("kind")
        if kind == "fundus":
            _think("结合本次分级，检索对应的随访和转诊建议。")
            events.append(_run_tool(s, username, "search_kb",
                                    {"query": f"糖尿病视网膜病变 {s['analysis']['level_label_long']} 随访"}))
        elif kind == "lab":
            _think("检索这些异常指标的临床意义。")
            events.append(_run_tool(s, username, "search_kb", {"query": "糖尿病 并发症 筛查"}))
        _think("把历史记录、本次分级和背景信息放一起，做综合风险评估。")
        events.append(_run_tool(s, username, "calc_risk", {}))
        _think("信息齐了，生成综合报告。")
        events.append(_final(s, username))
        return {"phase": "done", "tools": TOOL_LABELS, "events": events}

    # ---- 无图消息：保留 ReAct 逐步决策 ----
    step = 0
    for _ in range(MAX_ROUNDS):
        step += 1
        decision = _decide(s)
        events.append({"t": "thought", "n": step, "text": decision["thought"]})
        s["transcript"].append({"role": "assistant", "content": decision["thought"]})
        action = decision["action"]

        if action == "ask":
            args = decision["args"]
            q = str(args.get("question", "")).strip() or "能补充一点背景信息吗？"
            chips = [str(c).strip() for c in (args.get("chips") or [])[:5] if str(c).strip()]
            if "跳过" not in "".join(chips):
                chips.append("跳过，直接分析")
            s["asked"] = True
            s["transcript"].append({"role": "assistant", "content": f"[追问] {q}"})
            events.append({
                "t": "ask", "question": q,
                "hint": str(args.get("hint", "")).strip(),
                "chips": chips,
            })
            return {"phase": "asking", "tools": TOOL_LABELS, "events": events}

        if action == "final" or (action in s["used"] and action != "search_kb"):
            # 信息足够（或工具已调过）→ 汇总
            ev = _final(s, username)
            events.append(ev)
            return {"phase": "done", "tools": TOOL_LABELS, "events": events}

        ev = _run_tool(s, username, action, decision["args"])
        events.append(ev)

    # 超过轮次上限：强制汇总
    events.append({"t": "thought", "n": step + 1, "text": "信息已足够，生成综合报告。"})
    events.append(_final(s, username))
    return {"phase": "done", "tools": TOOL_LABELS, "events": events}
