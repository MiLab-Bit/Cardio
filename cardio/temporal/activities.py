"""Cardio Temporal Activities — 五段管线各阶段封装。

所有 LLM 调用统一走 hermes_core.gateway（经由 cardio.llm.chat），
确保配额门控 / 并发闸门 / 重试 / 缓存 / BYOK 在五段路径上全部生效
（早期直连 AsyncOpenAI 会绕过配额，已在统一后修复）。
分段 temperature 取自 prompts.STAGE_TEMPERATURES，与产品承诺一致。
"""
from __future__ import annotations

import json
from typing import Any

from temporalio import activity

from cardio.prompts import (
    STAGE_TEMPERATURES,
    SYSTEM_CRITIQUE,
    SYSTEM_EXTRACTION,
    SYSTEM_RESEARCH,
    SYSTEM_STRATEGY,
    SYSTEM_SYNTHESIS,
)


def _heartbeat(*d: str) -> None:
    try:
        activity.heartbeat(*d)
    except RuntimeError:
        pass


async def _llm_call(
    system: str,
    user: str,
    provider: dict[str, Any] | None,
    owner: str,
    temperature: float,
) -> dict[str, Any]:
    """共用 LLM 调用：走 gateway（配额/重试/缓存/BYOK 统一），配额超限转 non-retryable。"""
    from cardio import config, llm

    llm.set_scope(owner or "anon")
    try:
        text = await llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=config.LLM_MODEL,
            temperature=temperature,
            max_tokens=config.LLM_MAX_TOKENS,
            provider=provider,
        )
    except llm.LLMQuotaExceeded:
        from temporalio.exceptions import ApplicationError

        raise ApplicationError(
            "LLM 每日配额已用完", type="QuotaExceeded", non_retryable=True
        )
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


@activity.defn(name="extraction")
async def extraction_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 1: 信息提取。"""
    _heartbeat("extraction:start")
    result = await _llm_call(
        SYSTEM_EXTRACTION, inp["raw_text"], inp.get("provider"),
        inp.get("owner", ""), STAGE_TEMPERATURES["extraction"],
    )
    _heartbeat("extraction:done")
    return result


@activity.defn(name="research")
async def research_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 2: 背景调研。"""
    _heartbeat("research:start")
    payload = json.dumps(inp.get("extraction", {}), ensure_ascii=False)
    result = await _llm_call(
        SYSTEM_RESEARCH, payload, inp.get("provider"),
        inp.get("owner", ""), STAGE_TEMPERATURES["research"],
    )
    _heartbeat("research:done")
    return result


@activity.defn(name="synthesis")
async def synthesis_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 3: 画像合成。"""
    _heartbeat("synthesis:start")
    payload = json.dumps(
        {"extraction": inp.get("extraction"), "research": inp.get("research")},
        ensure_ascii=False,
    )
    result = await _llm_call(
        SYSTEM_SYNTHESIS, payload, inp.get("provider"),
        inp.get("owner", ""), STAGE_TEMPERATURES["synthesis"],
    )
    _heartbeat("synthesis:done")
    return result


@activity.defn(name="strategy")
async def strategy_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 4: BD 策略。输入 = 画像 + 原始信息（与产品设计一致）。"""
    _heartbeat("strategy:start")
    payload = (
        "客户画像：\n" + json.dumps(inp.get("synthesis"), ensure_ascii=False)
        + "\n原始信息：\n" + (inp.get("raw_text") or "")
    )
    result = await _llm_call(
        SYSTEM_STRATEGY, payload, inp.get("provider"),
        inp.get("owner", ""), STAGE_TEMPERATURES["strategy"],
    )
    _heartbeat("strategy:done")
    return result


@activity.defn(name="critique")
async def critique_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 5: 风险审核。输入 = 档案 + 画像 + 策略（不含 research，与产品设计一致）。"""
    _heartbeat("critique:start")
    payload = (
        "客户档案：" + json.dumps(inp.get("extraction"), ensure_ascii=False) + "\n"
        "画像：" + json.dumps(inp.get("synthesis"), ensure_ascii=False) + "\n"
        "策略：" + json.dumps(inp.get("strategy"), ensure_ascii=False)
    )
    result = await _llm_call(
        SYSTEM_CRITIQUE, payload, inp.get("provider"),
        inp.get("owner", ""), STAGE_TEMPERATURES["critique"],
    )
    _heartbeat("critique:done")
    return result
