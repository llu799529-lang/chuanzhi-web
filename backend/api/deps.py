"""路由共享的依赖：当前用户、上传图片校验、AI 接口限流。"""
from __future__ import annotations

import io
import os

from fastapi import Header, UploadFile
from PIL import Image

import auth
import config
import errors
import guardrails


def current_user(authorization: str = Header(default="")) -> str:
    """从 `Authorization: Bearer <token>` 解析当前用户；失败抛 401（`errors.Unauthorized`）。"""
    return auth.user_from_authorization(authorization)


MAX_TEXT_CHARS = 20000


def check_text_length(text: str) -> None:
    """所有收自由文本的接口共用的长度闸门：超长文本进模型就是在烧额度（也拖慢红旗扫描）。"""
    if len(text or "") > MAX_TEXT_CHARS:
        raise errors.BadRequest(f"输入内容过长，请控制在 {MAX_TEXT_CHARS} 字以内")


def rate_limit_ai(username: str, bucket: str) -> None:
    """所有会消耗模型额度的接口共用一套限流参数（每分钟次数 + 最短间隔），超限抛 429。"""
    guardrails.rate_limit(username, bucket, config.RATE_LIMIT_AI_PER_MIN, config.MIN_INTERVAL_SECONDS)


async def read_image(file: UploadFile, bad_image_msg: str = "图片解析失败，请更换清晰的图片") -> tuple[bytes, str]:
    """读上传图片并校验，返回 (bytes, mime)。所有收图片的接口共用这一个入口。

    - 必须 async：`UploadFile.read()` 是异步的；同步读会在事件循环里做磁盘 IO，多人同时上传会互相等。
    - 大小闸门在 read() **之前**：read() 一执行整份内容就进了内存，事后判断拦不住占用。
      starlette 0.50 的 `UploadFile.seek()` 只接受一个参数，探长度必须走底层文件对象。
    - 只用 `except Exception` 接 PIL 的校验失败：以前写成 `(UnidentifiedImageError, Exception)`，前者是后者的子类，等于没写。
    """
    if file.content_type and not file.content_type.startswith("image/"):
        raise errors.BadRequest("请上传图片文件（JPG/PNG）")
    try:
        file.file.seek(0, os.SEEK_END)
        size = file.file.tell()
        file.file.seek(0)
    except (OSError, ValueError, AttributeError):
        size = 0                              # 探不到长度就交给后面的空内容校验
    if size > config.MAX_UPLOAD_BYTES:
        raise errors.PayloadTooLarge(f"图片过大（{size / 1048576:.1f}MB），请压缩到 {config.MAX_UPLOAD_MB}MB 以内")
    data = await file.read()
    if not data:
        raise errors.BadRequest("图片内容为空，请重新上传")
    if len(data) > config.MAX_UPLOAD_BYTES:  # 兜底：探长度失败或客户端没给 Content-Length
        raise errors.PayloadTooLarge(f"图片过大，请压缩到 {config.MAX_UPLOAD_MB}MB 以内")
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception as e:
        raise errors.BadRequest(bad_image_msg) from e
    return data, (file.content_type or "image/jpeg")
