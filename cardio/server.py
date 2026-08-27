"""Cardio API — FastAPI 入口。

提供：
  GET  /health                      公开 — 含 db/auth 状态
  GET  /                            公开
  POST /api/auth/register           公开 — 注册，返回 JWT
  POST /api/auth/login              公开 — 登录，返回 JWT
  POST /api/chat        (需登录)     SSE 流式 — 商枢对话
  POST /api/analyze     (需登录)     SSE 流式 — 五段式商务分析（图片自动落库名片）
  POST /api/card/scan  (需登录)     名片识别并自动落库
  GET/POST/PUT/DELETE /api/contacts (需登录)  数字商册
  GET  /api/history    (需登录)     历史分析（可按 contact_id 过滤）

安全：CARDIO_JWT_SECRET 空则 fail-fast 拒绝开放；CORS 由 nginx 统一处理（本文件不再加）。
鉴权与 BizAtlas 同范式：Authorization: Bearer <JWT>，token.sub 即数据 owner。
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import auth as auth_lib
from . import config, store
from . import email_utils
from . import llm
from .pipeline import STAGE_META, run_pipeline
from .cardscan import extract_card, card_to_text

app = FastAPI(title="Cardio API", version="0.3.0")


# ── 启动 fail-fast：禁止空 JWT 密钥开放运行 ──
@app.on_event("startup")
def _startup():
    if not config.JWT_SECRET:
        raise RuntimeError(
            "CARDIO_JWT_SECRET 未设置，拒绝以开放模式启动（fail-fast）。"
            "请在 /opt/cardio/.env 设置强随机密钥后重启 cardio.service。"
        )


# ── 鉴权：全局依赖作用于 /api/*；/health、/、/api/auth/* 公开 ──
def authenticate(request: Request) -> dict:
    """返回调用者身份：人类 JWT 或 Agent API Key。失败抛 401。"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": "UNAUTHENTICATED", "message": "missing bearer token"},
        )
    cred = auth[7:].strip()
    # 1) Agent API Key（机器凭证）
    ak = store.get_api_key_by_hash(auth_lib.hash_api_key(cred))
    if ak and ak["status"] == "active":
        store.touch_api_key(ak["id"])
        return {"sub": ak["owner_id"], "api_key_id": ak["id"], "scopes": ak["scopes"], "kind": "agent"}
    # 2) 人类 JWT
    payload = auth_lib.decode_token(cred, config.JWT_SECRET)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail={"error": "UNAUTHENTICATED", "message": "invalid or expired token"},
        )
    # 人类账号未验证邮箱则禁止调用（注册后会收到验证邮件）
    if not store.get_user(payload["sub"]).get("email_verified"):
        raise HTTPException(
            status_code=403,
            detail={"error": "EMAIL_NOT_VERIFIED", "message": "请先通过邮件验证邮箱"},
        )
    return payload


def get_current_user(request: Request) -> dict:
    return authenticate(request)


def resolve_owner(request: Request) -> str:
    """从 Bearer 凭证取 owner（api 路由已 Depends 拦截未认证）。"""
    try:
        ident = authenticate(request)
    except HTTPException:
        return store.DEFAULT_OWNER
    return ident.get("sub", store.DEFAULT_OWNER)


api = APIRouter(dependencies=[Depends(get_current_user)])

app.include_router(api)


SHANGSHU_SYSTEM = (
    "你是「商枢」，Cardio 数字商册中勇敢而热情的商务助手，化用哥萨克般敢闯敢拼的精神。"
    "你帮助用户管理商务人脉、整理名片、分析客户、制定 BD 跟进策略。"
    "你说话简洁有力、有温度，善用比喻（商路、驼铃、罗盘）。"
    "当用户提供客户或会议信息时，主动建议用「数字商册分析」来深度研判。回答用中文。"
)


@app.get("/health")
async def health():
    return {
        "status": "ok", "service": "cardio", "version": "0.2.0",
        "model": config.LLM_MODEL, "vision_model": config.VISION_MODEL,
        "db": "ok" if store.check_db() else "error",
        "auth": "user",
    }


@app.get("/api/healthz")
async def healthz():
    # liveness 探针：不查 DB/外部依赖，供 k8s/systemd 存活检测。
    return {"status": "ok", "service": "cardio", "version": app.version, "time": time.time()}


@app.get("/")
async def root():
    return {
        "service": "cardio",
        "message": "Cardio · 新时代的数字商册",
        "docs": "/docs",
        "health": "/health",
    }


