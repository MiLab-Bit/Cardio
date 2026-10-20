"""Cardio LLM 客户端 — 委托 openclaw_core.gateway.Gateway。

配额门控 / 并发闸门 / 指数退避 / 响应缓存 / JSON 解析全部下沉到共享库，
本文件只保留产品级对外符号（chat / vision_chat / test_provider /
set_scope / client_for / extract_json / LLMQuotaExceeded），调用点零改动。
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import AsyncIterator

from openai import AsyncOpenAI

from . import config
from openclaw_core.gateway import Gateway, QuotaExceeded, extract_json

# 向后兼容别名（Gateway 超限抛 QuotaExceeded）
LLMQuotaExceeded = QuotaExceeded

_scope: ContextVar[str] = ContextVar("cardio_llm_scope", default="anon")


def set_scope(scope: str) -> None:
    """设置当前请求的配额 scope（用户 id）；请求内所有平台网关调用共用。"""
    _scope.set(scope or "anon")


_gateway = Gateway(
    platform_base_url=config.LLM_BASE_URL,
    platform_api_key=config.LLM_API_KEY,
    default_model=config.LLM_MODEL,
    quota_db=config.QUOTA_DB_PATH,
    max_concurrency=5,
    max_retries=config.LLM_MAX_RETRIES,
    timeout=120.0,
    cache_db=config.DB_PATH,
)


def client_for(provider: dict | None = None) -> AsyncOpenAI:
    """兼容旧调用：返回平台或 BYOK 的 AsyncOpenAI 客户端。"""
    if provider and provider.get("api_key"):
        return AsyncOpenAI(
            base_url=provider.get("base_url") or config.LLM_BASE_URL,
            api_key=provider["api_key"],
            timeout=120.0,
            max_retries=2,
        )
    return _gateway._client(config.LLM_BASE_URL, config.LLM_API_KEY or "sk-placeholder")


async def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    stream: bool = False,
    provider: dict | None = None,
) -> str | AsyncIterator[str]:
    """非流式返回完整文本；流式返回 token 异步迭代器。provider 携带时走 BYOK。"""
    return await _gateway.chat(
        messages,
        model=model or config.LLM_MODEL,
        temperature=temperature if temperature is not None else config.LLM_TEMPERATURE,
        max_tokens=max_tokens or config.LLM_MAX_TOKENS,
        stream=stream,
        provider=provider,
        scope=_scope.get(),
    )


async def vision_chat(
    text_prompt: str,
    image_b64: str | None = None,
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1500,
    image_format: str = "jpeg",
    provider: dict | None = None,
) -> str:
    """多模态调用：支持图文输入（名片识别等）。"""
    content: list[dict] = []
    if image_b64:
        url = image_b64 if image_b64.startswith("data:") else f"data:image/{image_format};base64,{image_b64}"
        content.append({"type": "image_url", "image_url": {"url": url}})
    content.append({"type": "text", "text": text_prompt})
    return await _gateway.chat(
        [{"role": "user", "content": content}],
        model=model or config.VISION_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
        provider=provider,
        scope=_scope.get(),
    )


async def test_provider(provider: dict) -> dict:
    """验证用户自带供应商配置是否可用。"""
    return await _gateway.test_provider(provider)
