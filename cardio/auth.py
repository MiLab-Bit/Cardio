"""Cardio 鉴权 — 轻量用户体系（PBKDF2 + HS256 JWT，无第三方依赖）。

与 BizAtlas 的登录范式保持一致：注册/登录 → 返回 Bearer JWT → 后续接口
携带 Authorization: Bearer <token>。token 内的 sub 即用户 id，作为数据 owner 隔离。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(pw: str) -> str:
    """返回 'pbkdf2$<iters>$<salt_b64>$<dk_b64>' 存储串。"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, 100_000)
    return "pbkdf2$100000$" + _b64u(salt) + "$" + _b64u(dk)


def verify_password(stored: str, pw: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        dk2 = _b64u(hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), _b64d(salt), int(it)))
        return hmac.compare_digest(dk2, dk)
    except Exception:
        return False


def issue_token(user_id: str, email: str, secret: str, ttl: int = 60 * 60 * 24 * 7) -> str:
    """签发 HS256 JWT（默认 7 天）。"""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {"sub": user_id, "email": email, "iat": now, "exp": now + ttl}
    h = _b64u(json.dumps(header, separators=(",", ":")).encode())
    p = _b64u(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode("utf-8"), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64u(sig)}"


def decode_token(token: str, secret: str) -> dict | None:
    """校验签名与有效期，成功返回 payload，失败返回 None。"""
    try:
        h, p, s = token.split(".")
    except ValueError:
        return None
    expected = hmac.new(secret.encode("utf-8"), f"{h}.{p}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64u(expected), s):
        return None
    try:
        payload = json.loads(_b64d(p))
    except Exception:
        return None
    if payload.get("exp", 0) < int(time.time()):
        return None
    return payload


# ── 邮箱验证 / 密码找回一次性 token ──
def make_verify_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """一次性 token 仅存哈希（与其明文等价，但泄露库也不怕）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── Agent API Key（机器凭证）──
def generate_api_key(prefix: str = "cd_") -> tuple[str, str, str]:
    """返回 (明文, 前缀, 哈希)。明文仅创建瞬间返回一次。"""
    raw = secrets.token_urlsafe(32)
    plain = f"{prefix}{raw}"
    return plain, prefix, hashlib.sha256(plain.encode("utf-8")).hexdigest()


def hash_api_key(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()