# ── 公开：注册 / 登录 / 邮箱验证 ──
@app.post("/api/auth/register")
async def register(request: Request):
    data = await request.json()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    name = (data.get("name") or "").strip()
    if not email or not password:
        raise HTTPException(status_code=400, detail={"error": "EMAIL_PASSWORD_REQUIRED"})
    if len(password) < 6:
        raise HTTPException(status_code=400, detail={"error": "PASSWORD_TOO_SHORT", "message": "密码至少 6 位"})
    uid = store.create_user(email, auth_lib.hash_password(password), name)
    if not uid:
        raise HTTPException(status_code=409, detail={"error": "EMAIL_TAKEN", "message": "该邮箱已注册"})
    # 注册即未验证；发验证邮件（无 SMTP 则仅打印，开发态）
    tok = auth_lib.make_verify_token()
    exp = str(int(time.time()) + config.EMAIL_TOKEN_TTL)
    store.save_verify_token(auth_lib.hash_token(tok), uid, "verify_email", exp)
    link = f"{config.EMAIL_BASE_URL.rstrip('/')}/verify-email?token={tok}"
    email_utils.send_email(
        email, "请验证您的邮箱 - Cardio",
        body_text=f"欢迎使用 Cardio。请点击以下链接验证邮箱（{config.EMAIL_TOKEN_TTL // 3600} 小时内有效）：\n{link}",
    )
    return {"status": "registered", "requires_verification": True, "email": email,
            "message": "注册成功，请查收验证邮件后登录。"}


@app.get("/api/auth/verify-email")
async def verify_email(token: str):
    rec = store.get_verify_token(auth_lib.hash_token(token))
    if not rec:
        raise HTTPException(status_code=400, detail={"error": "INVALID_TOKEN", "message": "验证链接无效或已过期"})
    if rec["purpose"] != "verify_email":
        raise HTTPException(status_code=400, detail={"error": "BAD_TOKEN", "message": "token 用途不符"})
    if rec["expires_at"] < str(int(time.time())):
        store.delete_verify_token(auth_lib.hash_token(token))
        raise HTTPException(status_code=400, detail={"error": "TOKEN_EXPIRED", "message": "验证链接已过期"})
    store.set_email_verified(rec["user_id"])
    store.delete_verify_token(auth_lib.hash_token(token))
    u = store.get_user(rec["user_id"])
    jwt = auth_lib.issue_token(u["id"], u["email"], config.JWT_SECRET)
    return {"status": "ok", "token": jwt, "user": {"id": u["id"], "email": u["email"], "name": u["name"]}}


@app.post("/api/auth/resend-verification")
async def resend_verification(request: Request):
    data = await request.json()
    email = (data.get("email") or "").strip()
    u = store.get_user_by_email(email)
    if not u or u["email_verified"]:
        # 不泄露账号是否存在
        return {"status": "ok", "message": "若邮箱存在且未验证，验证邮件已发送。"}
    tok = auth_lib.make_verify_token()
    exp = str(int(time.time()) + config.EMAIL_TOKEN_TTL)
    store.save_verify_token(auth_lib.hash_token(tok), u["id"], "verify_email", exp)
    link = f"{config.EMAIL_BASE_URL.rstrip('/')}/verify-email?token={tok}"
    email_utils.send_email(
        email, "请验证您的邮箱 - Cardio",
        body_text=f"请点击以下链接验证邮箱（{config.EMAIL_TOKEN_TTL // 3600} 小时内有效）：\n{link}",
    )
    return {"status": "ok", "message": "验证邮件已发送。"}


@app.post("/api/auth/login")
async def login(request: Request):
    data = await request.json()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    u = store.get_user_by_email(email)
    if not u or not auth_lib.verify_password(u["password_hash"], password):
        raise HTTPException(status_code=401, detail={"error": "INVALID_CREDENTIALS", "message": "邮箱或密码错误"})
    if not u["email_verified"]:
        raise HTTPException(
            status_code=403,
            detail={"error": "EMAIL_NOT_VERIFIED", "message": "请先通过邮件验证邮箱", "requires_verification": True},
        )
    token = auth_lib.issue_token(u["id"], email, config.JWT_SECRET)
    return {"status": "ok", "token": token, "user": {"id": u["id"], "email": email, "name": u["name"]}}


# ── Agent API Key 管理（需登录）──
@app.get("/api/apikeys")
async def list_keys(request: Request):
    ident = get_current_user(request)
    return {"status": "ok", "keys": store.list_api_keys(ident["sub"])}


@app.post("/api/apikeys")
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


@app.post("/api/apikeys/rotate")
async def rotate_key(request: Request):
    ident = get_current_user(request)
    data = await request.json()
    kid = data.get("key_id") or ""
    plain, prefix, h = auth_lib.generate_api_key("cd_")
    if not store.rotate_api_key(kid, ident["sub"], h, prefix):
        raise HTTPException(status_code=404, detail={"error": "KEY_NOT_FOUND"})
    return {"status": "ok", "key_id": kid, "key": plain, "warning": "旧 Key 已失效，此为新 Key（仅显示一次）。"}


