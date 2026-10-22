"""管线装配回归：直接测试 workflow 的纯方法（payload 拼接 / 包装 / 最终结构）。

不依赖 Temporal 运行时（不调用 workflow.run / execute_activity），只校验最容易
随 prompt/编排改动而漂移的装配逻辑（见 product-optimization-audit.md §10.3）。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from temporalio import workflow as _temporal_workflow

from cardio import prompts as P
from cardio.temporal.common import AnalyzeInput
from cardio.temporal.workflows import analyze as WF


@pytest.fixture(autouse=True)
def _patch_workflow_now(monkeypatch):
    """测试环境无 Temporal 运行时：patch workflow.now() 为固定确定性时间。"""
    fixed = datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(_temporal_workflow, "now", lambda: fixed)


def _wf() -> WF.CardioAnalyzeWorkflow:
    return WF.CardioAnalyzeWorkflow()


def test_build_payload_per_stage():
    wf = _wf()
    inp = AnalyzeInput(raw_text="某制造公司王总", raw_type="text", provider=None, owner="u1")
    wf.results = {
        "extraction": {"details": {"name": "甲", "company": "甲"}},
        "research": {"details": {"company_profile": "p"}},
        "synthesis": {"details": {"intent_score": 0.7, "customer_level": "重要"}},
        "strategy": {"details": {"next_steps": ["n"]}},
    }
    assert wf._build_payload("extraction", inp)["raw_text"] == "某制造公司王总"

    res_p = wf._build_payload("research", inp)
    assert res_p["extraction"]["name"] == "甲"

    syn_p = wf._build_payload("synthesis", inp)
    assert "extraction" in syn_p and "research" in syn_p

    strat_p = wf._build_payload("strategy", inp)
    assert "synthesis" in strat_p and strat_p["raw_text"] == "某制造公司王总"

    cri_p = wf._build_payload("critique", inp)
    assert {"extraction", "synthesis", "strategy"}.issubset(cri_p)
    assert "research" not in cri_p  # 设计上 critique 不含 research


def test_wrap_shape():
    wf = _wf()
    rep = wf._wrap("extraction", {"name": "甲", "confidence": 0.9})
    assert {"agent_name", "label", "summary", "details", "confidence", "generated_at"}.issubset(rep)
    assert rep["agent_name"] == "extraction" and rep["confidence"] == 0.9


def test_final_shape_includes_prompt_version():
    wf = _wf()
    inp = AnalyzeInput(raw_text="RT", raw_type="text", provider="p", owner="u1")
    wf.results = {
        "extraction": {"details": {"name": "甲", "title": "CEO", "company": "甲", "phone": "", "email": "", "industry": "制造", "needs": ["x"], "tags": ["y"]}},
        "research": {"details": {"company_profile": "p", "summary": "r"}},
        "synthesis": {"details": {"intent_score": 0.7, "customer_level": "重要", "summary": "s"}},
        "strategy": {"details": {"next_steps": ["n"], "summary": "st"}},
        "critique": {"details": {"risk_alerts": ["r"], "trust_score": 0.6, "passed": True, "missing_info": [], "advice": "a", "summary": "c"}},
    }
    final = wf._final(inp)
    assert {"input_text", "profile", "agent_reports", "completed_at", "prompt_version"}.issubset(final)
    assert final["profile"]["name"] == "甲"
    assert final["agent_reports"]["critique"]["details"]["risk_alerts"] == ["r"]
    assert final["prompt_version"] == P.ACTIVE_PROMPT_VERSION


def test_stage_order_canonical():
    assert P.STAGE_ORDER == ["extraction", "research", "synthesis", "strategy", "critique"]
