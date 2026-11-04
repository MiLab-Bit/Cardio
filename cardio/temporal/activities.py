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


async def _llm_call(
    system: str, user: str, provider_id: str | None = None,
    owner: str = "", stage: str = "extraction",
) -> dict[str, Any]:
    """Resolve BYOK only in this Activity process; keep credentials out of history.

    Temporal receives the provider_id and owner, never api_key/api_key_enc.
    Model failures are redacted before Temporal persists activity exceptions.
    """
    from temporalio.exceptions import ApplicationError

    from cardio import config, llm, store
    from cardio.pipeline import STAGE_TEMPERATURES

    try:
        provider = store.resolve_workflow_provider(provider_id, owner) if provider_id else None
    except Exception:
        raise ApplicationError("Configured text provider unavailable", non_retryable=True) from None

    llm.set_scope(owner or "anon")
    try:
        text = await llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=(provider or {}).get("model") or config.LLM_MODEL,
            temperature=STAGE_TEMPERATURES.get(stage, config.LLM_TEMPERATURE),
            max_tokens=config.LLM_MAX_TOKENS,
            provider=provider,  # local variable only: never placed in Activity result
        )
        return llm.extract_json(text)
    except llm.LLMQuotaExceeded:
        raise ApplicationError("Cardio platform quota exceeded", non_retryable=True) from None
    except Exception:
        # Provider errors sometimes echo request headers or credentials; avoid
        # storing third-party exception details in Temporal history.
        raise ApplicationError("Cardio LLM activity failed") from None


@activity.defn(name="extraction")
async def extraction_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 1: 信息提取。"""
    from cardio.pipeline import SYSTEM_EXTRACTION
    _heartbeat("extraction:start")
    result = await _llm_call(SYSTEM_EXTRACTION, inp["raw_text"], inp.get("provider_id"), inp.get("owner", ""), stage="extraction")
    _heartbeat("extraction:done")
    return result


@activity.defn(name="research")
async def research_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 2: 背景调研。"""
    from cardio.pipeline import SYSTEM_RESEARCH
    _heartbeat("research:start")
    user_msg = json.dumps(inp.get("extraction", {}), ensure_ascii=False)
    result = await _llm_call(SYSTEM_RESEARCH, user_msg, inp.get("provider_id"), inp.get("owner", ""), stage="research")
    _heartbeat("research:done")
    return result


@activity.defn(name="synthesis")
async def synthesis_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 3: 画像合成。"""
    from cardio.pipeline import SYSTEM_SYNTHESIS
    _heartbeat("synthesis:start")
    payload = {"extraction": inp.get("extraction"), "research": inp.get("research")}
    result = await _llm_call(SYSTEM_SYNTHESIS, json.dumps(payload, ensure_ascii=False), inp.get("provider_id"), inp.get("owner", ""), stage="synthesis")
    _heartbeat("synthesis:done")
    return result


@activity.defn(name="strategy")
async def strategy_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """阶段 4: BD 策略。"""
    from cardio.pipeline import SYSTEM_STRATEGY
    _heartbeat("strategy:start")
    payload = {"profile": inp.get("synthesis"), "extraction": inp.get("extraction")}
    result = await _llm_call(SYSTEM_STRATEGY, json.dumps(payload, ensure_ascii=False), inp.get("provider_id"), inp.get("owner", ""), stage="strategy")
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
    result = await _llm_call(SYSTEM_CRITIQUE, json.dumps(payload, ensure_ascii=False), inp.get("provider_id"), inp.get("owner", ""), stage="critique")
    _heartbeat("critique:done")
    return result


@activity.defn(name="persist_analysis")
async def persist_analysis_activity(inp: dict[str, Any]) -> dict[str, Any]:
    """Save a completed business analysis idempotently even if SSE disconnects.

    Receives only model outputs, workflow ID and business identifiers. No BYOK
    credential or encrypted token ever appears in workflow/activity arguments.
    """
    from datetime import datetime, timezone

    from cardio import store
    from cardio.pipeline import STAGE_META, STAGE_ORDER

    reports = inp["results"]
    extracted = reports.get("extraction", {})
    fields = ("name", "title", "company", "phone", "email", "industry", "needs", "tags")
    profile = {k: extracted.get(k, [] if k in ("needs", "tags") else "") for k in fields}
    now = datetime.now(timezone.utc).isoformat()
    output = {
        "input_text": inp["input_text"],
        "profile": profile,
        "agent_reports": {
            name: {
                "agent_name": name,
                "label": STAGE_META[name]["label"],
                "summary": reports[name].get("summary", STAGE_META[name]["label"] + "完成"),
                "details": reports[name],
                "confidence": reports[name].get("confidence", 0.0),
                "generated_at": now,
            }
            for name in STAGE_ORDER
        },
        "completed_at": now,
    }
    store.save_analysis(
        inp["owner"], inp["input_text"], output,
        contact_id=inp.get("contact_id"), analysis_id=inp["analysis_id"],
    )
    return output
