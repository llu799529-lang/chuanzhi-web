"""月度用量与成本估算（/api/usage 的数据来源）。

以前这段 SQL + 计价循环直接写在 HTTP 路由里：路由层既查库、又按分时价格算钱、又拼提示文案。
抽到服务层后，路由只做鉴权与返回；计价口径（`pricing.py`）与读取口径（这里）各自可测。

是估算值，不是账单：没有单价的模型（含有免费额度的 V4-Flash 正式版）按经济版价格给上限，并标 `priced=false`。
"""
from __future__ import annotations

import datetime

import db
import pricing

PRICING_NOTE = ("估算值（不是账单）：经济版闲时 0.8/3.2、高峰 1.6/6.4 元每百万 tokens（输入/输出）；"
                "命中上下文缓存的输入按 0.016/0.032 计，缓存存储费未计入。")


def monthly(username: str, month: str | None = None) -> dict:
    """某用户某月（默认本月，`YYYY-MM`）的调用次数、token 与估算成本，按模型拆分。"""
    month = month or datetime.datetime.now().strftime("%Y-%m")
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT model, prompt_tokens, completion_tokens, total_tokens, created_at, cached_tokens"
            " FROM llm_usage WHERE created_at LIKE ? AND username = ?",
            (month + "%", username),
        ).fetchall()
    p = c = t = peak_calls = cached = 0
    saved = 0.0
    cost = 0.0
    unpriced: set[str] = set()
    by_model: dict[str, dict] = {}
    for r in rows:
        model = r["model"] or "unknown"
        pt, ct, tt = int(r["prompt_tokens"] or 0), int(r["completion_tokens"] or 0), int(r["total_tokens"] or 0)
        hit = min(int(r["cached_tokens"] or 0), pt)
        ts = pricing.parse_ts(r["created_at"])
        one = pricing.estimate_cost(r["model"] or "", pt, ct, ts, cached_tokens=hit)
        saved += pricing.estimate_cost(r["model"] or "", pt, ct, ts) - one
        cached += hit
        if not pricing.price_for(r["model"] or "", ts)[3]:
            unpriced.add(model)
        p, c, t, cost = p + pt, c + ct, t + tt, cost + one
        peak_calls += 1 if pricing.is_peak(ts) else 0
        bm = by_model.setdefault(model, {"calls": 0, "total_tokens": 0, "cached_tokens": 0, "cost_cny": 0.0})
        bm["priced"] = model not in unpriced
        bm["calls"] += 1
        bm["total_tokens"] += tt
        bm["cached_tokens"] += hit
        bm["cost_cny"] = round(bm["cost_cny"] + one, 6)
    note = PRICING_NOTE
    if unpriced:
        note += ("下列模型未录入单价，按经济版价格给出上限估算，有免费额度时实际可能为 0："
                 + "、".join(sorted(unpriced)) + "。")
    note += "以火山方舟控制台账单为准。"
    return {"month": month, "prompt_tokens": p, "completion_tokens": c, "total_tokens": t,
            "calls": len(rows), "cost_cny": round(cost, 4), "peak_calls": peak_calls, "by_model": by_model,
            # 上下文缓存：命中的输入 token、命中率（占输入的比例）、按缓存价比按原价少花的钱
            "cached_tokens": cached, "cache_hit_rate": round(cached / p, 4) if p else None,
            "cache_saved_cny": round(saved, 4),
            "unpriced_models": sorted(unpriced), "pricing_note": note}
