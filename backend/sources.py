"""参考文献登记表（kb_sources.json）的运行时读取。

登记表由人工联网核实（见 docs/KB_SOURCES.md），每条来源带可点开的证据链接；运行时只读，不联网。
这里只暴露 high 级来源——medium 级是「待二次核实」，不应出现在给用户看的界面上。

注意路径：用模块自身所在目录，**不用 `config.BASE_DIR`**——测试会把 BASE_DIR 改到临时目录放数据库，
用它会读不到登记表。
"""
from __future__ import annotations

import json
from pathlib import Path

_REG_PATH = Path(__file__).resolve().parent / "kb_sources.json"
_CACHE: dict | None = None


def registry() -> dict:
    """登记表（带缓存）。文件缺失或损坏时返回空表——引用功能降级为「没有参考文献」，不影响分诊。"""
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = json.loads(_REG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _CACHE = {"sources": {}, "map": {}}
    return _CACHE


def reload() -> None:
    global _CACHE
    _CACHE = None


def describe(source_ids) -> list[dict]:
    """来源 id 列表 → 给前端展示的结构。未登记或非 high 的 id 被丢弃。"""
    sources = registry().get("sources", {})
    out = []
    for sid in source_ids or []:
        s = sources.get(sid)
        if not s or s.get("confidence") != "high":
            continue
        ev = s.get("evidence") or []
        out.append({
            "id": sid,
            "title": s.get("title", ""),
            "issuer": "" if str(s.get("issuer", "")).startswith("（") else s.get("issuer", ""),
            "citation": "" if str(s.get("citation", "")).startswith("（") else s.get("citation", ""),
            "year": s.get("year"),
            "verify_url": ev[0] if ev else "",
        })
    return out


def verify_links(source_ids) -> list[str]:
    """每个来源的核实链接（与 source_ids 一一对应，缺失时为空串）。"""
    return [d["verify_url"] for d in describe(source_ids)]
