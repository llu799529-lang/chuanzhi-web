"""pytest 全局配置：把 backend/ 加进 sys.path，并隔离测试数据库。

关键点：测试绝不能碰真实的 backend/medtriage.db——
在 conftest 里把 config.DATA_DIR 指到临时目录，db.get_conn() 自然落到 tmp。
（只改 DATA_DIR，不改 BASE_DIR：BASE_DIR 是代码目录，改它会把知识库等路径一起带偏。）
"""
import os
import sys
from pathlib import Path

import pytest

# Do not import runtime credentials, even when tests run on a configured machine.
os.environ["MEDTRIAGE_SKIP_DOTENV"] = "1"
os.environ["JWT_SECRET"] = "offline-test-secret-do-not-use-in-production"
for key in ("ARK_API_KEY", "AMAP_API_KEY", "AMAP_JS_KEY", "AMAP_JS_SEC"):
    os.environ[key] = ""
os.environ["RAG_VECTOR"] = "0"

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(autouse=True)
def offline_transport(monkeypatch):
    import urllib.request

    def blocked(*args, **kwargs):
        raise AssertionError("External network is disabled in unit tests")

    monkeypatch.setattr(urllib.request, "urlopen", blocked)


@pytest.fixture(scope="session", autouse=True)
def isolated_db(tmp_path_factory):
    """把数据库重定向到临时目录，跑完即弃。"""
    import config

    tmp = tmp_path_factory.mktemp("db")
    config.DATA_DIR = tmp

    import db
    db.init_db()
    yield tmp


@pytest.fixture()
def client():
    """FastAPI TestClient（不带 LLM，纯本地逻辑可测）。"""
    from fastapi.testclient import TestClient

    import main
    return TestClient(main.app)


@pytest.fixture()
def token(client):
    """注册一个随机用户并返回 JWT。"""
    import uuid

    name = "t" + uuid.uuid4().hex[:8]
    r = client.post("/api/auth/register", json={"username": name, "password": "test123456"})
    assert r.status_code == 200, r.text
    return r.json()["token"]
