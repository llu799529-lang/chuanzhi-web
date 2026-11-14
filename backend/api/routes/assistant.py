"""Agent 助手（工作台聊天）与报告朗读。

主路径是 `/api/agent/chat/stream`（Agent v2，SSE）。没有可用的大模型时不 503：
agent2 会走离线分诊（真实工具 + 规则报告，如实标注「离线模式」）。
"""
from __future__ import annotations

import anyio
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse

import agent
import agent2
import errors
import guardrails
import llm
import tts
from api.deps import check_text_length, current_user, rate_limit_ai, read_image

router = APIRouter(prefix="/api", tags=["assistant"])


async def _optional_image(file: UploadFile | None) -> tuple[bytes | None, str]:
    if file is not None and file.filename:
        return await read_image(file)
    return None, "image/jpeg"


@router.post("/agent/chat")
async def agent_chat(text: str = Form(""), file: UploadFile | None = File(None),
                     username: str = Depends(current_user)):
    """Agent v1（非流式，兼容保留）。线上前端用的是 /api/agent/chat/stream。"""
    if not llm.llm_available():
        raise errors.Unavailable("大模型未启用：请设置环境变量 ARK_API_KEY")
    rate_limit_ai(username, "agent:chat")
    check_text_length(text)
    image_bytes, mime = await _optional_image(file)
    if not (text or "").strip() and image_bytes is None:
        raise errors.BadRequest("请输入内容或上传图片")
    # 埋点：好知道这个兼容端点还有没有人在用——没有数据就别谈"保留成本"。
    guardrails.log_event("agent.legacy_endpoint", user=username, has_image=image_bytes is not None)
    try:
        return await run_in_threadpool(agent.handle_message, username, (text or "").strip(), image_bytes, mime)
    except Exception as e:
        raise errors.Upstream(f"Agent 运行失败：{e}") from e


@router.post("/agent/reset")
def agent_reset(username: str = Depends(current_user)):
    agent.reset(username)
    agent2.reset(username)
    return {"ok": True}


class AgentStreamingResponse(StreamingResponse):
    """发送某个分块失败（客户端断开）时，也要关闭**这一个**异步迭代器。"""

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self.body_iterator.aclose()


@router.post("/agent/chat/stream")
async def agent_chat_stream(text: str = Form(""), file: UploadFile | None = File(None),
                            username: str = Depends(current_user)):
    """Agent v2 SSE：原生 Function Calling，plan / tool / reflect / repair / final 事件实时推送。"""
    text = (text or "").strip()
    check_text_length(text)
    image_bytes, mime = await _optional_image(file)
    if not text and image_bytes is None:
        raise errors.BadRequest("请输入内容或上传图片")
    rate_limit_ai(username, "agent:chat")

    async def gen():
        # 关闭的是**这一个**生成器；按用户名取消会误杀同一用户新开的会话。
        iterator = agent2.stream(username, text, image_bytes, mime)
        end = object()
        try:
            while True:
                chunk = await run_in_threadpool(next, iterator, end)
                if chunk is end:
                    break
                yield chunk
        except Exception as e:
            guardrails.log_event("agent.stream.failed", user=username, error=type(e).__name__)
            yield 'event: error\ndata: {"message": "分析暂时不可用，请重试。"}\n\n'
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                with anyio.CancelScope(shield=True):
                    await run_in_threadpool(close)

    return AgentStreamingResponse(gen(), media_type="text/event-stream",
                                  headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/tts")
def tts_endpoint(body: dict, username: str = Depends(current_user)):
    """报告朗读：edge-tts 可选，未装返回 503。"""
    if not tts.available():
        raise errors.Unavailable("TTS 未启用：pip install edge-tts")
    text = str(body.get("text") or "").strip()
    if not text:
        raise errors.BadRequest("请提供要朗读的文本")
    check_text_length(text)
    audio = tts.synthesize(text)
    if not audio:
        raise errors.Upstream("语音合成失败")
    return Response(content=audio, media_type="audio/mpeg")
