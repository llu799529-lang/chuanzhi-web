"""前端静态托管：Vue 构建产物（history 路由回退 index.html）+ 旧版前端只读旁路。

目录约定：
  frontend/          新版 Vue 3 + TS（构建产物在 frontend/dist*）
  frontend-legacy/   旧版原生 HTML/CSS/JS（只读归档，/_legacy/ 旁路可访问）

必须在所有 API 路由注册**之后**挂载根路径，否则 "/" 挂载会吞掉 API。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

import config


def is_spa_route(path: str) -> bool:
    """挂载点内的相对路径找不到文件时，是否应回退到 index.html。

    回退：无扩展名的路径（/login、/app 这类前端路由）。
    不回退：带扩展名的资源（缺图就该 404，不能返回首页冒充图片），以及 **api/ 下的一切**——
    以前没排除 api/，拼错的接口地址（或用错方法，如 GET 一个只收 POST 的接口）会拿到 200 + 首页 HTML，
    前端 `resp.json()` 失败后当成空结果，错误被悄悄吞掉。
    Windows 上 Starlette 给的是反斜杠路径，先统一成正斜杠再判断。
    """
    p = (path or "").strip().replace("\\", "/").lstrip("/")
    if p == "api" or p.startswith("api/"):
        return False
    return not p or p.endswith("/") or "." not in p.rsplit("/", 1)[-1]


class SPAStaticFiles(StaticFiles):
    """文件不存在且属于前端路由时，统一回退 index.html。"""

    async def get_response(self, path: str, scope):
        # starlette 0.50 在无匹配时 raise HTTPException(404)；个别旧版本返回 Response(404)，两种都接住。
        try:
            resp = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            resp = None
        if resp is not None and resp.status_code != 404:
            return resp
        if is_spa_route(path):
            try:
                return await super().get_response("index.html", scope)
            except StarletteHTTPException:
                pass
        if resp is None:
            raise StarletteHTTPException(status_code=404)
        return resp


def pick_vue_dist(app_dir: Path) -> Path:
    """选最新的 Vue 构建产物：构建脚本在 dist 无法清空时会退到 dist2/dist3，按 index.html 修改时间取最新。"""
    candidates = [app_dir / "dist", *app_dir.glob("dist*")]
    valid = [p for p in candidates if (p / "index.html").exists()]
    if not valid:
        return app_dir / "dist"
    return max(valid, key=lambda p: (p / "index.html").stat().st_mtime)


def mount_frontend(app: FastAPI, root: Path | None = None) -> Path | None:
    """挂载前端，返回实际托管的目录（都不存在时返回 None，此时只有 API 可用）。"""
    root = root or config.BASE_DIR.parent
    vue_dist = pick_vue_dist(root / "frontend")
    legacy = root / "frontend-legacy"
    # 新版未构建时回落旧版，保证「双击即用」不因漏跑 build 而白屏
    frontend_dir = vue_dist if vue_dist.exists() else legacy

    # 旧版是真实多文件站点，不能用 SPAStaticFiles（会把 404 图片替换成首页）；必须注册在根挂载之前。
    if vue_dist.exists() and legacy.exists():
        app.mount("/_legacy", StaticFiles(directory=legacy, html=True), name="legacy-frontend")

    icon = legacy / "favicon.ico"
    if icon.exists():
        @app.get("/favicon.ico", include_in_schema=False)
        async def _favicon():
            return FileResponse(icon, media_type="image/x-icon", headers={"Cache-Control": "public, max-age=86400"})

    if frontend_dir.exists():
        app.mount("/", SPAStaticFiles(directory=frontend_dir, html=True), name="frontend")
        return frontend_dir
    return None
