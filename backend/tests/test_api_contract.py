"""接口契约：用静态分析锁定「有哪些接口、谁要登录、谁要限流、前端调的地址后端是否存在」。

为什么静态分析而不是只靠接口测试
------------------------------
接口测试只覆盖写了用例的路径；这里对**所有**路由做全称断言，新增一个接口忘了加鉴权或限流，
不需要谁想起来写用例，CI 就会红。它不需要 FastAPI，纯逻辑环境也能跑。
"""
import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
ROUTES = BACKEND / "api" / "routes"
FRONTEND_SRC = BACKEND.parent / "frontend" / "src"

# 接口清单就是契约：增删接口必须同时改这里，评审时一眼能看到「对外暴露面变了」。
EXPECTED = {
    ("GET", "/api/health"), ("GET", "/api/usage"),
    ("POST", "/api/auth/register"), ("POST", "/api/auth/login"), ("GET", "/api/auth/me"),
    ("POST", "/api/auth/logout"), ("GET", "/api/records"),
    ("POST", "/api/fundus/analyze"), ("POST", "/api/ai/image"), ("POST", "/api/ai/symptom"),
    ("POST", "/api/ai/multimodal"),
    ("POST", "/api/agent/chat"), ("POST", "/api/agent/reset"), ("POST", "/api/agent/chat/stream"), ("POST", "/api/tts"),
    ("GET", "/api/hospitals"),
}
# 不需要登录的接口（白名单）。其余一律必须依赖 current_user。
PUBLIC = {"/api/health", "/api/auth/register", "/api/auth/login", "/api/auth/logout", "/api/hospitals"}
# 会消耗模型额度或大量算力的接口：必须限流。
METERED = {"/api/fundus/analyze", "/api/ai/image", "/api/ai/symptom", "/api/ai/multimodal",
           "/api/agent/chat", "/api/agent/chat/stream"}


def _routes() -> list[dict]:
    out = []
    for f in sorted(ROUTES.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        prefix = ""
        for n in tree.body:
            if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "router" for t in n.targets)
                    and isinstance(n.value, ast.Call)):
                prefix = next((k.value.value for k in n.value.keywords if k.arg == "prefix"), "")
        for n in tree.body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in n.decorator_list:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and isinstance(d.func.value, ast.Name)
                        and d.func.value.id == "router" and d.args and isinstance(d.args[0], ast.Constant)):
                    calls = {c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", "")
                             for c in ast.walk(n) if isinstance(c, ast.Call)}
                    deps = {a.id for a in ast.walk(n.args) if isinstance(a, ast.Name)}
                    out.append({"method": d.func.attr.upper(), "path": prefix + d.args[0].value, "fn": n.name,
                                "file": f.name, "calls": calls, "deps": deps})
    return out


def test_route_inventory_matches_the_contract():
    got = {(r["method"], r["path"]) for r in _routes()}
    assert got == EXPECTED, f"新增：{sorted(got - EXPECTED)}；缺失：{sorted(EXPECTED - got)}"


def test_no_route_is_registered_twice():
    keys = [(r["method"], r["path"]) for r in _routes()]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("route", [r for r in _routes() if r["path"] not in PUBLIC], ids=lambda r: r["path"])
def test_every_non_public_route_requires_login(route):
    assert "current_user" in route["deps"], f"{route['path']} 没有依赖 current_user（未登录也能调）"


@pytest.mark.parametrize("path", sorted(METERED))
def test_every_metered_route_is_rate_limited(path):
    route = next(r for r in _routes() if r["path"] == path)
    assert "rate_limit_ai" in route["calls"], f"{path} 会消耗模型额度 / 大量算力，却没有限流"


def test_public_routes_really_do_not_require_login():
    """白名单不能只增不减：标成公开、实际却要求登录的，说明白名单写错了。"""
    for r in _routes():
        if r["path"] in PUBLIC:
            assert "current_user" not in r["deps"], f"{r['path']} 登记为公开接口，但依赖了 current_user"


def _frontend_api_paths() -> set[str]:
    paths = set()
    for f in FRONTEND_SRC.rglob("*"):
        if f.suffix in (".ts", ".vue") and f.is_file():
            for m in re.finditer(r"""["'`](/api/[A-Za-z0-9_/\-]+)""", f.read_text(encoding="utf-8")):
                paths.add(m.group(1))
    return paths


@pytest.mark.skipif(not FRONTEND_SRC.exists(), reason="没有前端源码目录")
def test_every_api_path_the_frontend_calls_exists_in_the_backend():
    backend = {p for _, p in EXPECTED}
    called = _frontend_api_paths()
    # 前端用模板字符串拼 /api/auth/${mode}（login | register），按前缀匹配
    missing = {p for p in called if p not in backend and not any(b.startswith(p) for b in backend)}
    assert called, "没扫到任何前端接口调用，检查扫描规则"
    assert not missing, f"前端调用了后端不存在的接口：{sorted(missing)}"


# ---------------------------------------------------------------- 前端托管不吞 API
@pytest.mark.parametrize("path,fallback", [
    ("", True), ("login", True), ("app", True), ("app/", True),
    ("assets/index-abc.js", False), ("favicon.png", False),
    ("api", False), ("api/", False), ("api/ai/symptom", False), ("api/unknown", False), ("api\\ai\\x", False),
    ("apidocs", True),
])
def test_spa_fallback_never_swallows_api_paths(path, fallback):
    """拼错的接口地址以前会拿到 200 + 首页 HTML，前端 `resp.json()` 失败后当成空结果——错误被悄悄吞掉。"""
    pytest.importorskip("fastapi")
    from api import static
    assert static.is_spa_route(path) is fallback
