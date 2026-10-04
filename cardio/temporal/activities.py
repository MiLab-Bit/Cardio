"""Cardio Temporal Activities — 五段管线各阶段封装。"""
from __future__ import annotations
import asyncio, json
from typing import Any
from temporalio import activity


def _heartbeat(*d: str) -> None:
    try:
        activity.heartbeat(*d)
    except RuntimeError:
        pass


async def _llm_call(system: str, user: str, provider: dict | None = None) -> dict:
    """共用 LLM 调用。"""
    from cardio import llm, config
    client = llm.client_for(provider)
    resp = await client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=config.LLM_TEMPERATURE,
        max_tokens=config.LLM_MAX_TOKENS,
    )
    text = resp.choices[0].message.content or "{}"
    # 提取 JSON
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


@activity.defn(name="extraction")
async def extraction_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 1: 信息提取。"""
    from cardio.pipeline import SYSTEM_EXTRACTION
    _heartbeat("extraction:start")
    result = await _llm_call(SYSTEM_EXTRACTION, inp["raw_text"], inp.get("provider"))
    _heartbeat("extraction:done")
    return result


@activity.defn(name="research")
async def research_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 2: 背景调研。"""
    from cardio.pipeline import SYSTEM_RESEARCH
    _heartbeat("research:start")
    user_msg = json.dumps(inp.get("extraction", {}), ensure_ascii=False)
    result = await _llm_call(SYSTEM_RESEARCH, user_msg, inp.get("provider"))
    _heartbeat("research:done")
    return result


@activity.defn(name="synthesis")
async def synthesis_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 3: 画像合成。"""
    from cardio.pipeline import SYSTEM_SYNTHESIS
    _heartbeat("synthesis:start")
    payload = {"extraction": inp.get("extraction"), "research": inp.get("research")}
    result = await _llm_call(SYSTEM_SYNTHESIS, json.dumps(payload, ensure_ascii=False), inp.get("provider"))
    _heartbeat("synthesis:done")
    return result


@activity.defn(name="strategy")
async def strategy_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 4: BD 策略。"""
    from cardio.pipeline import SYSTEM_STRATEGY
    _heartbeat("strategy:start")
    payload = {"profile": inp.get("synthesis"), "extraction": inp.get("extraction")}
    result = await _llm_call(SYSTEM_STRATEGY, json.dumps(payload, ensure_ascii=False), inp.get("provider"))
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
    result = await _llm_call(SYSTEM_CRITIQUE, json.dumps(payload, ensure_ascii=False), inp.get("provider"))
    _heartbeat("critique:done")
    return result
