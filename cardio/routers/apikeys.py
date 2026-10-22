from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from cardio import auth as auth_lib
from cardio import store
from cardio.server import get_current_user

router = APIRouter()

@router.get("/api/apikeys")
async def list_keys(request: Request):
    ident = get_current_user(request)
    return {"status": "ok", "keys": store.list_api_keys(ident["sub"])}

@router.post("/api/apikeys")
async def create_key(request: Request):
    ident = get_current_user(request)
    data = await request.json()
    name = (data.get("name") or "").strip() or "unnamed"
    scopes = data.get("scopes") or ["*"]
    if not isinstance(scopes, list):
        scopes = ["*"]
    plain, prefix, h = auth_lib.generate_api_key("cd_")
    kid = store.create_api_key(ident["sub"], name, h, prefix, scopes)
    return {"status": "ok", "key_id": kid, "key": plain,
            "warning": "此明文 Key 仅显示一次，请妥善保存。",
            "key_preview": f"{prefix}****"}

@router.post("/api/apikeys/rotate")
async def rotate_key(request: Request):
    ident = get_current_user(request)
    data = await request.json()
    kid = data.get("key_id") or ""
    plain, prefix, h = auth_lib.generate_api_key("cd_")
    if not store.rotate_api_key(kid, ident["sub"], h, prefix):
        raise HTTPException(status_code=404, detail={"error": "KEY_NOT_FOUND"})
    return {"status": "ok", "key_id": kid, "key": plain, "warning": "旧 Key 已失效，此为新 Key（仅显示一次）。"}

@router.post("/api/apikeys/revoke")
async def revoke_key(request: Request):
    ident = get_current_user(request)
    data = await request.json()
    kid = data.get("key_id") or ""
    if not store.revoke_api_key(kid, ident["sub"]):
        raise HTTPException(status_code=404, detail={"error": "KEY_NOT_FOUND"})
    return {"status": "ok", "revoked": kid}
