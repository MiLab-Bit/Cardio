from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request

from cardio import auth as auth_lib
from cardio import config, email_utils, store

router = APIRouter()

@router.post("/api/auth/register")
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
    # 开发开关：注册即验证并直接登录（SMTP 就绪前跑通全链路）
    if config.AUTO_VERIFY_EMAIL:
        store.set_email_verified(uid)
        u = store.get_user(uid)
        token = auth_lib.issue_token(u["id"], u["email"], config.JWT_SECRET)
        return {"status": "registered", "token": token, "auto_verified": True,
                "user": {"id": u["id"], "email": u["email"], "name": u["name"]},
                "message": "注册成功，已自动登录（开发模式：邮箱验证已跳过）。"}
    # 正式流程：注册即未验证；发验证邮件（无 SMTP 则仅打印，开发态）
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

@router.get("/api/auth/verify-email")
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

@router.post("/api/auth/resend-verification")
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

@router.post("/api/auth/login")
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
