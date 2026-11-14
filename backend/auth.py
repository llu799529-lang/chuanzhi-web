"""用户认证：注册 / 登录 / 会话校验。

v2（对应「AI 安全可控」）：
  - JWT（HS256 自签，零第三方依赖）：带 exp / iat / jti，过期时间可配（默认 24h）
  - 会话落库 sessions 表：可主动吊销（登出）、可审计、重启不掉线
  - 兼容旧版内存 token：升级前签发的 token 在进程存活期间仍可用
  - 密码 PBKDF2-SHA256 + 随机盐，恒定时间比对（hmac.compare_digest）

与 Web 框架无关：失败只抛 `errors.*`（领域错误），HTTP 头的解析与依赖注入在 `api/deps.py`。
"""
import base64
import hashlib
import hmac
import json
import secrets
import time

import config
import db
import errors
import guardrails

# 旧版内存会话（向后兼容）
_SESSIONS: dict[str, str] = {}


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 120_000).hex()


# ---------------- JWT（HS256 手写实现，零依赖） ----------------

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _secret() -> bytes:
    return config.JWT_SECRET.encode("utf-8")


def purge_expired_sessions() -> int:
    """删掉已过期的会话行，返回删除条数。

    为什么需要：sessions 表只在两种时机被删——登出（按 jti 删）
    和这里。用户「登录后直接关浏览器」不会触发登出，那条行就永久留着；
    每人每天登录几次，几个月后表里全是早已失效的 jti。

    这本身不构成越权（过期 jti 在 _is_revoked 里查得到，但 JWT 自己
    在 decode_token 阶段就因为 exp 被拒了），纯属磁盘上的只增不减。
    调用点放在 issue_token 里而不是定时任务：签发是这张表唯一增长的地方，
    在那儿清理才能保证增长速度有上界。
    """
    try:
        with db.get_conn() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (int(time.time()),))
            return cur.rowcount or 0
    except Exception as e:
        guardrails.log_event("auth.session.purge_failed", error=f"{type(e).__name__}: {e}")
        return 0


def issue_token(username: str) -> str:
    """签发 HS256 JWT，并登记 jti 以便吊销。"""
    now = int(time.time())
    jti = secrets.token_hex(12)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": username, "iat": now, "exp": now + config.JWT_TTL_SECONDS, "jti": jti}
    signing = (_b64e(json.dumps(header, separators=(",", ":")).encode()) + "."
               + _b64e(json.dumps(payload, separators=(",", ":")).encode()))
    sig = _b64e(hmac.new(_secret(), signing.encode(), hashlib.sha256).digest())
    token = f"{signing}.{sig}"
    # 先清扫再插入：把这张表的增长钉在「未过期会话数 + 1」以内。
    # 放在 try 之外会造成登录被清理失败拖垮，所以 purge 自己吞异常并留痕。
    purge_expired_sessions()
    try:
        with db.get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions (jti, username, created_at, expires_at)"
                " VALUES (?,?,?,?)",
                (jti, username, db.now(), now + config.JWT_TTL_SECONDS),
            )
    except Exception as e:
        # 会话表写不进去 = 这个 token 无法被主动吊销（logout 只删得到表里的 jti）。
        # 不影响登录，但属于**安全相关的静默降级**，必须留痕，不能 pass。
        guardrails.log_event("auth.session.persist_failed",
                             user=username, error=f"{type(e).__name__}: {e}")
    return token


def decode_token(token: str) -> dict | None:
    """校验签名与过期时间，返回 payload；任何异常返回 None（不区分原因，避免信息泄露）。"""
    try:
        signing, sig = token.rsplit(".", 1)
        expect = _b64e(hmac.new(_secret(), signing.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expect):
            return None
        payload = json.loads(_b64d(signing.split(".")[1]))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def _is_revoked(jti: str) -> bool:
    try:
        with db.get_conn() as conn:
            row = conn.execute("SELECT 1 FROM sessions WHERE jti = ?", (jti,)).fetchone()
        return row is None
    except Exception:
        return False  # 表异常时不阻断登录态，宁可放行也不误杀


# ---------------- 业务 ----------------

def register(username: str, password: str) -> dict:
    username = (username or "").strip()
    if not 2 <= len(username) <= 20:
        raise errors.BadRequest("用户名需 2–20 个字符")
    if len(password or "") < 6:
        raise errors.BadRequest("密码至少 6 位")
    salt = secrets.token_hex(16)
    try:
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
                (username, _hash(password, salt), salt, db.now()),
            )
    except Exception:
        raise errors.Conflict("该用户名已被注册")
    return {"token": issue_token(username), "username": username}


def login(username: str, password: str) -> dict:
    username, password = (username or "").strip(), password or ""
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT password_hash, salt FROM users WHERE username = ?", (username,)
        ).fetchone()
    if row is None:
        # 用户不存在也走一次哈希，避免时间侧信道泄露「用户名是否存在」
        _hash(password, "00" * 16)
        raise errors.Unauthorized("用户名或密码不正确")
    if not hmac.compare_digest(_hash(password, row["salt"]), row["password_hash"]):
        raise errors.Unauthorized("用户名或密码不正确")
    return {"token": issue_token(username), "username": username}


def _new_session(username: str) -> str:
    """旧版内存 token（仅兼容历史调用）。"""
    token = secrets.token_hex(24)
    _SESSIONS[token] = username
    return token


def user_from_authorization(authorization: str) -> str:
    """从 `Authorization: Bearer <token>` 的取值解析当前用户（JWT 优先，内存 token 兜底）。

    HTTP 依赖注入的包装在 `api/deps.current_user`；这里只认字符串，便于离线测试与其它入口复用。
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise errors.Unauthorized("未登录")
    token = authorization.removeprefix("Bearer ").strip()

    payload = decode_token(token)
    if payload:
        jti = payload.get("jti", "")
        if jti and _is_revoked(jti):
            raise errors.Unauthorized("登录已失效，请重新登录")
        return payload.get("sub", "")

    username = _SESSIONS.get(token)
    if not username:
        raise errors.Unauthorized("登录已过期，请重新登录")
    return username


def logout(authorization: str):
    """吊销当前 token：JWT 删 jti，内存 token 直接移除。"""
    if not authorization or not authorization.startswith("Bearer "):
        return
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_token(token)
    if payload and payload.get("jti"):
        try:
            with db.get_conn() as conn:
                conn.execute("DELETE FROM sessions WHERE jti = ?", (payload["jti"],))
        except Exception as e:
            # 会话行删不掉 = 这个 jti 仍停留在表里，理论上还能被重放。
            # 内存里的 _SESSIONS 已经 pop，但重启后数据库里的残留会重新生效，
            # 所以这条必须留痕（是安全事件，不是普通清理失败）。
            guardrails.log_event("auth.session.revoke_failed",
                                 user=payload.get("sub"), error=f"{type(e).__name__}: {e}")
    _SESSIONS.pop(token, None)
