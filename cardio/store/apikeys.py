"""Agent API Key（机器凭证，api_keys 表）。"""
from __future__ import annotations

import json
import uuid
from typing import Any

from .conn import _connect, _now


# ── Agent API Key（机器凭证）──
def create_api_key(owner_id: str, name: str, key_hash: str, prefix: str, scopes: list[str]) -> str:
    kid = uuid.uuid4().hex[:12]
    with _connect() as c:
        c.execute(
            "INSERT INTO api_keys (id,owner_id,name,key_hash,prefix,scopes,created_at) VALUES (?,?,?,?,?,?,?)",
            (kid, owner_id, name, key_hash, prefix, json.dumps(scopes, ensure_ascii=False), _now()),
        )
    return kid


def list_api_keys(owner_id: str) -> list[dict[str, Any]]:
    with _connect() as c:
        rows = c.execute(
            "SELECT id,name,prefix,scopes,status,last_used_at,created_at,revoked_at FROM api_keys WHERE owner_id=?",
            (owner_id,),
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "name": r["name"], "prefix": r["prefix"],
            "scopes": json.loads(r["scopes"] or "[]"), "status": r["status"],
            "last_used_at": r["last_used_at"], "created_at": r["created_at"], "revoked_at": r["revoked_at"],
        })
    return out


def get_api_key_by_hash(key_hash: str) -> dict[str, Any] | None:
    with _connect() as c:
        r = c.execute(
            "SELECT id,owner_id,status,scopes FROM api_keys WHERE key_hash=?", (key_hash,)
        ).fetchone()
    if not r:
        return None
    return {
        "id": r["id"], "owner_id": r["owner_id"], "status": r["status"],
        "scopes": json.loads(r["scopes"] or "[]"),
    }


def rotate_api_key(key_id: str, owner_id: str, key_hash: str, prefix: str) -> bool:
    with _connect() as c:
        cur = c.execute(
            "UPDATE api_keys SET key_hash=?, prefix=?, status='active', revoked_at=NULL "
            "WHERE id=? AND owner_id=?",
            (key_hash, prefix, key_id, owner_id),
        )
        return cur.rowcount > 0


def revoke_api_key(key_id: str, owner_id: str) -> bool:
    with _connect() as c:
        cur = c.execute(
            "UPDATE api_keys SET status='revoked', revoked_at=? WHERE id=? AND owner_id=?",
            (_now(), key_id, owner_id),
        )
        return cur.rowcount > 0


def touch_api_key(key_id: str) -> None:
    with _connect() as c:
        c.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (_now(), key_id))
