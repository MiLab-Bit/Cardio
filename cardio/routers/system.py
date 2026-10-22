from __future__ import annotations

import time

from fastapi import APIRouter

from cardio import config, store
from cardio.server import app

router = APIRouter()

@router.get("/health")
async def health():
    return {
        "status": "ok", "service": "cardio", "version": "0.3.0",
        "model": config.LLM_MODEL, "vision_model": config.VISION_MODEL,
        "db": "ok" if store.check_db() else "error",
        "auth": "user", "auto_verify_email": config.AUTO_VERIFY_EMAIL,
    }

@router.get("/api/healthz")
async def healthz():
    # liveness 探针：不查 DB/外部依赖，供 k8s/systemd 存活检测。
    return {"status": "ok", "service": "cardio", "version": app.version, "time": time.time()}

@router.get("/")
async def root():
    return {
        "service": "cardio",
        "message": "Cardio · 新时代的数字商册",
        "docs": "/docs",
        "health": "/health",
    }
