"""Cardio 发信工具 — 零依赖 SMTP，读取共享配置 /opt/shared/smtp_config.json。

统一邮件发信源（abovetigers@qq.com），避免三产品各自复制 QQ 授权码。
优先级：
  1) 共享 JSON 文件 /opt/shared/smtp_config.json（smtp.host/username/password/from）
  2) 环境变量 SMTP_*（兼容老部署）
  3) 都没有 → 仅打印（开发态，不发真实邮件）
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

SHARED_SMTP_PATH = "/opt/shared/smtp_config.json"


def load_smtp_config() -> dict[str, Any] | None:
    # 1) 共享文件
    try:
        with open(SHARED_SMTP_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        s = data.get("smtp") or data
        if s.get("host") and s.get("username"):
            return s
    except Exception:
        pass
    # 2) 环境变量
    if os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USERNAME"):
        use_ssl = str(os.environ.get("SMTP_USE_SSL", "true")).lower() != "false"
        return {
            "host": os.environ["SMTP_HOST"],
            "port": int(os.environ.get("SMTP_PORT", 465)),
            "encryption": "ssl" if use_ssl else "tls",
            "username": os.environ["SMTP_USERNAME"],
            "password": os.environ.get("SMTP_PASSWORD", ""),
            "from": os.environ.get("SMTP_FROM", os.environ["SMTP_USERNAME"]),
        }
    return None


def send_email(to: str, subject: str, body_text: str | None = None, body_html: str | None = None) -> bool:
    """返回 True 表示真实发出；False 表示无 SMTP 配置（仅打印，开发态）。"""
    cfg = load_smtp_config()
    if not cfg:
        print(f"[mail:noop] -> {to} | {subject}\n{(body_text or body_html or '')[:400]}")
        return False
    msg = EmailMessage()
    msg["From"] = cfg["from"]
    msg["To"] = to
    msg["Subject"] = subject
    if body_text:
        msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    ctx = ssl.create_default_context()
    try:
        if cfg.get("encryption") == "tls":
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as s:
                s.starttls(context=ctx)
                s.login(cfg["username"], cfg["password"])
                s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=ctx, timeout=15) as s:
                s.login(cfg["username"], cfg["password"])
                s.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        print(f"[mail:error] -> {to} | {exc}")
        return False
    return True
