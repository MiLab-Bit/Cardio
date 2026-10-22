"""SQLite 连接与 schema 演化 —— store 包的共享基建。

_connect() 在建连时统一建全表 + _migrate() 补列，所有域共用。
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

from .. import config

DEFAULT_OWNER = "default"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    # 多 worker 并发写：WAL 允许读写并发，busy_timeout 避免 "database is locked"
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE,
            name TEXT,
            password_hash TEXT NOT NULL,
            email_verified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS email_verifications (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            purpose TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            name TEXT NOT NULL,
            key_hash TEXT NOT NULL,
            prefix TEXT NOT NULL,
            scopes TEXT NOT NULL DEFAULT '["*"]',
            status TEXT NOT NULL DEFAULT 'active',
            last_used_at TEXT,
            created_at TEXT,
            revoked_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS model_providers (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            slot TEXT NOT NULL DEFAULT 'text',
            name TEXT NOT NULL,
            provider TEXT NOT NULL,
            api_key_enc TEXT NOT NULL,
            base_url TEXT,
            model TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT,
            updated_at TEXT,
            last_used_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS contacts (
            id TEXT PRIMARY KEY,
            name TEXT,
            title TEXT,
            company TEXT,
            phone TEXT,
            email TEXT,
            tags TEXT,
            notes TEXT,
            created_at TEXT,
            owner TEXT NOT NULL DEFAULT 'default'
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS analyses (
            id TEXT PRIMARY KEY,
            input_text TEXT,
            result_json TEXT,
            created_at TEXT,
            owner TEXT NOT NULL DEFAULT 'default',
            contact_id TEXT
        )"""
    )
    _migrate(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contacts_owner ON contacts(owner)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_analyses_owner ON analyses(owner)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_owner ON api_keys(owner_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_model_providers_owner ON model_providers(owner_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_verifications_user ON email_verifications(user_id)")
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """对已有库补齐 owner / contact_id 列（新库 CREATE 时不带，运行时补）。"""
    cols_contacts = {r[1] for r in conn.execute("PRAGMA table_info(contacts)")}
    if "owner" not in cols_contacts:
        conn.execute("ALTER TABLE contacts ADD COLUMN owner TEXT NOT NULL DEFAULT 'default'")
    cols_analyses = {r[1] for r in conn.execute("PRAGMA table_info(analyses)")}
    if "owner" not in cols_analyses:
        conn.execute("ALTER TABLE analyses ADD COLUMN owner TEXT NOT NULL DEFAULT 'default'")
    if "contact_id" not in cols_analyses:
        conn.execute("ALTER TABLE analyses ADD COLUMN contact_id TEXT")
    cols_users = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    if "name" not in cols_users:
        conn.execute("ALTER TABLE users ADD COLUMN name TEXT")
    if "email_verified" not in cols_users:
        conn.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
    # 双模型槽位：已存在的 model_providers 表补齐 slot 列（默认 'text'）
    cols_mp = {r[1] for r in conn.execute("PRAGMA table_info(model_providers)")}
    if "slot" not in cols_mp:
        conn.execute("ALTER TABLE model_providers ADD COLUMN slot TEXT NOT NULL DEFAULT 'text'")


def check_db() -> bool:
    """探测数据库是否可用（健康检查时调用）。"""
    try:
        with _connect() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False

