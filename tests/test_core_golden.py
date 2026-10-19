"""Cardio 核心逻辑黄金测试 —— 仅覆盖「不调 LLM / 不联网」的确定性环节。

覆盖：
  - auth: PBKDF2 密码哈希/校验、HS256 JWT 签发/校验（有效/篡改签名/过期）、
          Agent API Key 哈希、一次性校验 token 哈希
  - crypto: 用户自带密钥的 at-rest 加解密（固定 Fernet key 下的确定性往返）
  - email_utils: SMTP 配置加载（环境变量分支 / 未配置回退 None，不发真实邮件）

运行（仓库根）：
    venv/bin/python -m pytest tests/test_core_golden.py -q
"""
from __future__ import annotations

import hashlib
import importlib
import os
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.getenv("OPENCLAW_SHARED_DIR", "/opt/shared"))

_JWT_SECRET = "cardio-golden-test-secret"


# ----------------------------------------------------------------------
# auth: 密码哈希
# ----------------------------------------------------------------------
def test_hash_password_format_and_verify():
    from cardio import auth

    stored = auth.hash_password("hunter2")
    assert stored.startswith("pbkdf2$100000$")
    assert auth.verify_password(stored, "hunter2") is True


def test_verify_password_wrong_returns_false():
    from cardio import auth

    stored = auth.hash_password("hunter2")
    assert auth.verify_password(stored, "wrong") is False
    assert auth.verify_password("malformed", "anything") is False


# ----------------------------------------------------------------------
# auth: JWT
# ----------------------------------------------------------------------
def test_issue_and_decode_token():
    from cardio import auth

    tok = auth.issue_token("u1", "a@b.com", _JWT_SECRET)
    payload = auth.decode_token(tok, _JWT_SECRET)
    assert payload is not None
    assert payload["sub"] == "u1"
    assert payload["email"] == "a@b.com"


def test_decode_token_tampered_signature_returns_none():
    from cardio import auth

    tok = auth.issue_token("u1", "a@b.com", _JWT_SECRET)
    h, p, s = tok.split(".")
    bad_sig = ("A" if s[-1] != "A" else "B") + s[1:]
    assert auth.decode_token(f"{h}.{p}.{bad_sig}", _JWT_SECRET) is None


def test_decode_token_expired_returns_none():
    from cardio import auth

    tok = auth.issue_token("u1", "a@b.com", _JWT_SECRET, ttl=-10)
    assert auth.decode_token(tok, _JWT_SECRET) is None


def test_decode_token_wrong_secret_returns_none():
    from cardio import auth

    tok = auth.issue_token("u1", "a@b.com", _JWT_SECRET)
    assert auth.decode_token(tok, "another-secret") is None


# ----------------------------------------------------------------------
# auth: Agent API Key / 校验 token
# ----------------------------------------------------------------------
def test_api_key_hash_roundtrip():
    from cardio import auth

    plain, prefix, h = auth.generate_api_key("cd_")
    assert plain.startswith("cd_")
    assert prefix == "cd_"
    assert auth.hash_api_key(plain) == h


def test_verify_token_hash_deterministic():
    from cardio import auth

    t = auth.make_verify_token()
    assert auth.hash_token(t) == hashlib.sha256(t.encode("utf-8")).hexdigest()
    assert len(auth.hash_token(t)) == 64


# ----------------------------------------------------------------------
# crypto: at-rest 加解密（固定 key 下的确定性往返）
# ----------------------------------------------------------------------
def test_crypto_roundtrip():
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch_key = pytest.MonkeyPatch()
    monkeypatch_key.setenv("CARDIO_ENC_KEY", key)
    import cardio.crypto
    importlib.reload(cardio.crypto)
    try:
        ct = cardio.crypto.encrypt("sk-abc-123")
        assert cardio.crypto.decrypt(ct) == "sk-abc-123"
    finally:
        monkeypatch_key.undo()


def test_crypto_empty_string():
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    mp = pytest.MonkeyPatch()
    mp.setenv("CARDIO_ENC_KEY", key)
    import cardio.crypto
    importlib.reload(cardio.crypto)
    try:
        assert cardio.crypto.encrypt("") == ""
        assert cardio.crypto.decrypt("") == ""
    finally:
        mp.undo()


def test_crypto_distinct_ciphertext_same_plaintext():
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    mp = pytest.MonkeyPatch()
    mp.setenv("CARDIO_ENC_KEY", key)
    import cardio.crypto
    importlib.reload(cardio.crypto)
    try:
        a = cardio.crypto.encrypt("same")
        b = cardio.crypto.encrypt("same")
        assert a != b                       # Fernet 随机 IV
        assert cardio.crypto.decrypt(a) == cardio.crypto.decrypt(b) == "same"
    finally:
        mp.undo()


# ----------------------------------------------------------------------
# email_utils: SMTP 配置加载（不发真实邮件）
# ----------------------------------------------------------------------
def test_load_smtp_config_from_env(monkeypatch, tmp_path):
    import cardio.email_utils as eu

    monkeypatch.setattr(eu, "SHARED_SMTP_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USERNAME", "bot@example.com")
    monkeypatch.setenv("SMTP_FROM", "Cardio <bot@example.com>")
    cfg = eu.load_smtp_config()
    assert cfg is not None
    assert cfg["host"] == "smtp.example.com"
    assert cfg["username"] == "bot@example.com"
    assert cfg["encryption"] == "ssl"
    assert cfg["port"] == 465


def test_load_smtp_config_none_when_unconfigured(monkeypatch, tmp_path):
    import cardio.email_utils as eu

    monkeypatch.setattr(eu, "SHARED_SMTP_PATH", str(tmp_path / "missing.json"))
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    assert eu.load_smtp_config() is None
