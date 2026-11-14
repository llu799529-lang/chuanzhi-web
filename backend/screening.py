"""筛查编排：把「眼底 / 图片 / 症状 / 多模态综合」四条业务流程从 HTTP 路由里拿出来。**全项目唯一实现。**

为什么要有这一层
----------------
以前同一件事散在四个入口里，而且已经不一致：

| 事情 | 以前在哪 | 不一致之处 |
|---|---|---|
| 「大模型判图 → 本地模型覆盖分级」 | main 的 /api/ai/image、agent.py 的 analyze_image 工具 | Agent 版不传图像质量，糊图也会做边界升级 |
| 本地模型分级 + 分诊 | main 的 /api/fundus/analyze、mcp_server 的 analyze_fundus | MCP 非演示分支调 `triage_fundus(level, conf)` 时**没传概率**，边界病例不会保守升级 |
| 热力图失败处理 | 三处各写一遍 | 一处给空串 + 状态，一处直接省略字段，一处只 print |
| 落库 | 三个路由各写一条 INSERT | 每处自己记得脱敏 |

现在 HTTP 路由、Agent 工具、MCP 工具都只调这里；路由只剩「解析请求 → 调用 → 包装响应」。

这一层不认识 HTTP：失败抛 `errors.*`，由 HTTP 层翻译成状态码。
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import uuid

import ai_analysis
import cache
import citations
import config
import errors
import guardrails
import llm
import rag
import records
import safety
from fundus import analyzer
from quality import verifier as quality_verifier
from quality_check import assess as assess_image_quality
from triage import triage_fundus

DR_LABELS = ["无病变", "轻度NPDR", "中度NPDR", "重度NPDR", "增殖期PDR"]


# ---------------------------------------------------------------- 眼底：本地模型
def grade_local(image_bytes: bytes, shot: dict | None = None) -> dict:
    """本地分级（真实权重或演示模式）+ 图像质量 + 分诊。返回 probs 为 0–1 小数。

    分诊**总是**带上概率与图像质量：边界病例保守升级依赖概率，糊图不做升级依赖质量。
    （MCP 的旧实现漏传概率，Agent 的旧实现漏传质量——两处都由这里统一修正。）
    """
    result = analyzer.analyze(image_bytes)
    probs, level = result["probabilities"], result["level"]
    shot = shot or assess_image_quality(image_bytes)
    tri = triage_fundus(level, probs[level], probs, quality=shot["quality"])
    return {"probs": probs, "level": level, "confidence": probs[level], "shot": shot, "triage": tri,
            "engine": "demo" if analyzer.is_demo else "local"}


def heatmap(image_bytes: bytes, level: int) -> tuple[str, str]:
    """(base64 PNG, 状态)。真实模型的 Grad-CAM 失败时**不伪造**模拟热点：返回空串 + unavailable。"""
    hm, status, _ = heatmap_layers(image_bytes, level)
    return hm, status


def heatmap_layers(image_bytes: bytes, level: int) -> tuple[str, str, str]:
    """(叠加图 base64, 状态, 透明热力层 base64)。热力层给前端「专业阅片」叠在增强 / 无赤光图上用；拿不到时为空串。"""
    status = "demo" if analyzer.is_demo else "gradcam"
    try:
        make = getattr(analyzer, "make_heatmap_layers", None)
        blended, layer = make(image_bytes, level) if make else (analyzer.make_heatmap(image_bytes, level), b"")
        return base64.b64encode(blended).decode(), status, base64.b64encode(layer).decode() if layer else ""
    except Exception as e:
        guardrails.log_event("fundus.heatmap.failed", error=type(e).__name__)
        return "", "unavailable", ""


def apply_local_model(analysis: dict, image_bytes: bytes) -> dict:
    """大模型判为眼底时，用本地专用模型的分级**覆盖**大模型的视觉估计（就地修改并返回）。

    大模型只负责「这是什么图」和病灶描述；分级数字以训练过的模型为准。
    没有本地权重（演示模式）时保持大模型结果，只补质量字段。
    """
    if analysis.get("kind") != "fundus":
        return analysis
    shot = assess_image_quality(image_bytes)
    if not analyzer.is_demo:
        llm_level = analysis.get("level")
        g = grade_local(image_bytes, shot)
        lvl, probs, tri = g["level"], g["probs"], g["triage"]
        analysis.update({
            "level": lvl, "level_label": tri["level_name"], "level_label_long": tri["level_name"],
            "probabilities": [round(p * 100, 1) for p in probs], "confidence": round(probs[lvl], 4),
            "department": tri["department"], "urgency": tri["urgency"], "urgency_label": tri["urgency_label"],
            "engine": "local",
        })
        if isinstance(llm_level, int) and llm_level != lvl:
            # 大模型写的分级依据与总结对应它自己估的级别：与本地模型的分级不一致时，依据改用标准条文（前端按级别生成），
            # 总结里写明两者不一致、以本地模型为准——以前会出现「4 级 · 增殖期」下面写着「符合中度非增殖期表现」。
            analysis["criteria"] = []
            analysis["llm_level"] = llm_level
            analysis["summary"] = (str(analysis.get("summary") or "").rstrip("。") +
                                   f"。（大模型看图估计为 {llm_level} 级，分级以本地模型为准；病灶描述来自大模型，仅供参考）")
    else:
        analysis.setdefault("engine", "llm")
    analysis["image_quality"] = shot["quality"]
    analysis["quality_reasons"] = shot["reasons"]
    analysis["retake"] = shot["retake"]
    return analysis


def _pre_visit_notes(level: int) -> list[str]:
    notes = [
        "就诊前整理既往病史、糖尿病/高血压病程与用药情况",
        "如正在使用散瞳药物或有青光眼病史，请提前告知医生",
    ]
    if level >= 3:
        notes.insert(0, "携带近期血糖记录（空腹血糖/糖化血红蛋白）")
    if level >= 2:
        notes.append("避免剧烈运动，出现视力骤降立即急诊")
    return notes


EYE_CN = {"right": "右眼", "left": "左眼"}


def fundus_report(image_bytes: bytes, mime: str, username: str, eye: str | None = None) -> dict:
    """眼底筛查页：本地模型优先 → 无权重时大模型 → 再不行演示模式。返回完整报告并落库。"""
    probs = level = ai = None
    mode = "demo"
    shot = assess_image_quality(image_bytes)
    if not analyzer.is_demo:
        r = analyzer.analyze(image_bytes)
        probs, level, mode = r["probabilities"], r["level"], "model"
    elif llm.llm_available():
        try:
            ai = ai_analysis.analyze_image(image_bytes, mime or "image/jpeg", username)
        except Exception as e:
            guardrails.log_event("fundus.llm_failed", error=type(e).__name__)
            ai = None
        if ai is not None:
            if ai.get("kind") != "fundus":
                raise errors.BadRequest("图片不是眼底彩照，请上传视网膜环形视野的眼底图像")
            probs, level, mode = [p / 100 for p in ai["probabilities"]], ai["level"], "llm"
    if probs is None:
        r = analyzer.analyze(image_bytes)
        probs, level = r["probabilities"], r["level"]
    tri = triage_fundus(level, probs[level], probs, quality=shot["quality"])
    if ai:  # 大模型检出的病灶替代规则文案
        tri["lesions"] = "、".join(f"{x['type']}×{x['count']}" for x in ai.get("lesions") or []) or tri["lesions"]
    hm, hm_status, hm_layer = heatmap_layers(image_bytes, level)
    payload = {
        "record_id": uuid.uuid4().hex[:12],
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "input_type": "眼底彩照",
        "mode": mode,
        "probabilities": [{"level": i, "label": DR_LABELS[i], "probability": round(p, 4)} for i, p in enumerate(probs)],
        "heatmap": hm,
        "heatmap_status": hm_status,
        "heatmap_layer": hm_layer,
        **tri,
        # 质量不达标时仍返回分级结论（用户可能只有这一张图），前端据此提示「请重拍」。
        "image_quality": shot["quality"],
        "quality_reasons": shot["reasons"],
        "quality_metrics": shot["metrics"],
        "retake": shot["retake"],
        "pre_visit_notes": _pre_visit_notes(tri.get("escalated_to") or level),
        "disclaimer": config.DISCLAIMER,
    }
    if ai:
        payload["ai_summary"] = ai.get("summary", "")
    eye = eye if eye in EYE_CN else None
    if eye:                                   # 双眼联合筛查：标明是哪只眼，记录摘要也带上
        payload["eye"] = eye
    records.add(username, "眼底彩照", level, tri["department"], tri["urgency"],
                (f"{EYE_CN[eye]} · " if eye else "") + tri["doctor_summary"], payload["timestamp"])
    return payload


# ---------------------------------------------------------------- 任意图片（工作台聊天）
def image_report(image_bytes: bytes, mime: str, username: str) -> dict:
    """大模型判别眼底 / 化验单 / 其它；眼底再由本地模型覆盖分级。需要可用的大模型（调用方先检查）。"""
    try:
        data = ai_analysis.analyze_image(image_bytes, mime or "image/jpeg", username)
    except Exception as e:
        raise errors.Upstream(f"AI 分析失败：{e}") from e
    kind = data.get("kind")
    if kind == "other":
        return {**data, "disclaimer": config.DISCLAIMER}
    if kind == "fundus":
        apply_local_model(data, image_bytes)
        hm, status, layer = heatmap_layers(image_bytes, data["level"])
        data["heatmap_status"] = status
        if hm:
            data["heatmap"] = hm
        if layer:
            data["heatmap_layer"] = layer
        records.add(username, "眼底彩照", data["level"], data["department"], data["urgency"],
                    f"DR {data['level']} · {data.get('level_label_long', '')}")
    else:
        records.add(username, "化验单", None, data["department"], data["urgency"],
                    f"{data['report_title']} · {data['abnormal_count']} 项异常")
    return {**data, "disclaimer": config.DISCLAIMER}


# ---------------------------------------------------------------- 症状
def symptom_fallback(text: str, reason: str, kb_query: str | None = None) -> dict:
    """模型超时 / 整条链路异常时的规则兜底。

    超时：知识库是好的，带 `kb_query` 检索后再组织结果；
    链路异常：连检索都可能是出错的那一环，`kb_query=None` 时不检索，直接给保守的通用卡。
    """
    kb = rag.retrieve(kb_query) if kb_query else []
    return ai_analysis._rule_based_symptom(text, kb, reason)


def finalize_symptom(data: dict, safe_text: str, username: str) -> dict:
    """症状卡出门前的统一处理：红旗托底（幂等）→ 越界扫描 → 可核验性分档 → 落库。

    超时 / 兜底分支绕过了 analyze_symptom 内部的红旗托底，所以必须在这里再做一次。
    """
    flags = safety.detect(safe_text)
    data = safety.apply_floor(data, flags)
    if flags and isinstance(data.get("safety"), dict):
        data["safety"]["basis"] = citations.safety_basis(flags)      # 红旗规则对应的国内指南（主题级）
    guard = guardrails.check_payload(data)
    # 把要给人看的文字拆句，逐句对知识库找落点（纯增量字段，前端不认也不受影响）。
    data["verification"] = quality_verifier.verify(
        "。".join(str(data.get(k) or "") for k in ("echo", "alt", "urg")), rag.all_entries())
    records.add(username, "症状描述", None, data["dept"], data["urgency"], data["echo"])
    return {**data, **guard, "disclaimer": config.DISCLAIMER}


# ---------------------------------------------------------------- 多模态综合
# 同样的历史 + 同样的化验单明细，10 分钟内不重复调用模型。有上限：key 几乎不会重复命中，不设上限就只增不减。
_MULTIMODAL_CACHE = cache.TTLCache(ttl_seconds=600, max_items=200)


def _multimodal_key(username: str, history: list[dict], lab_detail: dict | None) -> str:
    parts = [username] + ["|".join((r["input_type"] or "", r["created_at"] or "")) for r in history]
    if lab_detail:
        parts.append(json.dumps(lab_detail, sort_keys=True, ensure_ascii=False))
    return hashlib.sha1("§".join(parts).encode("utf-8")).hexdigest()[:16]


def multimodal_report(username: str, lab_detail: dict | None) -> dict:
    """当前用户历史记录（眼底 / 化验 / 症状）+ 最近化验单明细 → 大模型交叉分析。"""
    history = records.recent(username, 20)
    if not history and not lab_detail:
        raise errors.BadRequest("暂无筛查记录，请先完成眼底 / 化验单 / 症状任一筛查")
    key = _multimodal_key(username, history, lab_detail)
    data = _MULTIMODAL_CACHE.get(key)
    cached = data is not None
    if not cached:
        try:
            data = ai_analysis.analyze_multimodal(history, lab_detail)
        except Exception as e:
            raise errors.Upstream(f"综合分析失败：{e}") from e
        _MULTIMODAL_CACHE.put(key, data)
    # 越界扫描每次都做：旧实现命中缓存时直接返回，响应里少了 guard / red_flags 字段。
    out = {**data, **guardrails.check_payload(data), "record_count": len(history), "disclaimer": config.DISCLAIMER}
    if cached:
        out["cached"] = True
    return out