@app.post("/api/apikeys/revoke")
async def revoke_key(request: Request):
    ident = get_current_user(request)
    data = await request.json()
    kid = data.get("key_id") or ""
    if not store.revoke_api_key(kid, ident["sub"]):
        raise HTTPException(status_code=404, detail={"error": "KEY_NOT_FOUND"})
    return {"status": "ok", "revoked": kid}


# ── 用户自带大模型供应商配置（模型配置）──
# 与 RedTrip/BizAtlas 统一契约：驼峰字段（apiKey/baseUrl）+ presets 以 providers 列表返回。
@app.get("/api/model-providers/presets")
async def mp_presets():
    return {"status": "ok", "providers": store.provider_presets()}


@app.get("/api/model-providers")
async def mp_list(request: Request):
    ident = get_current_user(request)
    return {"status": "ok", "providers": store.list_model_providers(ident["sub"])}


@app.post("/api/model-providers")
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


@app.post("/api/model-providers/test")
async def mp_test(request: Request):
    ident = get_current_user(request)
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


@app.delete("/api/model-providers/{pid}")
async def mp_delete(pid: str, request: Request):
    ident = get_current_user(request)
    if not store.delete_model_provider(pid, ident["sub"]):
        raise HTTPException(status_code=404, detail={"error": "PROVIDER_NOT_FOUND"})
    return {"status": "ok", "deleted": pid}


# ── 商枢对话（SSE）──
@api.post("/api/chat")
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
        gen = await llm.chat(messages, stream=True, provider=provider)
        async for token in gen:
            yield "data: " + json.dumps({"type": "token", "text": token}, ensure_ascii=False) + "\n\n"
        yield "data: " + json.dumps({"type": "done"}, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ── 五段式分析（SSE，支持名片图片，自动落库名片）──
@api.post("/api/analyze")
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

        async def on_progress(stage: str, data: dict) -> None:
            try:
                await queue.put((stage, data))
            except asyncio.QueueFull:
                pass

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
                        contact_id = contact["id"]
                        await queue.put(("contact_saved", {"contact": contact}))
                        card_text = card_to_text(card)
                        if card_text:
                            effective_text = (card_text + "\n\n" + text).strip() if text else card_text
                    except Exception as exc:  # noqa: BLE001
                        await queue.put(("vision_error", {"error": str(exc)}))
                result = await run_pipeline(effective_text, on_progress=on_progress, provider=text_provider)
                store.save_analysis(owner, effective_text, result, contact_id=contact_id)
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


# ── 名片识别（快速结构化并自动落库）──
@api.post("/api/card/scan")
async def card_scan(request: Request):
    body = await request.json()
    image: str | None = body.get("image")
    if not image:
        raise HTTPException(status_code=400, detail={"error": "image required"})
    image_format = (body.get("image_format") or "jpeg")
    owner = resolve_owner(request)
    mm_provider = store.get_active_provider(owner, "multimodal")
    try:
        card = await extract_card(image, image_format, provider=mm_provider)
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


# ── 数字商册（联系人）──
@api.get("/api/contacts")
async def list_contacts_route(request: Request, q: str | None = None):
    owner = resolve_owner(request)
    return {"status": "ok", "contacts": store.list_contacts(owner, q=q)}


@api.post("/api/contacts")
async def create_contact(request: Request):
    owner = resolve_owner(request)
    data = await request.json()
    contact = store.save_contact(owner, data)
    return {"status": "ok", "contact": contact}


@api.put("/api/contacts/{cid}")
async def update_contact_route(cid: str, request: Request):
    owner = resolve_owner(request)
    data = await request.json()
    contact = store.update_contact(owner, cid, data)
    if not contact:
        raise HTTPException(status_code=404, detail={"error": "contact not found or not owned"})
    return {"status": "ok", "contact": contact}


@api.delete("/api/contacts/{cid}")
async def delete_contact_route(cid: str, request: Request):
    owner = resolve_owner(request)
    if not store.delete_contact(owner, cid):
        raise HTTPException(status_code=404, detail={"error": "contact not found or not owned"})
    return {"status": "ok", "deleted": cid}


# ── 历史分析 ──
@api.get("/api/history")
async def history(request: Request, contact_id: str | None = None):
    owner = resolve_owner(request)
    return {"status": "ok", "records": store.list_analyses(owner, contact_id=contact_id)}


@app.exception_handler(HTTPException)
async def _http_exc(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content=exc.detail)
