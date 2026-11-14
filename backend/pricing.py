"""模型计费估算（单位：元 / 百万 tokens）。

DeepSeek-V4.1-Flash 经济版按「闲时 / 高峰」分时计费，以**请求完成时的北京时间**为准：
  高峰：周一至周五 09:00–12:00、14:00–18:00；其余为闲时。
  闲时 输入 0.8 / 输出 3.2；高峰 输入 1.6 / 输出 6.4（价格来源：方舟控制台模型详情页，
  价格以控制台实时显示为准，本表只用于用量页的估算）。

这里只做**估算**。缓存命中的输入 token 按缓存价计（经济版闲时 0.016 / 高峰 0.032，是输入价的 1/50），
来源是上游 `usage.prompt_tokens_details.cached_tokens`；缓存存储费（0.017 元/百万 tokens/小时）没有计入。
`created_at` 来自 `db.now()`，按服务器本地时间（部署在国内机器时即北京时间）解析。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

BJ = timezone(timedelta(hours=8))

# 工作日高峰窗口（含起点、不含终点）
PEAK_WINDOWS = ((9, 12), (14, 18))

ECONOMY = "deepseek-v4-1-flash-economy"
# 没有录入单价的模型（含有免费额度的 V4-Flash 正式版）不编造价格：price_for 用经济版价格给**上限**估算，
# 并返回 known=False，用量接口据此标 priced=false。

# 模型前缀 -> {"idle": (输入, 输出), "peak": (输入, 输出)}；按顺序匹配，经济版必须排在标准版前面（前缀更长）。
PRICES = {
    ECONOMY: {"idle": (0.8, 3.2), "peak": (1.6, 6.4)},
    # 标准版（同一权重、更快），价格来自同一页文档的版本对比表：闲时 1/4，高峰 2/8。
    "deepseek-v4-1-flash": {"idle": (1.0, 4.0), "peak": (2.0, 8.0)},
    # 历史口径：升级前用量表里残留的 GLM 记录，保持原估算（输入 0.11 / 输出 0.28）。
    "glm-": {"idle": (0.11, 0.28), "peak": (0.11, 0.28)},
}
# 缓存命中的输入价。没有列出的模型按输入价计（即不打折，宁可估高）。
CACHE_PRICES = {
    ECONOMY: {"idle": 0.016, "peak": 0.032},
    "deepseek-v4-1-flash": {"idle": 0.02, "peak": 0.04},
}


def _as_bj(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(BJ)
    if dt.tzinfo is None:          # 无时区信息：按北京时间理解
        return dt.replace(tzinfo=BJ)
    return dt.astimezone(BJ)


def is_peak(dt: datetime | None = None) -> bool:
    d = _as_bj(dt)
    if d.weekday() >= 5:
        return False
    return any(a <= d.hour < b for a, b in PEAK_WINDOWS)


def price_for(model: str, dt: datetime | None = None) -> tuple[float, float, str, bool]:
    """返回 (输入价, 输出价, 'peak'|'idle', 是否有真实单价)。

    没有单价的模型（含免费额度的 V4-Flash 正式版）按经济版价格估算——那是**上限**，
    且第四个返回值为 False，调用方必须把它标成「未录入单价」，不能当账单展示。
    """
    period = "peak" if is_peak(dt) else "idle"
    for prefix, table in PRICES.items():
        if (model or "").startswith(prefix):
            i, o = table[period]
            return i, o, period, True
    i, o = PRICES[ECONOMY][period]
    return i, o, period, False


def cache_price_for(model: str, dt: datetime | None = None) -> float:
    """缓存命中输入价。未录入单价的模型与 price_for 同口径：按经济版给上限。"""
    i, _, period, known = price_for(model, dt)
    for prefix, table in CACHE_PRICES.items():
        if (model or "").startswith(prefix):
            return table[period]
    return CACHE_PRICES[ECONOMY][period] if not known else i


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int,
                  dt: datetime | None = None, cached_tokens: int = 0) -> float:
    """输入里命中缓存的部分按缓存价，其余按输入价；输出按输出价。缓存数不会超过输入数。"""
    i, o, _, _ = price_for(model, dt)
    prompt = max(prompt_tokens, 0)
    cached = min(max(cached_tokens or 0, 0), prompt)
    return ((prompt - cached) * i + cached * cache_price_for(model, dt) + max(completion_tokens, 0) * o) / 1_000_000


def parse_ts(value) -> datetime | None:
    """解析 db.now() 写入的时间串（'YYYY-MM-DD HH:MM:SS' 或 ISO）。"""
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace(" ", "T"))
    except (TypeError, ValueError):
        return None
