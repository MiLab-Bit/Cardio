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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from temporalio.client import Client

from . import auth as auth_lib
from . import config, store

# ── Temporal client（懒加载，首次 analyze 时连接）──
_temporal_client = None

async def get_temporal_client():
    global _temporal_client
    if _temporal_client is None:
        _temporal_client = await Client.connect("127.0.0.1:7233", namespace="cardio")
    return _temporal_client


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


from cardio.routers import (
    analyze,
    apikeys,
    auth,
    card,
    chat,
    contacts,
    history,
    providers,
    system,
)

app.include_router(system.router)
app.include_router(auth.router)
app.include_router(apikeys.router)
app.include_router(providers.router)
app.include_router(chat.router)
app.include_router(analyze.router)
app.include_router(card.router)
app.include_router(contacts.router)
app.include_router(history.router)


# ── 公开：注册 / 登录 / 邮箱验证 ──








# ── Agent API Key 管理（需登录）──








# ── 用户自带大模型供应商配置（模型配置）──
# 与 RedTrip/BizAtlas 统一契约：驼峰字段（apiKey/baseUrl）+ presets 以 providers 列表返回。










# ── 商枢对话（SSE）──


# ── 五段式分析（SSE，支持名片图片，自动落库名片）──


# ── 名片识别（快速结构化并自动落库）──


# ── 数字商册（联系人）──








# ── 历史分析 ──


@app.exception_handler(HTTPException)
async def _http_exc(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content=exc.detail)
