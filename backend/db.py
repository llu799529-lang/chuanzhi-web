"""SQLite 存储：用户表 + 筛查记录表。"""
import datetime
import sqlite3

import config


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DATA_DIR / "medtriage.db", timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL：并发读不阻塞写，多个请求同时落库时不再 "database is locked"
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        pass
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt          TEXT NOT NULL,
                created_at    TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS records (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT NOT NULL,
                input_type TEXT NOT NULL,
                level      INTEGER,
                department TEXT,
                urgency    TEXT,
                summary    TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS llm_usage (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                model            TEXT,
                prompt_tokens    INTEGER,
                completion_tokens INTEGER,
                total_tokens     INTEGER,
                created_at       TEXT NOT NULL,
                username         TEXT,
                cached_tokens    INTEGER DEFAULT 0,
                reasoning_tokens INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS audit (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                path       TEXT NOT NULL,
                method     TEXT,
                status     INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                jti        TEXT PRIMARY KEY,
                username   TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_llm_usage_month ON llm_usage(created_at);
            CREATE INDEX IF NOT EXISTS idx_audit_path ON audit(path);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(username);
            """
        )
        _add_missing_columns(conn, "llm_usage", MIGRATIONS["llm_usage"])


# 只增不改的迁移：老库缺的列补上（默认 0），已有数据原样保留。SQLite 不支持 ADD COLUMN IF NOT EXISTS，先查再加。
MIGRATIONS = {
    "llm_usage": {"cached_tokens": "INTEGER DEFAULT 0", "reasoning_tokens": "INTEGER DEFAULT 0"},
}


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> list[str]:
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    added = [name for name in columns if name not in have]
    for name in added:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {columns[name]}")
    return added


def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")
