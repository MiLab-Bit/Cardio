"""数字商册联系人（contacts 表）。"""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from .conn import DEFAULT_OWNER, _connect, _now


def _normalize_tags(tags: Any) -> list[str]:
    if isinstance(tags, str):
        return [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()]
    if isinstance(tags, list):
        return [str(t).strip() for t in tags if str(t).strip()]
    return []


def save_contact(owner: str, data: dict[str, Any]) -> dict[str, Any]:
    cid = data.get("id") or uuid.uuid4().hex[:12]
    row = (
        cid,
        data.get("name", ""),
        data.get("title", ""),
        data.get("company", ""),
        data.get("phone", ""),
        data.get("email", ""),
        json.dumps(_normalize_tags(data.get("tags")), ensure_ascii=False),
        data.get("notes", ""),
        _now(),
        owner,
    )
    with _connect() as c:
        c.execute(
            """INSERT INTO contacts (id,name,title,company,phone,email,tags,notes,created_at,owner)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, title=excluded.title, company=excluded.company,
                 phone=excluded.phone, email=excluded.email, tags=excluded.tags,
                 notes=excluded.notes, owner=excluded.owner""",
            row,
        )
    return get_contact(cid)


def update_contact(owner: str, cid: str, data: dict[str, Any]) -> dict[str, Any] | None:
    existing = get_contact(cid)
    if not existing or existing.get("owner") != owner:
        return None
    merged = {**existing, **{k: v for k, v in data.items() if v is not None}}
    return save_contact(owner, merged)


def delete_contact(owner: str, cid: str) -> bool:
    with _connect() as c:
        cur = c.execute("DELETE FROM contacts WHERE id=? AND owner=?", (cid, owner))
        return cur.rowcount > 0


def get_contact(cid: str) -> dict[str, Any] | None:
    with _connect() as c:
        r = c.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    return _row_to_contact(r) if r else None


def list_contacts(
    owner: str = DEFAULT_OWNER, limit: int = 100, q: str | None = None
) -> list[dict[str, Any]]:
    with _connect() as c:
        if q:
            like = f"%{q}%"
            rows = c.execute(
                "SELECT * FROM contacts WHERE owner=? AND "
                "(name LIKE ? OR company LIKE ? OR title LIKE ? OR email LIKE ?) "
                "ORDER BY created_at DESC LIMIT ?",
                (owner, like, like, like, like, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM contacts WHERE owner=? ORDER BY created_at DESC LIMIT ?",
                (owner, limit),
            ).fetchall()
    return [_row_to_contact(r) for r in rows]


def _row_to_contact(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": r["id"],
        "name": r["name"],
        "title": r["title"],
        "company": r["company"],
        "phone": r["phone"],
        "email": r["email"],
        "tags": json.loads(r["tags"] or "[]"),
        "notes": r["notes"],
        "created_at": r["created_at"],
        "owner": r["owner"] if "owner" in r.keys() else DEFAULT_OWNER,
    }
