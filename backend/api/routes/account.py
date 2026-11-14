"""账户：注册 / 登录 / 当前用户 / 登出，以及当前用户的筛查记录。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header

import auth
import config
import records as records_repo
from api.deps import current_user
from api.schemas import Credentials

router = APIRouter(prefix="/api", tags=["account"])


@router.post("/auth/register")
def register(cred: Credentials):
    return auth.register(cred.username, cred.password)


@router.post("/auth/login")
def login(cred: Credentials):
    return auth.login(cred.username, cred.password)


@router.get("/auth/me")
def me(username: str = Depends(current_user)):
    return {"username": username}


@router.post("/auth/logout")
def logout(authorization: str = Header(default="")):
    """登出不要求 token 有效：过期 token 也应能「登出」而不是报 401。"""
    auth.logout(authorization)
    return {"ok": True}


# 注意函数名不叫 records：曾经路由函数名 `records` 遮蔽了 `import records` 模块，
# 把**函数对象**当记录列表传给了多模态分析（见 tests/test_api.py 的回归用例）。
@router.get("/records")
def list_records(username: str = Depends(current_user)):
    return {
        "records": records_repo.recent(username, 50, include_id=True),
        "usage": {"month_used": records_repo.count_this_month(username), "month_quota": config.MONTHLY_QUOTA},
    }
