from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from cardio import store
from cardio.server import get_current_user, resolve_owner

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.get("/api/contacts")
async def list_contacts_route(request: Request, q: str | None = None):
    owner = resolve_owner(request)
    return {"status": "ok", "contacts": store.list_contacts(owner, q=q)}

@router.post("/api/contacts")
async def create_contact(request: Request):
    owner = resolve_owner(request)
    data = await request.json()
    contact = store.save_contact(owner, data)
    return {"status": "ok", "contact": contact}

@router.put("/api/contacts/{cid}")
async def update_contact_route(cid: str, request: Request):
    owner = resolve_owner(request)
    data = await request.json()
    contact = store.update_contact(owner, cid, data)
    if not contact:
        raise HTTPException(status_code=404, detail={"error": "contact not found or not owned"})
    return {"status": "ok", "contact": contact}

@router.delete("/api/contacts/{cid}")
async def delete_contact_route(cid: str, request: Request):
    owner = resolve_owner(request)
    if not store.delete_contact(owner, cid):
        raise HTTPException(status_code=404, detail={"error": "contact not found or not owned"})
    return {"status": "ok", "deleted": cid}
