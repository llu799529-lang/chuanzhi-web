"""领域错误（errors.py）与有界 TTL 缓存（cache.py）。纯逻辑，无框架。"""
import pytest

import cache
import errors


# ---------------------------------------------------------------- errors
@pytest.mark.parametrize("cls,status,code", [
    (errors.BadRequest, 400, "BAD_REQUEST"), (errors.Unauthorized, 401, "UNAUTHORIZED"),
    (errors.Conflict, 409, "CONFLICT"), (errors.PayloadTooLarge, 413, "PAYLOAD_TOO_LARGE"),
    (errors.Upstream, 502, "UPSTREAM"), (errors.Unavailable, 503, "UNAVAILABLE"),
])
def test_each_error_class_carries_its_status_and_code(cls, status, code):
    e = cls("说明")
    assert e.status == e.status_code == status and e.code == code
    assert e.body() == {"detail": "说明", "code": code}
    assert isinstance(e, errors.ServiceError)


@pytest.mark.parametrize("wait,header", [(0.2, "1"), (1.0, "1"), (1.01, "2"), (37.4, "38")])
def test_rate_limited_always_sends_a_retry_after_of_at_least_one_second(wait, header):
    e = errors.RateLimited("太快了", retry_after=wait)
    assert e.status == 429 and e.code == "RATE_LIMITED" and e.headers == {"Retry-After": header}


def test_unknown_status_gets_a_generic_code_and_status_can_be_overridden():
    assert errors.code_for(418) == "ERROR"
    assert errors.ServiceError("x", status=404).code == "NOT_FOUND"


def test_domain_modules_raise_domain_errors_not_framework_errors():
    """auth / guardrails 的失败必须是 ServiceError：纯逻辑环境（无 FastAPI）也能断言状态码。"""
    import auth
    import guardrails
    with pytest.raises(errors.Unauthorized):
        auth.user_from_authorization("")
    with pytest.raises(errors.Unauthorized):
        auth.user_from_authorization("Bearer not-a-token")
    with pytest.raises(errors.BadRequest):
        auth.register("x", "123456")                      # 用户名太短
    guardrails._WINDOW.clear()
    guardrails._LAST_CALL.clear()
    guardrails.rate_limit("err_u", "err:test", per_min=5, min_interval=10)
    with pytest.raises(errors.RateLimited) as ei:
        guardrails.rate_limit("err_u", "err:test", per_min=5, min_interval=10)
    assert int(ei.value.headers["Retry-After"]) >= 1


# ---------------------------------------------------------------- cache
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_cache_returns_value_until_ttl_then_forgets_it():
    clk = Clock()
    c = cache.TTLCache(ttl_seconds=10, max_items=5, clock=clk)
    c.put("a", {"v": 1})
    clk.t += 9.9
    assert c.get("a") == {"v": 1}
    clk.t += 0.1
    assert c.get("a") is None and len(c) == 0           # 过期项在读时被删掉，而不是永远留着


def test_cache_never_exceeds_its_capacity_and_evicts_the_oldest():
    clk = Clock()
    c = cache.TTLCache(ttl_seconds=100, max_items=3, clock=clk)
    for k in "abcd":
        c.put(k, k)
        clk.t += 1
    assert len(c) == 3 and c.get("a") is None and c.get("d") == "d"


def test_cache_put_sweeps_expired_items_first():
    clk = Clock()
    c = cache.TTLCache(ttl_seconds=5, max_items=3, clock=clk)
    c.put("old1", 1)
    c.put("old2", 2)
    clk.t += 6
    c.put("new", 3)
    assert len(c) == 1 and c.get("new") == 3


def test_cache_rewriting_a_key_refreshes_it():
    clk = Clock()
    c = cache.TTLCache(ttl_seconds=5, max_items=2, clock=clk)
    c.put("a", 1)
    clk.t += 4
    c.put("a", 2)
    clk.t += 4
    assert c.get("a") == 2


def test_cache_rejects_nonsense_configuration():
    with pytest.raises(ValueError):
        cache.TTLCache(ttl_seconds=0, max_items=1)
    with pytest.raises(ValueError):
        cache.TTLCache(ttl_seconds=1, max_items=0)
