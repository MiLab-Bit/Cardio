# tests/test_distillation.py
"""Batch Distillation tests — L2 signals → L3 knowledge.

Ensures:
- ObjectionPattern[] → ObjectionPlaybook
- LearningSignal[] → TalkingPointEffect
- MemorySummary[] → ConversionPattern
- Idempotency works
- No transcript access (verified by design — only consumes structured signals)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from byou.distillation.models import (
    DistillationJobType,
    DistilledKnowledge,
    ObjectionPlaybook,
    ObjectionPlaybookEntry,
    TalkingPointEffect,
)
from byou.distillation.runner import DistillationJobTrigger, DistillationRunner


# ══════════════════════════════════════════════════════════
# Stub signal objects (simulate Memory reads without real DB)
# ══════════════════════════════════════════════════════════

@dataclass
class StubObjectionPattern:
    objection_topic: str = "price"
    user_phrase: str = "太贵了"
    agent_response: str = "我们支持分期付款"
    outcome: str = "overcome"
    industry: str = "fintech"
    company_scale: str = "medium"


@dataclass
class StubLearningSignal:
    description: str = "强调ROI数据后客户态度转变"
    signal_type: Any = "talking_point_effective"
    turn_index: int = 5


@dataclass
class StubMemorySummary:
    industry: str = "fintech"
    lead_id: str = "uid_001"
    best_talking_points: list = field(default_factory=lambda: ["ROI说明", "价格对比", "竞争对手劣势"])


# ══════════════════════════════════════════════════════════
# DistillationRunner
# ══════════════════════════════════════════════════════════

class TestDistillationRunner:
    async def test_objection_playbook_distillation(self):
        patterns = [
            StubObjectionPattern(objection_topic="price", outcome="overcome"),
            StubObjectionPattern(objection_topic="price", outcome="not_overcome"),
            StubObjectionPattern(objection_topic="competitor", outcome="overcome"),
        ]
        runner = DistillationRunner()
        knowledge = await runner.run(
            job_type=DistillationJobType.OBJECTION_PLAYBOOK,
            objection_patterns=patterns,
        )

        assert isinstance(knowledge, DistilledKnowledge)
        assert len(knowledge.playbooks) == 1
        playbook = knowledge.playbooks[0]
        assert isinstance(playbook, ObjectionPlaybook)
        assert len(playbook.entries) == 2  # price + competitor
        assert playbook.source_signal_count == 3

        price_entry = [e for e in playbook.entries if e.objection_topic == "price"][0]
        competitor_entry = [e for e in playbook.entries if e.objection_topic == "competitor"][0]

        assert price_entry.sample_count == 2
        assert price_entry.overcome_rate == 0.5  # 1/2
        assert competitor_entry.sample_count == 1
        assert competitor_entry.overcome_rate == 1.0  # 1/1

    async def test_playbook_empty_no_crash(self):
        runner = DistillationRunner()
        knowledge = await runner.run(
            job_type=DistillationJobType.OBJECTION_PLAYBOOK,
            objection_patterns=[],
        )
        assert knowledge is not None
        # empty patterns → no playbook generated

    async def test_conversion_pattern_distillation(self):
        summaries = [
            StubMemorySummary(industry="fintech", best_talking_points=["ROI说明"]),
            StubMemorySummary(industry="fintech", best_talking_points=["ROI说明", "价格对比"]),
            StubMemorySummary(industry="saas", best_talking_points=["竞品分析"]),
        ]
        runner = DistillationRunner()
        knowledge = await runner.run(
            job_type=DistillationJobType.CONVERSION_PATTERN,
            memory_summaries=summaries,
        )

        patterns = knowledge.conversion_patterns
        assert len(patterns) >= 1
        fintech = [p for p in patterns if p.industry == "fintech"][0]
        assert "ROI说明" in fintech.key_signals

    async def test_talking_point_effect(self):
        signals = [
            StubLearningSignal(description="强调ROI", signal_type="talking_point_effective"),
            StubLearningSignal(description="强调ROI", signal_type="talking_point_effective"),
            StubLearningSignal(description="强调ROI", signal_type="objection_unresolved"),
            StubLearningSignal(description="竞品对比", signal_type="talking_point_effective"),
        ]
        runner = DistillationRunner()
        knowledge = await runner.run(
            job_type=DistillationJobType.TALKING_POINT_EFFECT,
            learning_signals=signals,
        )

        effects = knowledge.talking_point_effects
        assert len(effects) == 2

        roi_effect = [e for e in effects if "ROI" in e.talking_point][0]
        assert roi_effect.sample_count == 3
        assert roi_effect.effectiveness_score == pytest.approx(0.67, abs=0.01)
        assert roi_effect.signal_type == "effective"

        competitor = [e for e in effects if "竞品" in e.talking_point][0]
        assert competitor.signal_type == "effective"
        assert competitor.effectiveness_score == 1.0

    async def test_full_run_all_types(self):
        runner = DistillationRunner()
        knowledge = await runner.run(
            job_type=DistillationJobType.FULL,
            objection_patterns=[StubObjectionPattern()],
            learning_signals=[StubLearningSignal()],
            memory_summaries=[StubMemorySummary()],
        )
        assert len(knowledge.playbooks) >= 1
        assert len(knowledge.talking_point_effects) >= 1

    async def test_on_complete_callback(self):
        callback_data = []

        async def on_complete(knowledge: DistilledKnowledge):
            callback_data.append(knowledge)

        runner = DistillationRunner()
        runner.on_complete(on_complete)

        await runner.run(
            job_type=DistillationJobType.OBJECTION_PLAYBOOK,
            objection_patterns=[StubObjectionPattern()],
        )

        assert len(callback_data) == 1
        assert isinstance(callback_data[0], DistilledKnowledge)

    async def test_dry_run_no_callback(self):
        callback_data = []

        async def on_complete(knowledge):
            callback_data.append(knowledge)

        runner = DistillationRunner()
        runner.on_complete(on_complete)

        await runner.run(
            job_type=DistillationJobType.OBJECTION_PLAYBOOK,
            objection_patterns=[StubObjectionPattern()],
            dry_run=True,
        )

        assert len(callback_data) == 0  # dry run suppresses writeback


# ══════════════════════════════════════════════════════════
# DistillationJobTrigger (idempotency)
# ══════════════════════════════════════════════════════════

class TestDistillationJobTrigger:
    async def test_idempotency(self):
        trigger = DistillationJobTrigger()

        sigs = [StubObjectionPattern()]
        key = "daily_2026_06_28"

        r1 = await trigger.trigger(
            job_type=DistillationJobType.OBJECTION_PLAYBOOK,
            idempotency_key=key,
            objection_patterns=sigs,
        )
        assert r1 is not None

        r2 = await trigger.trigger(
            job_type=DistillationJobType.OBJECTION_PLAYBOOK,
            idempotency_key=key,
            objection_patterns=sigs,
        )
        assert r2 is None  # idempotent skip

    async def test_different_keys_run_again(self):
        trigger = DistillationJobTrigger()

        sigs = [StubObjectionPattern()]

        r1 = await trigger.trigger(
            job_type=DistillationJobType.OBJECTION_PLAYBOOK,
            idempotency_key="run_1",
            objection_patterns=sigs,
        )
        assert r1 is not None

        r2 = await trigger.trigger(
            job_type=DistillationJobType.OBJECTION_PLAYBOOK,
            idempotency_key="run_2",
            objection_patterns=sigs,
        )
        assert r2 is not None  # different key = different run
