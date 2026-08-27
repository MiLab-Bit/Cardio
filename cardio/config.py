"""Cardio 配置 — 从环境变量读取（不依赖 pydantic-settings，保持轻量）。"""
from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # python-dotenv 可选
    pass


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


# ── LLM 网关（abc-ai.cn，OpenAI 兼容）──
LLM_BASE_URL = _env("CARDIO_LLM_BASE_URL", "https://www.abc-ai.cn/v1")
LLM_API_KEY = _env("CARDIO_LLM_API_KEY", "")
LLM_MODEL = _env("CARDIO_LLM_MODEL", "Qwen-flash")

# 统一只用 Qwen-flash，放弃小模型分层
LLM_MODEL_CHEAP = _env("CARDIO_LLM_MODEL_CHEAP", LLM_MODEL)
LLM_MODEL_MEDIUM = _env("CARDIO_LLM_MODEL_MEDIUM", LLM_MODEL)
LLM_MODEL_DEEP = _env("CARDIO_LLM_MODEL_DEEP", LLM_MODEL)

# 多模态视觉模型（名片识别等图像理解任务）。
# 默认按需求配置为 qwen3.5-397b-a17b；若该模型在当前 token 未授权，
# 可改为网关上已授权且支持视觉的模型（如 Qwen-flash）。
VISION_MODEL = _env("CARDIO_VISION_MODEL", "qwen3.5-397b-a17b")

LLM_TEMPERATURE = float(_env("CARDIO_LLM_TEMPERATURE", "0.7"))
LLM_MAX_TOKENS = int(_env("CARDIO_LLM_MAX_TOKENS", "2048"))
LLM_MAX_RETRIES = int(_env("CARDIO_LLM_MAX_RETRIES", "3"))

# ── 服务 ──
HOST = _env("CARDIO_HOST", "0.0.0.0")
PORT = int(_env("CARDIO_PORT", "8010"))

# 可选主密钥：设置了则 /api/* 需要 X-Cardio-Key；未设置则开放（演示用）
MASTER_API_KEY = _env("CARDIO_API_KEY", "")

# JWT 签名密钥：用户登录签发 Bearer token 用。空则启动失败（fail-fast）。
JWT_SECRET = _env("CARDIO_JWT_SECRET", "")

# 允许的前端来源（逗号分隔）；留空 = 允许全部
CORS_ORIGINS = [o for o in _env(
    "CARDIO_CORS_ORIGINS",
    "https://card-io.pages.dev,https://www.abc-ai.cn",
).split(",") if o]

# 数据库路径
DATA_DIR = _env("CARDIO_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
DB_PATH = _env("CARDIO_DB_PATH", os.path.join(DATA_DIR, "cardio.db"))

# 邮箱验证邮件中的回链基址（前端验证页域名）
EMAIL_BASE_URL = _env("CARDIO_EMAIL_BASE_URL", "https://card-io.pages.dev")
EMAIL_TOKEN_TTL = int(_env("CARDIO_EMAIL_TOKEN_TTL", "86400"))
