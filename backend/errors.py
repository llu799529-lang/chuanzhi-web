"""领域错误：业务层只说「出了什么错」，由 HTTP 入口统一翻译成状态码与 `{detail, code}`。

为什么不直接抛 `fastapi.HTTPException`
------------------------------------
`auth` / `guardrails` 以前直接 `raise HTTPException(...)`，等于领域逻辑依赖 Web 框架：
  · 纯逻辑测试必须装 FastAPI 才能断言「限流返回 429」；
  · MCP Server、评测脚本复用这些函数时，会收到一个它们根本不认识的异常类型。
现在领域层只抛这里的 `ServiceError`，HTTP 层（`api/app.py`）注册一个处理器，把它翻译成与 HTTPException
完全同形的 JSON（前端无感知）。路由（`api/routes/`）也统一用它，全项目只有一套错误词汇。

基础层模块：不依赖任何内部模块。
"""
from __future__ import annotations

# 状态码 → 机器可读的错误码。前端按 code 分支（比如 429 提示「N 秒后再试」、401 跳登录）。
CODES: dict[int, str] = {
    400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE", 422: "UNPROCESSABLE", 429: "RATE_LIMITED",
    500: "INTERNAL", 502: "UPSTREAM", 503: "UNAVAILABLE",
}


def code_for(status: int) -> str:
    return CODES.get(int(status), "ERROR")


class ServiceError(Exception):
    """所有可预期的业务错误的基类。`status` 由子类决定，也可以在构造时覆盖。"""

    status: int = 400

    def __init__(self, detail: str, *, status: int | None = None, headers: dict[str, str] | None = None):
        super().__init__(detail)
        self.detail = detail
        if status is not None:
            self.status = int(status)
        self.headers: dict[str, str] = dict(headers or {})

    @property
    def code(self) -> str:
        return code_for(self.status)

    @property
    def status_code(self) -> int:
        """与 HTTPException 同名的属性：日志、测试按 status_code 读时不用区分两种异常。"""
        return self.status

    def body(self) -> dict:
        return {"detail": self.detail, "code": self.code}


class BadRequest(ServiceError):
    status = 400


class Unauthorized(ServiceError):
    status = 401


class Conflict(ServiceError):
    status = 409


class PayloadTooLarge(ServiceError):
    status = 413


class RateLimited(ServiceError):
    """限流。必须带 Retry-After：前端据此倒计时，而不是让用户盲目重试。"""

    status = 429

    def __init__(self, detail: str, retry_after: float):
        self.retry_after = max(1, int(-(-float(retry_after) // 1)))      # 向上取整，至少 1 秒
        super().__init__(detail, headers={"Retry-After": str(self.retry_after)})


class Upstream(ServiceError):
    """上游（大模型 / 第三方接口）调用失败。"""

    status = 502


class Unavailable(ServiceError):
    """能力未启用（未配置 Key、依赖未安装）。"""

    status = 503
