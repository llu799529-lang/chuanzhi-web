"""应用工厂：中间件、统一错误体、挂载路由与前端。

统一错误体 `{detail, code}`
--------------------------
前端只认这一种形状（`code` 决定分支：UNAUTHORIZED 跳登录、RATE_LIMITED 读 Retry-After 倒计时……）。
四类异常都在这里翻译，路由与业务代码不需要关心：

| 来源 | 例子 | 状态码 |
|---|---|---|
| `errors.ServiceError`（业务层） | 限流、未登录、上游失败 | 由异常类决定 |
| Starlette `HTTPException` | 路由不存在、方法不允许 | 404 / 405 |
| 请求体校验失败 | JSON 字段类型不对 | 422（detail 是一句人话，明细在 errors） |
| 其它未捕获异常 | bug | 500（不回显异常文本，只给 request_id 便于追溯） |
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import config
import db
import errors
import guardrails
from api import static
from api.routes import ROUTERS

OPENAPI_TAGS = [
    {"name": "system", "description": "健康检查（能力矩阵）与用量"},
    {"name": "account", "description": "注册 / 登录 / 筛查记录"},
    {"name": "screening", "description": "眼底 / 图片 / 症状 / 多模态综合分析"},
    {"name": "assistant", "description": "Agent 助手（SSE）与报告朗读"},
    {"name": "navigation", "description": "附近医院"},
]


_LOC_SOURCES = {"body", "query", "path", "header", "cookie"}


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(errors.ServiceError)
    async def service_error(request, exc: errors.ServiceError):
        return JSONResponse(status_code=exc.status, content=exc.body(), headers=exc.headers or None)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.detail, "code": errors.code_for(exc.status_code)},
                            headers=getattr(exc, "headers", None) or None)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc: RequestValidationError):
        # 默认 422 的 detail 是对象数组，前端直接显示会变成「[object Object]」。
        items = [{"loc": [str(x) for x in e.get("loc", ())], "msg": str(e.get("msg", ""))} for e in exc.errors()]
        where = ".".join(x for x in items[0]["loc"] if x not in _LOC_SOURCES) if items else ""
        return JSONResponse(status_code=422, content={
            "detail": f"请求参数不合法{f'：{where}' if where else ''}", "code": "UNPROCESSABLE", "errors": items})

    @app.exception_handler(Exception)
    async def unhandled(request, exc: Exception):
        rid = request.headers.get("X-Request-Id", "-")
        guardrails.log_event("unhandled", rid=rid, path=request.url.path, err=type(exc).__name__, msg=str(exc)[:300])
        return JSONResponse(status_code=500, headers={"X-Request-Id": rid}, content={
            "detail": "服务内部错误，请稍后重试", "code": "INTERNAL", "request_id": rid, "disclaimer": config.DISCLAIMER})


def _install_middleware(app: FastAPI) -> None:
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def audit_log(request, call_next):
        """request_id + 结构化日志 + audit 表（PII 脱敏 + 调用追溯）。"""
        return await guardrails.audit_middleware(request, call_next)

    @app.middleware("http")
    async def no_cache_static(request, call_next):
        """静态资源每次 revalidate（304），改动后浏览器立即生效。"""
        response = await call_next(request)
        if not request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(*, serve_frontend: bool = True) -> FastAPI:
    app = FastAPI(title="MedTriage 多模态智能分诊与就医导航系统", version="2.0", openapi_tags=OPENAPI_TAGS)
    _install_middleware(app)
    _install_error_handlers(app)
    db.init_db()
    for router in ROUTERS:
        app.include_router(router)
    if serve_frontend:
        static.mount_frontend(app)        # 必须最后：根路径挂载会吞掉其后注册的路由
    return app
