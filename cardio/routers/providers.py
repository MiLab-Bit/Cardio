from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from cardio import llm, store
from cardio.server import get_current_user

router = APIRouter()

@router.get("/api/model-providers/presets")
async def mp_presets():
    return {"status": "ok", "providers": store.provider_presets()}

@router.get("/api/model-providers")
async def mp_list(request: Request):
    ident = get_current_user(request)
    return {"status": "ok", "providers": store.list_model_providers(ident["sub"])}

@router.post("/api/model-providers")
async def mp_create(request: Request):
    ident = get_current_user(request)
    data = await request.json()
    name = (data.get("name") or "").strip()
    provider = (data.get("provider") or "").strip()
    # 兼容驼峰与蛇形两种字段命名
    api_key = (data.get("apiKey") or data.get("api_key") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail={"error": "NAME_REQUIRED", "message": "请填写配置名称"})
    if not provider:
        raise HTTPException(status_code=400, detail={"error": "PROVIDER_REQUIRED", "message": "请选择供应商"})
    if provider not in [p["provider"] for p in store.provider_presets()] and provider != "custom":
        raise HTTPException(status_code=400, detail={"error": "UNKNOWN_PROVIDER", "message": "不支持的供应商"})
    if not api_key:
        raise HTTPException(status_code=400, detail={"error": "API_KEY_REQUIRED", "message": "请填写 API Key"})
    preset = store.preset_for(provider)
    base_url = (data.get("baseUrl") or data.get("base_url") or "").strip() or preset.get("baseUrl")
    model = (data.get("model") or "").strip() or preset.get("defaultModel")
    # 槽位：text（文本模型）或 multimodal（多模态模型），默认 text
    slot = (data.get("slot") or "text").strip()
    if slot not in ("text", "multimodal"):
        raise HTTPException(status_code=400, detail={"error": "INVALID_SLOT", "message": "slot 仅支持 text / multimodal"})
    pid = store.create_model_provider(ident["sub"], name, provider, api_key, base_url, model, slot=slot)
    return {"status": "ok", "id": pid, "provider": provider, "name": name, "model": model,
            "message": "已保存（API Key 已加密存储）。"}

@router.post("/api/model-providers/test")
async def mp_test(request: Request):
    get_current_user(request)
    data = await request.json()
    provider = (data.get("provider") or "").strip()
    api_key = (data.get("apiKey") or data.get("api_key") or "").strip()
    if not provider or not api_key:
        raise HTTPException(status_code=400, detail={"error": "PROVIDER_AND_KEY_REQUIRED"})
    preset = store.preset_for(provider)
    base_url = (data.get("baseUrl") or data.get("base_url") or "").strip() or preset.get("baseUrl")
    model = (data.get("model") or "").strip() or preset.get("defaultModel")
    result = await llm.test_provider(
        {"provider": provider, "api_key": api_key, "base_url": base_url, "model": model}
    )
    return {"status": "ok", **result}

@router.delete("/api/model-providers/{pid}")
async def mp_delete(pid: str, request: Request):
    ident = get_current_user(request)
    if not store.delete_model_provider(pid, ident["sub"]):
        raise HTTPException(status_code=404, detail={"error": "PROVIDER_NOT_FOUND"})
    return {"status": "ok", "deleted": pid}
