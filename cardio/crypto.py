"""用户自带大模型密钥的静态加密存储（at-rest encryption）。

密钥来源（优先级）：
  1. 环境变量 CARDIO_ENC_KEY（Fernet key，32 url-safe base64 字节）
  2. 否则在 config.DATA_DIR 下生成并持久化 .enc_key，保证进程重启后仍可解密
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet

from . import config

_KEY_PATH = Path(config.DATA_DIR) / ".enc_key"


def _load_key() -> bytes:
    env = os.environ.get("CARDIO_ENC_KEY")
    if env:
        return env.encode("utf-8") if isinstance(env, str) else env
    if _KEY_PATH.exists():
        return _KEY_PATH.read_bytes().strip()
    key = Fernet.generate_key()
    _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _KEY_PATH.write_bytes(key)
    return key


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
