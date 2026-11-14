"""提交打包脚本（tools/pack_submission.py）的安全规则：密钥文件绝不进包、该带的一定带上、密钥扫描真的会拦。"""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location("pack_submission", ROOT / "tools" / "pack_submission.py")
pack = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pack)


@pytest.mark.parametrize("rel", [
    ".env", ".env.local", "backend/.env", "backend/.jwt_secret", "backend/medtriage.db", "backend/medtriage.db-wal",
    "frontend/node_modules/vue/index.js", "backend/__pycache__/x.pyc", "backend/api/__pycache__/app.cpython-311.pyc",
    "_backup_20261019/main.py", "backend/knowledge_base.json.bak", "backend/knowledge_base.json.bak-20261020",
    "_shots/03-app.png", "tools/verify/smoke.mjs", "docs/答辩话术.md", ".pytest_cache/v/x", "backend/server.log",
    "PLAN-95.md",
    "SUBMISSION_MANIFEST.md", "docs/DEV_SANDBOX.md",
])
def test_secrets_runtime_data_and_junk_are_excluded(rel):
    assert pack.excluded(rel, include_notes=False), f"{rel} 不应进入提交包"


@pytest.mark.parametrize("rel", [
    ".env.example", "README.md", "start_server.bat", "pack_submission.bat", "run_live_smoke.bat",
    "backend/main.py", "backend/api/app.py", "backend/knowledge_base.json", "backend/kb_sources.json",
    "backend/weights/best_v2.pth", "backend/requirements.txt", "_shots/fundus_real.jpg",
    "frontend/dist/index.html", "frontend/src/main.ts", "frontend/package-lock.json", "docs/EVAL.md",
    ".github/workflows/ci.yml", "tools/pack_submission.py",
])
def test_everything_a_judge_needs_is_kept(rel):
    assert pack.excluded(rel, include_notes=False) is None, f"{rel} 必须进入提交包"


def test_notes_are_opt_in():
    assert pack.excluded("docs/答辩话术.md", include_notes=True) is None


def test_secret_scan_catches_a_key_that_leaked_into_a_source_file(tmp_path):
    leaked = tmp_path / "config_copy.py"
    leaked.write_text('KEY = "abcdef0123456789abcdef"\n', encoding="utf-8")
    clean = tmp_path / "ok.py"
    clean.write_text("x = 1\n", encoding="utf-8")
    pack_root = pack.ROOT
    try:
        pack.ROOT = tmp_path
        hits = pack.scan([leaked, clean], [("AMAP_JS_KEY", "abcdef0123456789abcdef")])
    finally:
        pack.ROOT = pack_root
    assert hits == ["config_copy.py 含 AMAP_JS_KEY 的值"]


def test_demo_records_use_only_known_urgency_levels():
    assert {r[4] for r in pack.DEMO_RECORDS} <= {"green", "yellow", "orange", "red"}
    assert pack.JUDGE_USER == "wbtest" and len(pack.JUDGE_PASS) >= 6


def test_review_config_includes_service_settings_but_not_accounts_or_local_paths(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ARK_API_KEY=review-key-123456789\nAMAP_JS_KEY=map-key-123456789\nJWT_SECRET=must-not-share\nMEDTRIAGE_DATA_DIR=C:/private\n", encoding="utf-8")
    monkeypatch.setattr(pack, "ROOT", tmp_path)
    assert hasattr(pack, "review_config"), "换机评审需要显式选择的私有配置交付方式"
    content = pack.review_config()
    assert "ARK_API_KEY=review-key-123456789" in content
    assert "AMAP_JS_KEY=map-key-123456789" in content
    assert "must-not-share" not in content and "C:/private" not in content
    assert "LLM_ALLOW_PAID_FALLBACK=0" in content


def test_review_config_refuses_an_unconfigured_api_key(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ARK_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(pack, "ROOT", tmp_path)
    assert hasattr(pack, "review_config")
    with pytest.raises(SystemExit, match="ARK_API_KEY"):
        pack.review_config()
