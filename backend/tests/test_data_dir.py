"""数据目录与代码目录必须分开：config.DATA_DIR（数据库）≠ config.BASE_DIR（代码、知识库、权重）。

回归背景：数据库原来也用 BASE_DIR，测试为隔离数据库去改 BASE_DIR，于是「代码目录」被改成临时目录——
知识库路径是否被带偏取决于模块导入顺序，哪天换了导入顺序，RAG 就会无声地读不到知识库（症状分诊全部退化成
「没有检索依据」，而不是报错）。
"""
import importlib.util
from pathlib import Path

import pytest

import config
import db
import rag

BACKEND = Path(__file__).resolve().parent.parent


def _fresh_config():
    spec = importlib.util.spec_from_file_location("config_fresh_data_dir", config.__file__)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_tests_isolate_the_database_without_touching_the_code_directory():
    assert config.BASE_DIR == BACKEND
    assert config.DATA_DIR != BACKEND                       # conftest 指到了临时目录
    assert (config.BASE_DIR / "knowledge_base.json").exists()


def test_database_follows_data_dir_and_knowledge_base_follows_base_dir():
    assert db.get_conn().execute("PRAGMA database_list").fetchall()[0][2].startswith(str(config.DATA_DIR))
    assert rag._KB_PATH.parent == BACKEND


def test_retrieval_still_works_when_data_dir_is_somewhere_else():
    assert rag.retrieve("咳嗽三天，有点黄痰", 3), "数据目录换了，知识库不应受影响"


def test_default_data_dir_is_the_code_dir_and_env_can_move_it(monkeypatch, tmp_path):
    monkeypatch.delenv("MEDTRIAGE_DATA_DIR", raising=False)
    assert _fresh_config().DATA_DIR == _fresh_config().BASE_DIR
    monkeypatch.setenv("MEDTRIAGE_DATA_DIR", str(tmp_path))
    moved = _fresh_config()
    assert moved.DATA_DIR == tmp_path and moved.BASE_DIR == BACKEND
    monkeypatch.setenv("MEDTRIAGE_DATA_DIR", "")
    assert _fresh_config().DATA_DIR == BACKEND                # 空值等于没设


@pytest.mark.parametrize("name", ["medtriage.db"])
def test_nothing_under_the_code_directory_is_written_by_the_test_database(name):
    """测试库在临时目录里；真实 backend/medtriage.db 的行数不应因测试而变（由 conftest 保证）。"""
    assert (config.DATA_DIR / name).exists()
    assert config.DATA_DIR / name != BACKEND / name
