"""历史分析记录（analyses 表）。"""
from __future__ import annotations

import json
import uuid
from typing import Any

from .conn import DEFAULT_OWNER, _connect, _now


def save_analysis(
    owner: str,
    input_text: str,
    result: dict[str, Any],
    contact_id: str | None = None,
) -> dict[str, Any]:
    aid = uuid.uuid4().hex[:12]
    with _connect() as c:
        c.execute(
            "INSERT INTO analyses (id,input_text,result_json,created_at,owner,contact_id) "
            "VALUES (?,?,?,?,?,?)",
            (aid, input_text, json.dumps(result, ensure_ascii=False), _now(), owner, contact_id),
        )
    return {"id": aid, "created_at": _now(), "contact_id": contact_id}


def list_analyses(
    owner: str = DEFAULT_OWNER, limit: int = 50, contact_id: str | None = None
) -> list[dict[str, Any]]:
    with _connect() as c:
        if contact_id:
            rows = c.execute(
                "SELECT * FROM analyses WHERE owner=? AND contact_id=? ORDER BY created_at DESC LIMIT ?",
                (owner, contact_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM analyses WHERE owner=? ORDER BY created_at DESC LIMIT ?",
                (owner, limit),
            ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "input_text": r["input_text"],
            "result": json.loads(r["result_json"] or "{}"),
            "created_at": r["created_at"],
            "contact_id": r["contact_id"] if "contact_id" in r else None,
        })
    return out
