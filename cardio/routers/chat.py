from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from cardio import llm, store
from cardio.prompts import SHANGSHU_SYSTEM
from cardio.server import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    message: str = (body.get("message") or "").strip()
    history: list[dict] = body.get("history") or []
    if not message:
        raise HTTPException(status_code=400, detail={"error": "message required"})

    # 若用户配置了自带文本模型（text 槽），则用它调模型；否则回退平台网关
    ident = get_current_user(request)
    provider = store.get_active_provider(ident["sub"], "text")
    if provider:
        store.touch_model_provider(provider["id"])

    messages = [{"role": "system", "content": SHANGSHU_SYSTEM}]
    for h in history[-12:]:
        role = h.get("role")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": h.get("content", "")})
    messages.append({"role": "user", "content": message})

    async def event_stream():
        yield "data: " + json.dumps({"type": "start"}, ensure_ascii=False) + "\n\n"
        llm.set_scope(ident["sub"])
        try:
            gen = await llm.chat(messages, stream=True, provider=provider)
            async for token in gen:
                yield "data: " + json.dumps({"type": "token", "text": token}, ensure_ascii=False) + "\n\n"
        except llm.LLMQuotaExceeded:
            yield "data: " + json.dumps(
                {"type": "error", "error": "今日 AI 额度已用完（每用户每日 3 次），明日重置；也可在「模型提供方」配置自己的 Key"},
                ensure_ascii=False,
            ) + "\n\n"
            return
        except Exception as exc:  # noqa: BLE001 — 网关不可用等：以 SSE error 事件告知前端，避免裸崩流
            yield "data: " + json.dumps(
                {"type": "error", "error": f"模型服务暂时不可用：{exc}"}, ensure_ascii=False
            ) + "\n\n"
            return
        yield "data: " + json.dumps({"type": "done"}, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
