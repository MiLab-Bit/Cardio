from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from temporalio.exceptions import ApplicationError

from cardio import store
from cardio.cardscan import card_to_text, extract_card
from cardio.prompts import STAGE_META
from cardio.server import get_current_user, get_temporal_client, resolve_owner
from cardio.temporal.common import AnalyzeInput
from cardio.temporal.workflows.analyze import CardioAnalyzeWorkflow

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.post("/api/analyze")
async def analyze(request: Request):
    body = await request.json()
    text: str = (body.get("text") or "").strip()
    image: str | None = body.get("image")
    image_format: str = (body.get("image_format") or "jpeg")
    contact_id: str | None = body.get("contact_id")
    if not text and not image:
        raise HTTPException(status_code=400, detail={"error": "text or image required"})

    owner = resolve_owner(request)
    # 按槽位选 provider：文本分析走 text 槽，名片图片识别走 multimodal 槽；缺失则回退平台默认
    text_provider = store.get_active_provider(owner, "text")
    mm_provider = store.get_active_provider(owner, "multimodal")

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)

        async def run():
            nonlocal contact_id
            try:
                effective_text = text
                if image:
                    await queue.put(("vision_start", {}))
                    try:
                        card = await extract_card(image, image_format, provider=mm_provider)
                        await queue.put(("vision_done", {"card": card}))
                        contact = store.save_contact(owner, {
                            "name": card.get("name"),
                            "title": card.get("title"),
                            "company": card.get("company"),
                            "phone": card.get("phone") or card.get("mobile"),
                            "email": card.get("email"),
                            "tags": card.get("tags"),
                            "notes": card.get("raw_text", ""),
                        })
                        contact_id = contact['id']
                        await queue.put(("contact_saved", {"contact": contact}))
                        card_text = card_to_text(card)
                        if card_text:
                            effective_text = (card_text + "\n\n" + text).strip() if text else card_text
                    except Exception as exc:  # noqa: BLE001
                        await queue.put(("vision_error", {"error": str(exc)}))
                # 启动 Temporal 五段工作流（持久化 / 自动重试 / 断点可查）
                client = await get_temporal_client()
                handle = await client.start_workflow(
                    CardioAnalyzeWorkflow.run,
                    AnalyzeInput(
                        raw_text=effective_text,
                        raw_type="text",
                        provider=text_provider,
                        owner=owner,
                    ),
                    id=f"cardio-{owner}-{uuid.uuid4().hex}",
                    task_queue="cardio-task-queue",
                )
                seen = 0
                while True:
                    snap = await handle.query(CardioAnalyzeWorkflow.get_snapshot)
                    for item in snap.get('progress', [])[seen:]:
                        ev = item.get('event')
                        if ev == 'stage_start':
                            await queue.put(("stage_start", {
                                "stage": item["stage"],
                                "label": item.get("label", ""),
                                "agent": item.get("agent", ""),
                            }))
                        elif ev == 'stage_done':
                            await queue.put(("stage_done", {
                                "stage": item["stage"],
                                "report": item.get("report", {}),
                            }))
                        seen += 1
                    if snap.get('status') == 'completed':
                        break
                    await asyncio.sleep(1.0)
                final = await handle.result()
                store.save_analysis(owner, effective_text, final, contact_id=contact_id)
                await queue.put(("complete", {"result": final}))
            except ApplicationError as exc:
                if exc.type == 'QuotaExceeded':
                    await queue.put(("error", {"error": "今日 AI 额度已用完（每用户每日 3 次），明日重置；也可配置自己的模型 Key"}))
                else:
                    await queue.put(("error", {"error": str(exc)}))
            except Exception as exc:  # noqa: BLE001
                await queue.put(("error", {"error": str(exc)}))
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())

        while True:
            item = await queue.get()
            if item is None:
                break
            stage, data = item
            if stage == "pipeline_start":
                payload = {"type": "pipeline_start"}
            elif stage == "vision_start":
                payload = {"type": "vision_start"}
            elif stage == "vision_done":
                payload = {"type": "vision_done", "card": data.get("card", {})}
            elif stage == "contact_saved":
                payload = {"type": "contact_saved", "contact": data.get("contact", {})}
            elif stage == "vision_error":
                payload = {"type": "vision_error", "error": data.get("error", "")}
            elif stage == "stage_start":
                meta = STAGE_META.get(data["stage"], {})
                payload = {"type": "stage_start", "stage": data["stage"],
                           "label": meta.get("label", data["stage"]),
                           "agent": meta.get("agent", "")}
            elif stage == "stage_done":
                payload = {"type": "stage_done", "stage": data["stage"], "report": data["report"]}
            elif stage == "complete":
                payload = {"type": "complete", "result": data["result"]}
            elif stage == "error":
                payload = {"type": "error", "error": data.get("error")}
            else:
                payload = {"type": stage, **data}
            yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

        await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
