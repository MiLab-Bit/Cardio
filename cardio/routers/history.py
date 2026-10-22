from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from cardio import store
from cardio.server import get_current_user, resolve_owner

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.get("/api/history")
async def history(request: Request, contact_id: str | None = None):
    owner = resolve_owner(request)
    return {"status": "ok", "records": store.list_analyses(owner, contact_id=contact_id)}
