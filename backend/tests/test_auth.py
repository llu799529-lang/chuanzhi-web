"""认证：JWT 签发/校验/过期/吊销，以及密码哈希。"""
import time

import auth
import config


def test_register_and_login(client):
    import uuid

    name = "u" + uuid.uuid4().hex[:8]
    r = client.post("/api/auth/register", json={"username": name, "password": "abc123456"})
    assert r.status_code == 200
    assert r.json()["username"] == name
    assert len(r.json()["token"]) > 40

    r2 = client.post("/api/auth/login", json={"username": name, "password": "abc123456"})
    assert r2.status_code == 200


def test_wrong_password_401(client):
    import uuid

    name = "w" + uuid.uuid4().hex[:8]
    client.post("/api/auth/register", json={"username": name, "password": "right123"})
    r = client.post("/api/auth/login", json={"username": name, "password": "wrong123"})
    assert r.status_code == 401


def test_duplicate_register_409(client):
    import uuid

    name = "d" + uuid.uuid4().hex[:8]
    client.post("/api/auth/register", json={"username": name, "password": "abc123456"})
    r = client.post("/api/auth/register", json={"username": name, "password": "abc123456"})
    assert r.status_code == 409


def test_short_password_rejected(client):
    r = client.post("/api/auth/register", json={"username": "shortpw", "password": "123"})
    assert r.status_code == 400


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_me_with_token(client, token):
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["username"]


def test_jwt_roundtrip():
    """签发的 JWT 必须能被自己解回来，且带 exp / jti。"""
    t = auth.issue_token("alice")
    payload = auth.decode_token(t)
    assert payload["sub"] == "alice"
    assert payload["exp"] > time.time()
    assert payload["jti"]


def test_jwt_tampered_signature_rejected():
    """改一个字符即失效——签名校验必须真的生效。"""
    t = auth.issue_token("bob")
    head, sig = t.rsplit(".", 1)
    forged = head + "." + ("A" if sig[0] != "A" else "B") + sig[1:]
    assert auth.decode_token(forged) is None


def test_jwt_expired_rejected(monkeypatch):
    """把 TTL 调成 -1 立刻过期，验证 exp 校验生效。"""
    monkeypatch.setattr(config, "JWT_TTL_SECONDS", -1)
    t = auth.issue_token("carol")
    assert auth.decode_token(t) is None


def test_logout_revokes_token(client, token):
    """登出后同一个 token 立刻失效（jti 已从 sessions 表删除）。"""
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=h).status_code == 200
    client.post("/api/auth/logout", headers=h)
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_password_hash_salted():
    """同一密码两次注册的哈希必须不同（盐不同）。"""
    salt1, salt2 = "00" * 16, "11" * 16
    assert auth._hash("same", salt1) != auth._hash("same", salt2)


def test_expired_sessions_are_purged_on_issue():
    """sessions 表不能只增不减。

    用户登录后直接关浏览器不会触发登出，那条 jti 会永久留表。
    签名时顺手清扫过期行，把表的增长钉在「未过期会话数 + 1」以内。
    """
    import db

    with db.get_conn() as conn:
        before = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]

    # 造 50 条一年前就过期的会话
    stale_exp = int(time.time()) - 365 * 24 * 3600
    with db.get_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO sessions (jti, username, created_at, expires_at)"
            " VALUES (?,?,?,?)",
            [(f"stale{i}", "ghost", db.now(), stale_exp) for i in range(50)],
        )
        mid = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
    assert mid == before + 50

    auth.issue_token("someone")

    with db.get_conn() as conn:
        left = conn.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE expires_at < ?", (int(time.time()),)
        ).fetchone()["n"]
    assert left == 0, "过期会话必须被清掉，否则表只增不减"


def test_purge_keeps_live_sessions():
    """清扫不能删掉还没过期的会话——那等于把在线用户全部踢下线。"""
    import db

    live = auth.issue_token("live-user")
    assert live
    payload = auth.decode_token(live)
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE jti = ?", (payload["jti"],)
        ).fetchone()
    assert row is not None, "刚签发的会话不能被清扫掉"
