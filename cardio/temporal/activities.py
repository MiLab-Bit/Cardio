"""Cardio Temporal Activities — 五段管线各阶段封装。"""
from __future__ import annotations

import json
from typing import Any

from temporalio import activity


def _heartbeat(*d: str) -> None:
    try:
        activity.heartbeat(*d)
    except RuntimeError:
        pass


async def _llm_call(system: str, user: str, provider: dict | None = None, owner: str = "") -> dict:
    """共用 LLM 调用。"""
    from cardio import config, llm
    # Temporal activities must use the same quota/cache/BYOK gateway as the API,
    # not client_for() which exposes a raw, unmetered provider client.
    llm.set_scope(owner or "anon")
    text = await llm.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        model=config.LLM_MODEL,
        temperature=config.LLM_TEMPERATURE,
        max_tokens=config.LLM_MAX_TOKENS,
        provider=provider,
    )
    return llm.extract_json(text)


@activity.defn(name="extraction")
async def extraction_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 1: 信息提取。"""
    from cardio.pipeline import SYSTEM_EXTRACTION
    _heartbeat("extraction:start")
    result = await _llm_call(SYSTEM_EXTRACTION, inp["raw_text"], inp.get("provider"), inp.get("owner", ""))
    _heartbeat("extraction:done")
    return result


@activity.defn(name="research")
async def research_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 2: 背景调研。"""
    from cardio.pipeline import SYSTEM_RESEARCH
    _heartbeat("research:start")
    user_msg = json.dumps(inp.get("extraction", {}), ensure_ascii=False)
    result = await _llm_call(SYSTEM_RESEARCH, user_msg, inp.get("provider"), inp.get("owner", ""))
    _heartbeat("research:done")
    return result


@activity.defn(name="synthesis")
async def synthesis_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 3: 画像合成。"""
    from cardio.pipeline import SYSTEM_SYNTHESIS
    _heartbeat("synthesis:start")
    payload = {"extraction": inp.get("extraction"), "research": inp.get("research")}
    result = await _llm_call(SYSTEM_SYNTHESIS, json.dumps(payload, ensure_ascii=False), inp.get("provider"), inp.get("owner", ""))
    _heartbeat("synthesis:done")
    return result


@activity.defn(name="strategy")
async def strategy_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 4: BD 策略。"""
    from cardio.pipeline import SYSTEM_STRATEGY
    _heartbeat("strategy:start")
    payload = {"profile": inp.get("synthesis"), "extraction": inp.get("extraction")}
    result = await _llm_call(SYSTEM_STRATEGY, json.dumps(payload, ensure_ascii=False), inp.get("provider"), inp.get("owner", ""))
    _heartbeat("strategy:done")
    return result


@activity.defn(name="critique")
async def critique_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 5: 风险审核。"""
    from cardio.pipeline import SYSTEM_CRITIQUE
    _heartbeat("critique:start")
    payload = {
        "extraction": inp.get("extraction"),
        "research": inp.get("research"),
        "synthesis": inp.get("synthesis"),
        "strategy": inp.get("strategy"),
    }
    result = await _llm_call(SYSTEM_CRITIQUE, json.dumps(payload, ensure_ascii=False), inp.get("provider"), inp.get("owner", ""))
    _heartbeat("critique:done")
    return result
