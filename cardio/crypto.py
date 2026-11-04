"""用户自带大模型密钥的静态加密存储（at-rest encryption）。

密钥来源（优先级）：
  1. 环境变量 CARDIO_ENC_KEY（Fernet key，32 url-safe base64 字节）
  2. 否则在 config.DATA_DIR 下生成并持久化 .enc_key，保证进程重启后仍可解密
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

from . import config

_KEY_PATH = Path(config.DATA_DIR) / ".enc_key"


def _load_key() -> bytes:
    env = os.environ.get("CARDIO_ENC_KEY")
    if env:
        return env.encode("utf-8") if isinstance(env, str) else env
    if os.getenv("CARDIO_REQUIRE_ENC_KEY", "").lower() in ("1", "true", "yes"):
        raise RuntimeError(
            "CARDIO_ENC_KEY is required for this deployment; "
            "refusing to silently generate a different decryption key"
        )
    if _KEY_PATH.exists():
        return _KEY_PATH.read_bytes().strip()

    # A missing key must never be silently replaced if persisted BYOK tokens
    # would become undecryptable. Read an existing DB without creating one.
    db_path = Path(config.DB_PATH)
    if db_path.is_file():
        try:
            with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
                table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='model_providers'"
                ).fetchone()
                if table and conn.execute(
                    "SELECT 1 FROM model_providers WHERE api_key_enc IS NOT NULL "
                    "AND api_key_enc <> '' LIMIT 1"
                ).fetchone():
                    raise RuntimeError(
                        "Cardio encryption key missing with stored BYOK credentials; "
                        "restore original key from protected backup before migration"
                    )
        except sqlite3.Error as exc:
            raise RuntimeError(
                "Cannot verify existing Cardio credentials before key generation"
            ) from exc

    key = Fernet.generate_key()
    _KEY_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Stage the complete key under a private temporary name. Linking it into
    # place is atomic: a concurrent API/worker cannot read a zero-byte file.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".enc_key.", dir=_KEY_PATH.parent, delete=False
        ) as handle:
            temp_path = Path(handle.name)
            os.chmod(temp_path, 0o600)
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_path, _KEY_PATH)
            return key
        except FileExistsError:
            existing = _KEY_PATH.read_bytes().strip()
            Fernet(existing)  # Refuse truncated or invalid keys.
            return existing
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


_fernet = Fernet(_load_key())


def encrypt(plain: str) -> str:
    """加密明文（如用户自带的大模型 API Key），返回可存库的密文。"""
    if not plain:
        return ""
    return _fernet.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    """解密密文，还原用户自带的大模型 API Key。"""
    if not token:
        return ""
    return _fernet.decrypt(token.encode("utf-8")).decode("utf-8")
