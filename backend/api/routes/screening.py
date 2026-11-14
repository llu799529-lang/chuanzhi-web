"""筛查：眼底（本地模型）/ 任意图片（大模型判别）/ 症状文字 / 多模态综合。

业务流程都在 `screening.py`；这里只做：鉴权 → 限流 → 读请求 → 放进线程池调用 → 返回。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.concurrency import run_in_threadpool

import ai_analysis
import config
import errors
import guardrails
import llm
import screening
from api.deps import check_text_length, current_user, rate_limit_ai, read_image
from api.schemas import MultimodalIn, SymptomIn

router = APIRouter(prefix="/api", tags=["screening"])

LLM_OFF = "大模型未启用：请设置环境变量 ARK_API_KEY"


@router.post("/fundus/analyze")
async def analyze_fundus(file: UploadFile = File(...), eye: str | None = None,
                         username: str = Depends(current_user)):
    """眼底分级。`eye=right|left`（可选）：双眼联合筛查时标明是哪只眼，其它值忽略。"""
    """眼底彩照 → DR 分级 + 概率 + 热力图 + 分诊。本地模型优先（不耗额度），无权重时才用大模型。"""
    image_bytes, mime = await read_image(file, "图片解析失败，请更换清晰的眼底照片")
    rate_limit_ai(username, "fundus")          # 本地推理 + Grad-CAM 也吃 CPU；无权重时还会调视觉模型
    return await run_in_threadpool(screening.fundus_report, image_bytes, mime, username,
                                  eye if eye in ("right", "left") else None)


@router.post("/ai/image")
async def ai_image(file: UploadFile = File(...), username: str = Depends(current_user)):
    """工作台聊天：上传任意图片，大模型判别眼底 / 化验单并返回结构化报告。"""
    if not llm.llm_available():
        raise errors.Unavailable(LLM_OFF)
    image_bytes, mime = await read_image(file)
    rate_limit_ai(username, "ai:image")        # 视觉模型是所有调用里最贵的一次，以前这里没有限流
    return await run_in_threadpool(screening.image_report, image_bytes, mime, username)


@router.post("/ai/symptom")
async def ai_symptom(body: SymptomIn, username: str = Depends(current_user)):
    """症状文字 → 结构化分诊。没有模型 / 额度耗尽 / 超时都不 503：降级到知识库规则结果并如实标注。"""
    text = (body.text or "").strip()
    if not text:
        raise errors.BadRequest("请输入症状描述")
    check_text_length(text)
    rate_limit_ai(username, "ai:symptom")
    safe_text = guardrails.mask_pii(text)          # 进模型前脱敏：手机号 / 身份证 / 邮箱不进推理链路
    try:
        # 硬超时：模型挂住时不让用户干等，到点走降级链
        data = await asyncio.wait_for(run_in_threadpool(ai_analysis.analyze_symptom, safe_text, username),
                                      timeout=config.LLM_TIMEOUT_SECONDS + 10)
    except asyncio.TimeoutError:   # noqa: UP041 —— Python 3.10 上它与内置 TimeoutError 不是同一个类
        guardrails.log_event("ai.symptom.timeout", user=username, limit=config.LLM_TIMEOUT_SECONDS)
        data = screening.symptom_fallback(text, "model timeout", kb_query=safe_text)
    except Exception as e:
        # analyze_symptom 内部已有降级；走到这里说明连规则引擎都炸了（极少），再兜一层
        guardrails.log_event("ai.symptom.error", user=username, err=type(e).__name__)
        data = screening.symptom_fallback(text, type(e).__name__)
    return await run_in_threadpool(screening.finalize_symptom, data, safe_text, username)


@router.post("/ai/multimodal")
async def ai_multimodal(body: MultimodalIn, username: str = Depends(current_user)):
    """当前用户历史记录 + 最近化验单明细 → 大模型交叉分析（10 分钟内同输入走缓存）。"""
    if not llm.llm_available():
        raise errors.Unavailable(LLM_OFF)
    rate_limit_ai(username, "ai:multimodal")
    return await run_in_threadpool(screening.multimodal_report, username, body.lab_detail)
