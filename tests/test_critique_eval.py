"""critique 质量门禁测试：用打分器断言"审官敢说问题"。

两层：
  1) 纯打分器单测（无需 LLM）—— 表扬型应判为"不敢说"，风险型应判为"敢说"。
  2) 集成：mock LLM 跑真实 critique_activity，断言其输出能被打分器识别为敢说问题。
见 product-optimization-audit.md §10.3。
"""
from __future__ import annotations

import asyncio

import cardio.llm as llm_mod
from cardio.eval.critique_rubric import score_critique
from cardio.eval.sample_inputs import SAMPLE_INPUTS
from cardio.temporal import activities as A


def test_rubric_flags_praise_only_as_not_daring():
    v = score_critique({"summary": "整体不错，建议推进", "risk_alerts": [], "advice": "", "passed": True})
    assert v["dare_to_flag"] is False
    assert v["has_alerts"] is False


def test_rubric_flags_risk_raising_as_daring():
    v = score_critique({
        "summary": "存在数据矛盾与缺失联系方式的风险，建议核实",
        "risk_alerts": ["策略提到电话跟进但 extraction 未提供 phone"],
        "advice": "补充联系方式后再推进",
        "passed": False,
    })
    assert v["dare_to_flag"] is True
    assert v["has_alerts"] is True
    assert "风险" in v["signals"]


def test_rubric_rejects_non_dict():
    import pytest

    with pytest.raises(TypeError):
        score_critique("not a dict")


def test_sample_inputs_well_formed():
    assert len(SAMPLE_INPUTS) >= 3
    for s in SAMPLE_INPUTS:
        assert "raw_text" in s and s["raw_text"]


def test_critique_activity_output_passes_rubric_with_mock(monkeypatch):
    async def fake_chat(messages, model=None, temperature=0.0, max_tokens=None, provider=None):
        return '{"risk_alerts":["缺联系方式"],"trust_score":0.5,"passed":false,"missing_info":["phone"],"advice":"补联系方式","summary":"缺失关键信息，建议核实"}'

    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    cri = asyncio.new_event_loop().run_until_complete(
        A.critique_activity({
            "extraction": {"name": "甲"},
            "synthesis": {"intent_score": 0.7},
            "strategy": {"next_steps": ["n"]},
            "provider": None,
            "owner": "u1",
        })
    )
    v = score_critique(cri)
    assert v["dare_to_flag"] is True
    assert cri["passed"] is False
