"""请求体模型。只描述「接口收什么」，校验失败由 FastAPI 返回 422（错误体经 app 统一成 `{detail, code}`）。"""
from __future__ import annotations

from pydantic import BaseModel


class Credentials(BaseModel):
    username: str
    password: str


class SymptomIn(BaseModel):
    text: str


class MultimodalIn(BaseModel):
    lab_detail: dict | None = None
