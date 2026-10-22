from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from cardio import config, llm, store
from cardio.cardscan import extract_card
from cardio.server import get_current_user, resolve_owner

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.post("/api/card/scan")
async def card_scan(request: Request):
    body = await request.json()
    image: str | None = body.get("image")
    if not image:
        raise HTTPException(status_code=400, detail={"error": "image required"})
    image_format = (body.get("image_format") or "jpeg")
    owner = resolve_owner(request)
    mm_provider = store.get_active_provider(owner, "multimodal")
    llm.set_scope(owner)
    try:
        card = await extract_card(image, image_format, provider=mm_provider)
    except llm.LLMQuotaExceeded:
        raise HTTPException(status_code=429, detail={"error": "今日 AI 额度已用完（每用户每日 3 次），明日重置；也可配置自己的模型 Key"})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail={"error": f"card scan failed: {exc}"})
    contact = store.save_contact(owner, {
        "name": card.get("name"),
        "title": card.get("title"),
        "company": card.get("company"),
        "phone": card.get("phone") or card.get("mobile"),
        "email": card.get("email"),
        "tags": card.get("tags"),
        "notes": card.get("raw_text", ""),
    })
    return {"status": "ok", "vision_model": config.VISION_MODEL, "card": card, "contact": contact}
