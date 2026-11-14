"""DeepSeek 经济版分时计费估算（闲时 0.8/3.2，高峰 1.6/6.4 元每百万 tokens）。"""
from datetime import datetime, timedelta, timezone

import pytest

import pricing

BJ = timezone(timedelta(hours=8))


@pytest.mark.parametrize("when,peak", [
    ("2026-10-26 09:00", True),    # 周一 09:00 起
    ("2026-10-26 11:59", True),
    ("2026-10-26 12:00", False),   # 午休闲时
    ("2026-10-26 13:59", False),
    ("2026-10-26 14:00", True),
    ("2026-10-26 17:59", True),
    ("2026-10-26 18:00", False),   # 18:00 起闲时（不含终点）
    ("2026-10-26 08:59", False),
    ("2026-10-24 10:00", False),   # 周六全天闲时
    ("2026-10-25 15:00", False),   # 周日
])
def test_peak_windows_are_beijing_weekday_hours(when, peak):
    assert pricing.is_peak(datetime.fromisoformat(when.replace(" ", "T"))) is peak


def test_timezone_aware_values_are_converted_to_beijing():
    utc = datetime(2026, 10, 26, 2, 0, tzinfo=timezone.utc)      # = 北京 10:00 周一
    assert pricing.is_peak(utc) is True


def test_economy_prices_idle_and_peak():
    idle = datetime(2026, 10, 24, 10, 0)
    peak = datetime(2026, 10, 26, 10, 0)
    m = "deepseek-v4-1-flash-economy-261017"
    assert pricing.estimate_cost(m, 1_000_000, 1_000_000, idle) == pytest.approx(0.8 + 3.2)
    assert pricing.estimate_cost(m, 1_000_000, 1_000_000, peak) == pytest.approx(1.6 + 6.4)
    assert pricing.estimate_cost(m, 1500, 600, idle) == pytest.approx(0.00312, rel=1e-3)


def test_unknown_model_falls_back_to_economy_price_and_is_flagged():
    i, o, period, known = pricing.price_for("some-other-model", datetime(2026, 10, 24, 10, 0))
    assert (i, o, period, known) == (0.8, 3.2, "idle", False)


def test_free_quota_ga_model_is_flagged_unpriced_not_invented():
    i, o, _, known = pricing.price_for("deepseek-v4-flash-ga-260731", datetime(2026, 10, 24, 10, 0))
    assert known is False                   # 单价没给到，不编造
    assert (i, o) == (0.8, 3.2)             # 仅作上限估算


def test_legacy_glm_rows_keep_their_old_estimate():
    i, o, _, known = pricing.price_for("glm-5-3-flash-260828", datetime(2026, 10, 26, 10, 0))
    assert known is True and (i, o) == (0.11, 0.28)


def test_negative_tokens_never_produce_negative_cost():
    assert pricing.estimate_cost("deepseek-v4-1-flash-economy-261017", -5, -5) == 0


def test_parse_ts_accepts_db_now_format_and_rejects_garbage():
    assert pricing.parse_ts("2026-10-24 14:30:05") == datetime(2026, 10, 24, 14, 30, 5)
    assert pricing.parse_ts("not a date") is None
    assert pricing.parse_ts(None) is None


# ---------------------------------------------------------------- 上下文缓存（2026-10-29 按方舟文档补）
def test_cached_input_is_billed_at_the_cache_price():
    idle, peak = datetime(2026, 10, 24, 10, 0), datetime(2026, 10, 26, 10, 0)
    m = "deepseek-v4-1-flash-economy-261017"
    # 100 万输入里 80 万命中缓存：20 万 × 0.8 + 80 万 × 0.016 = 0.1728 元（闲时）
    assert pricing.estimate_cost(m, 1_000_000, 0, idle, cached_tokens=800_000) == pytest.approx(0.2 * 0.8 + 0.8 * 0.016)
    assert pricing.estimate_cost(m, 1_000_000, 0, peak, cached_tokens=800_000) == pytest.approx(0.2 * 1.6 + 0.8 * 0.032)


def test_cached_tokens_never_exceed_prompt_tokens_or_go_negative():
    m = "deepseek-v4-1-flash-economy-261017"
    t = datetime(2026, 10, 24, 10, 0)
    assert pricing.estimate_cost(m, 100, 0, t, cached_tokens=10_000) == pytest.approx(100 * 0.016 / 1e6)
    assert pricing.estimate_cost(m, 100, 0, t, cached_tokens=-5) == pricing.estimate_cost(m, 100, 0, t)


def test_standard_v41_flash_is_priced_and_not_confused_with_economy():
    t = datetime(2026, 10, 24, 10, 0)
    assert pricing.price_for("deepseek-v4-1-flash-261017", t)[:2] == (1.0, 4.0)
    assert pricing.price_for("deepseek-v4-1-flash-economy-261017", t)[:2] == (0.8, 3.2)
    assert pricing.cache_price_for("deepseek-v4-1-flash-261017", t) == 0.02


def test_unpriced_model_cache_estimate_is_an_upper_bound_like_its_input_price():
    t = datetime(2026, 10, 24, 10, 0)
    assert pricing.cache_price_for("deepseek-v4-flash-ga-260731", t) == 0.016
