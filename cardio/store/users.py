"""用户账号与验证 token（users / email_verifications）。"""
from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from ..auth import verify_password
from .conn import _connect, _now


# ── 用户账号 ──
def create_user(email: str, password_hash: str, name: str = "") -> str | None:
    uid = uuid.uuid4().hex[:12]
    with _connect() as c:
        try:
            c.execute(
                "INSERT INTO users (id,email,name,password_hash,created_at) VALUES (?,?,?,?,?)",
                (uid, email.lower().strip(), name, password_hash, _now()),
            )
        except sqlite3.IntegrityError:
            return None  # 邮箱已注册
    return uid


def verify_user(email: str, password: str) -> str | None:
    with _connect() as c:
        r = c.execute("SELECT id,password_hash FROM users WHERE email=?", (email.lower().strip(),)).fetchone()
    if not r:
        return None
    if not verify_password(r["password_hash"], password):
        return None
    return r["id"]


def get_user(uid: str) -> dict[str, Any] | None:
    with _connect() as c:
        r = c.execute("SELECT id,email,name,email_verified FROM users WHERE id=?", (uid,)).fetchone()
    return {"id": r["id"], "email": r["email"], "name": r["name"], "email_verified": bool(r["email_verified"])} if r else None


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with _connect() as c:
        r = c.execute(
            "SELECT id,email,name,email_verified,password_hash FROM users WHERE email=?",
            (email.lower().strip(),),
        ).fetchone()
    if not r:
        return None
    return {
        "id": r["id"], "email": r["email"], "name": r["name"],
        "email_verified": bool(r["email_verified"]), "password_hash": r["password_hash"],
    }


def set_email_verified(uid: str) -> None:
    with _connect() as c:
        c.execute("UPDATE users SET email_verified=1 WHERE id=?", (uid,))


# ── 邮箱验证 / 密码找回 token ──
def save_verify_token(token_hash: str, uid: str, purpose: str, expires_at: str) -> None:
    with _connect() as c:
        c.execute(
            "INSERT INTO email_verifications (token_hash,user_id,purpose,expires_at) VALUES (?,?,?,?) "
            "ON CONFLICT(token_hash) DO UPDATE SET user_id=excluded.user_id, purpose=excluded.purpose, expires_at=excluded.expires_at",
            (token_hash, uid, purpose, expires_at),
        )


def get_verify_token(token_hash: str) -> dict[str, Any] | None:
    with _connect() as c:
        r = c.execute(
            "SELECT user_id,purpose,expires_at FROM email_verifications WHERE token_hash=?",
            (token_hash,),
        ).fetchone()
    return {"user_id": r["user_id"], "purpose": r["purpose"], "expires_at": r["expires_at"]} if r else None


def delete_verify_token(token_hash: str) -> None:
    with _connect() as c:
        c.execute("DELETE FROM email_verifications WHERE token_hash=?", (token_hash,))
