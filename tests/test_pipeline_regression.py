"""管线回归：mock LLM，逐段断言 JSON 结构、分段 temperature、阶段输入拼接。

不调用真实 LLM（CLAUDE.md 约定），用 monkeypatch 替换 cardio.llm.chat。
覆盖 activities 的关键契约，避免五段逻辑漂移（见 product-optimization-audit.md §10.3）。
"""
from __future__ import annotations

import asyncio

import cardio.llm as llm_mod
from cardio import prompts as P
from cardio.temporal import activities as A

_LOOP = asyncio.new_event_loop()


def _run(coro):
    return _LOOP.run_until_complete(coro)


def test_stage_schemas_and_temperature(monkeypatch):
    calls = []

    async def fake_chat(messages, model=None, temperature=0.0, max_tokens=None, provider=None):
        system = messages[0]["content"]
        user = messages[1]["content"] if len(messages) > 1 else ""
        calls.append({"system": system, "user": user, "temperature": temperature})
        if "提取官" in system:
            return '{"name":"甲","title":"CEO","company":"甲","phone":"","email":"","industry":"制造","needs":["x"],"tags":["y"],"summary":"s","confidence":0.9}'
        if "调研员" in system:
            return '{"company_profile":"p","industry_trends":["t"],"pain_points":["p1"],"opportunities":["o"],"suggested_sources":["s"],"summary":"s","confidence":0.8}'
        if "画像师" in system:
            return '{"enriched_profile":{},"intent_score":0.7,"customer_level":"重要","relationship_hint":"h","summary":"s","confidence":0.8}'
        if "谋士" in system:
            return '{"next_steps":["n"],"talking_points":["t"],"channels":["c"],"follow_up_timing":"w","proposal_idea":"i","summary":"s","confidence":0.7}'
        if "审官" in system:
            return '{"risk_alerts":["r1"],"trust_score":0.6,"passed":true,"missing_info":[],"advice":"a","summary":"存在风险点，建议核实"}'
        return '{"summary":"fallback"}'

    monkeypatch.setattr(llm_mod, "chat", fake_chat)

    base = {"raw_text": "某制造公司，王总，CTO，想采购数据中台", "provider": None, "owner": "u1"}

    ext = _run(A.extraction_activity(base))
    assert {"name", "company", "confidence"}.issubset(ext)
    assert calls[-1]["temperature"] == P.STAGE_TEMPERATURES["extraction"]

    res = _run(A.research_activity({**base, "extraction": ext}))
    assert {"industry_trends", "pain_points", "company_profile"}.issubset(res)
    assert calls[-1]["temperature"] == P.STAGE_TEMPERATURES["research"]

    syn = _run(A.synthesis_activity({**base, "extraction": ext, "research": res}))
    assert {"intent_score", "customer_level", "relationship_hint"}.issubset(syn)
    assert calls[-1]["temperature"] == P.STAGE_TEMPERATURES["synthesis"]

    stra = _run(A.strategy_activity({"synthesis": syn, "raw_text": base["raw_text"], "provider": None, "owner": "u1"}))
    assert {"next_steps", "talking_points", "channels", "follow_up_timing"}.issubset(stra)
    assert calls[-1]["temperature"] == P.STAGE_TEMPERATURES["strategy"]
    # 产品设计：strategy 输入 = 画像 + 原始信息
    assert base["raw_text"] in calls[-1]["user"]
    assert "客户画像" in calls[-1]["user"]

    cri = _run(A.critique_activity({"extraction": ext, "synthesis": syn, "strategy": stra, "provider": None, "owner": "u1"}))
    assert {"risk_alerts", "trust_score", "passed", "missing_info", "advice"}.issubset(cri)
    assert calls[-1]["temperature"] == P.STAGE_TEMPERATURES["critique"]
    # 产品设计：critique 输入 = 档案 + 画像 + 策略（不含 research）
    assert "客户档案" in calls[-1]["user"]
    assert "画像" in calls[-1]["user"]
    assert "策略" in calls[-1]["user"]
