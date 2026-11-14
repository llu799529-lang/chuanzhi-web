"""系统：健康检查（能力矩阵）与本月用量。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends

import config
import guardrails
import llm
import rag
import tts
import usage as usage_service
from api.deps import current_user
from fundus import analyzer

LIVE_REPORT = config.BASE_DIR / "evals" / "live_smoke_report.json"

router = APIRouter(prefix="/api", tags=["system"])


def mcp_available() -> bool:
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


def live_check() -> dict | None:
    """最近一次真实接口冒烟测试（evals/live_smoke.py）的摘要。没跑过返回 None——页面据此如实显示「未实测」。"""
    try:
        rep = json.loads(LIVE_REPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(rep, dict):
        return None
    results = rep.get("results") if isinstance(rep.get("results"), dict) else {}
    return {"at": rep.get("at"), "model": rep.get("model"), "passed": rep.get("passed"), "total": rep.get("total"),
            "requests": rep.get("requests"), "unsupported_params": rep.get("unsupported_params") or [],
            "probes": {k: bool(v.get("ok")) for k, v in results.items() if isinstance(v, dict)},
            "cache_hit": bool((results.get("cache") or {}).get("cache_hit"))}


@router.get("/health")
def health():
    """一眼看清各能力当前是真跑还是降级（答辩演示第一屏）。不需要登录。"""
    on = llm.llm_available()
    return {
        "status": "ok",
        "fundus_mode": "demo" if analyzer.is_demo else "model",
        "llm_enabled": on,
        # 文本主模型与视觉模型分开报：两者可以不同（ARK_VISION_MODEL），只报一个就答不了「看图用的是哪个」。
        "llm_model": config.LLM_MODEL if on else None,
        "llm_vision_model": config.LLM_VISION_MODEL if on else None,
        "capabilities": {
            "fundus_model": not analyzer.is_demo,
            "llm": on,
            "tts": tts.available(),
            "rag_vector": rag.vector_ready(),
            "amap_map": bool(config.AMAP_JS_KEY),
            "amap_poi": bool(config.AMAP_API_KEY),
            "mcp_server": mcp_available(),
            # 无 Key / 额度耗尽时：症状分诊与 Agent 仍可用（知识库 + 规则），结果会明确标注「离线模式」
            "offline_fallback": True,
            "safety_gate": True,
        },
        "guardrails": {"pii_mask": True, "red_word_scan": len(guardrails.RED_WORDS),
                       "rate_limit_ai_per_min": config.RATE_LIMIT_AI_PER_MIN},
        "auth": {"scheme": "JWT-HS256", "ttl_seconds": config.JWT_TTL_SECONDS},
        # 参数协商结果（本进程内上游明确不认的可选参数）与最近一次真实接口实测
        "llm_runtime": llm.runtime_info() if on else None,
        "live_check": live_check(),
    }


@router.get("/usage")
def usage(username: str = Depends(current_user)):
    """本月大模型 token 用量与成本估算（估算值，不是账单）。"""
    return usage_service.monthly(username)
