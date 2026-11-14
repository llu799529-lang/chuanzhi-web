"""文本转语音（TTS）：edge-tts 可选依赖，未安装时返回 None 由调用方返回 503。

用途：报告页「朗读」按钮——"给老人读报告"叙事，社会价值维度加分。
"""
import io


def available() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False


def synthesize(text: str) -> bytes | None:
    """文本 → mp3 字节。失败返回 None。"""
    if not text:
        return None
    try:
        import asyncio

        import edge_tts

        async def _run() -> bytes:
            buf = io.BytesIO()
            comm = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            return buf.getvalue()

        return asyncio.run(_run())
    except Exception:
        return None
