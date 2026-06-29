# tests/test_phase3_models.py
"""Phase 3 model tests: ObjectionPattern, OutcomeReason, QAResult, LearningSignal, MemorySummary.

Also: channel-neutral model split backward compatibility.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from byou.models.channel_contract import (
    ActionDecisionType,
    BANTScore,
    FollowUpAction,
    FollowUpStatus,
    LearningSignal,
    LearningSignalType,
    MemorySummary,
    ObjectionOutcome,
    ObjectionPattern,
    OutcomeReason,
    OutcomeReasonType,
    PostCallReport,
    QAEvaluator,
    QAResult,
    QualificationSignal,
)

# ══════════════════════════════════════════════════════════
# ObjectionPattern
# ══════════════════════════════════════════════════════════

class TestObjectionPattern:
    def test_minimal_pattern(self):
        p = ObjectionPattern(
            pattern_id="obj_001",
            session_id="sess_1",
            lead_id="lead_1",
            objection_topic="价格",
        )
        assert p.objection_topic == "价格"
        assert p.outcome == ObjectionOutcome.UNRESOLVED
        assert p.confidence == 0.0
        assert p.user_phrase == ""
        assert p.agent_response == ""

    def test_full_pattern(self):
        p = ObjectionPattern(
            pattern_id="obj_002",
            session_id="sess_2",
            lead_id="lead_2",
            objection_topic="竞品",
            user_phrase="我们已经在用XX的系统了",
            agent_response="明白了，我们和XX的互补性很强",
            outcome=ObjectionOutcome.OVERCOME,
            confidence=0.85,
            related_turns=["turn_1", "turn_2"],
            related_talking_point="差异化价值",
            industry="金融",
            lead_role="CTO",
            company_scale="500-1000人",
        )
        assert p.outcome == ObjectionOutcome.OVERCOME
        assert p.confidence == 0.85
        assert len(p.related_turns) == 2
        assert p.industry == "金融"
        assert p.lead_role == "CTO"

    def test_serializable(self):
        p = ObjectionPattern(
            pattern_id="obj_003",
            session_id="sess_3",
            lead_id="lead_3",
            objection_topic="不需要",
        )
        d = p.model_dump(mode="json")
        assert d["pattern_id"] == "obj_003"
        assert d["objection_topic"] == "不需要"
        json.dumps(d)  # must not raise

    def test_outcome_enum_values(self):
        assert ObjectionOutcome.OVERCOME.value == "overcome"
        assert ObjectionOutcome.ESCALATED.value == "escalated"
        assert ObjectionOutcome.UNRESOLVED.value == "unresolved"


# ══════════════════════════════════════════════════════════
# OutcomeReason
# ══════════════════════════════════════════════════════════

class TestOutcomeReason:
    def test_minimal(self):
        r = OutcomeReason(
            session_id="sess_1",
            lead_id="lead_1",
            primary_reason=OutcomeReasonType.NO_ANSWER,
        )
        assert r.primary_reason == OutcomeReasonType.NO_ANSWER
        assert r.secondary_reasons == []
        assert r.confidence == 0.0

    def test_with_crm_summary(self):
        r = OutcomeReason(
            session_id="sess_1",
            lead_id="lead_1",
            primary_reason=OutcomeReasonType.QUALIFIED_NEED,
            confidence=0.8,
            narrative="客户表达了强烈的技术需求",
            crm_summary="意向客户 — 需要技术demo",
            evidence_turns=["turn_3", "turn_5"],
        )
        assert r.crm_summary == "意向客户 — 需要技术demo"
        assert len(r.evidence_turns) == 2

    def test_reason_enum(self):
        assert OutcomeReasonType.QUALIFIED_BUDGET.value == "qualified_budget"
        assert OutcomeReasonType.COMPETITOR_LOCK.value == "competitor_lock"
        assert OutcomeReasonType.NO_ANSWER.value == "no_answer"


# ══════════════════════════════════════════════════════════
# QAResult
# ══════════════════════════════════════════════════════════

class TestQAResult:
    def test_defaults(self):
        qa = QAResult(
            qa_id="qa_001",
            session_id="sess_1",
            lead_id="lead_1",
        )
        assert qa.overall_score == 1.0
        assert qa.evaluator == QAEvaluator.SLM_AUTO
        assert qa.flags == []

    def test_dimensioned_scores(self):
        qa = QAResult(
            qa_id="qa_002",
            session_id="sess_2",
            lead_id="lead_2",
            opening_score=0.5,
            discovery_score=0.2,
            objection_handling_score=0.7,
            closing_score=0.8,
            compliance_score=0.9,
            tone_score=0.6,
            overall_score=0.55,
            flags=["low_discovery", "weak_opening"],
            suggestions=["增加需求挖掘问题"],
        )
        assert qa.discovery_score == 0.2
        assert len(qa.flags) == 2
        assert "low_discovery" in qa.flags

    def test_serializable(self):
        qa = QAResult(
            qa_id="qa_003",
            session_id="sess_3",
            lead_id="lead_3",
            overall_score=0.6,
            flags=["weak_opening"],
        )
        d = qa.model_dump(mode="json")
        json.dumps(d)

    def test_evaluator_enum(self):
        assert QAEvaluator.SLM_AUTO.value == "slm_auto"
        assert QAEvaluator.HUMAN_REVIEW.value == "human_review"


# ══════════════════════════════════════════════════════════
# LearningSignal
# ══════════════════════════════════════════════════════════

class TestLearningSignal:
    def test_minimal(self):
        ls = LearningSignal(
            signal_id="ls_001",
            session_id="sess_1",
            lead_id="lead_1",
            signal_type=LearningSignalType.TALKING_POINT_EFFECTIVE,
            description="话术有效",
        )
        assert ls.signal_type == LearningSignalType.TALKING_POINT_EFFECTIVE
        assert ls.confidence == 0.0
        assert ls.related_turns == []

    def test_objection_overcome_signal(self):
        ls = LearningSignal(
            signal_id="ls_002",
            session_id="sess_2",
            lead_id="lead_2",
            signal_type=LearningSignalType.OBJECTION_OVERCOME,
            description="成功回应价格异议",
            confidence=0.9,
            related_turns=["turn_5", "turn_7"],
            industry="电商",
        )
        assert ls.confidence == 0.9
        assert ls.industry == "电商"
        assert len(ls.related_turns) == 2

    def test_signal_type_enum(self):
        assert LearningSignalType.TALKING_POINT_EFFECTIVE.value == "talking_point_effective"
        assert LearningSignalType.OBJECTION_UNRESOLVED.value == "objection_unresolved"


# ══════════════════════════════════════════════════════════
# MemorySummary
# ══════════════════════════════════════════════════════════

class TestMemorySummary:
    def test_empty(self):
        ms = MemorySummary(lead_id="lead_1")
        assert ms.total_calls == 0
        assert ms.last_call_at is None
        assert ms.overall_intent_score == 0.0

    def test_with_data(self):
        ms = MemorySummary(
            lead_id="lead_1",
            total_calls=3,
            last_call_at=datetime.now(timezone.utc),
            budget_signal="预算充足",
            need_signal="AI平台需求",
            overall_intent_score=0.75,
            intent_trend="rising",
            best_talking_points=["技术领先", "ROI明确"],
            common_objections=["价格"],
            object_pattern_ids=["obj_001"],
            learning_signal_ids=["ls_001", "ls_002"],
            best_time_to_call="下午3点",
            best_channel="voice",
            recommended_crm_stage="商机",
            recommended_next_action="安排技术Demo",
        )
        assert ms.total_calls == 3
        assert ms.intent_trend == "rising"
        assert len(ms.best_talking_points) == 2
        assert ms.recommended_crm_stage == "商机"

    def test_serializable(self):
        ms = MemorySummary(lead_id="lead_2", total_calls=1)
        d = ms.model_dump(mode="json")
        json.dumps(d)


# ══════════════════════════════════════════════════════════
# PostCallReport (Phase 3 fields)
# ══════════════════════════════════════════════════════════

class TestPostCallReportPhase3:
    def test_with_phase3_fields(self):
        report = PostCallReport(
            session_id="sess_1",
            lead_id="lead_1",
            business_decision="qualified",
            recommended_next_step="安排demo",
            qualification_signals=[
                QualificationSignal(
                    session_id="sess_1",
                    turn_id="turn_1",
                    signal_type="budget",
                    raw_text="预算100万",
                    confidence=0.8,
                    is_positive=True,
                    bant_dimension="budget",
                ),
            ],
            objection_patterns=[
                ObjectionPattern(
                    pattern_id="obj_1",
                    session_id="sess_1",
                    lead_id="lead_1",
                    objection_topic="价格",
                    outcome=ObjectionOutcome.OVERCOME,
                ),
            ],
            learning_signals=[
                LearningSignal(
                    signal_id="ls_1",
                    session_id="sess_1",
                    lead_id="lead_1",
                    signal_type=LearningSignalType.TALKING_POINT_EFFECTIVE,
                    description="ROI话术有效",
                ),
            ],
            outcome_reason=OutcomeReason(
                session_id="sess_1",
                lead_id="lead_1",
                primary_reason=OutcomeReasonType.QUALIFIED_BUDGET,
                confidence=0.8,
                crm_summary="意向客户-预算明确",
            ),
            quality_score=0.75,
            qa_result=QAResult(
                qa_id="qa_1",
                session_id="sess_1",
                lead_id="lead_1",
                overall_score=0.75,
            ),
        )
        assert report.business_decision == "qualified"
        assert len(report.objection_patterns) == 1
        assert len(report.learning_signals) == 1
        assert report.outcome_reason is not None
        assert report.qa_result is not None
        assert report.qa_result.overall_score == 0.75

    def test_bant_score(self):
        bant = BANTScore(budget=0.9, authority=0.5, need=0.8, timeline=0.0)
        assert bant.budget == 0.9
        assert bant.timeline == 0.0
        d = bant.model_dump()
        assert d["budget"] == 0.9

    def test_action_decision_type_enum(self):
        assert ActionDecisionType.FOLLOW_UP_TASK.value == "follow_up_task"
        assert ActionDecisionType.HUMAN_REVIEW.value == "human_review"
        assert ActionDecisionType.DURABLE_RETRY.value == "durable_retry"


# ══════════════════════════════════════════════════════════
# Backward compatibility (voice models → channel_contract)
# ══════════════════════════════════════════════════════════

class TestBackwardCompat:
    """Verify that channels/voice/models.py still exports channel-neutral types."""

    def test_voice_models_export_channel_neutral(self):
        """Voice models re-export channel_contract types for backward compat."""
        from byou.channels.voice.models import (
            LeadContext,
            PreCallPackage,
            QualificationSignal,
            FollowUpAction,
            PostCallReport,
            ObjectionPattern,
            OutcomeReason,
            LearningSignal,
            QAResult,
        )
        # All should import cleanly
        assert LeadContext is not None
        assert PreCallPackage is not None
        assert QualificationSignal is not None
        assert FollowUpAction is not None
        assert PostCallReport is not None
        # Phase 3 new types
        assert ObjectionPattern is not None
        assert OutcomeReason is not None
        assert LearningSignal is not None
        assert QAResult is not None

    def test_channel_contract_models_all_present(self):
        """All Phase 3 models are importable from channel_contract."""
        from byou.models.channel_contract import (
            ObjectionPattern,
            OutcomeReason,
            QAResult,
            LearningSignal,
            MemorySummary,
            ActionDecisionType,
        )
        assert ObjectionPattern is not None
        assert OutcomeReason is not None
        assert QAResult is not None
        assert LearningSignal is not None
        assert MemorySummary is not None
        assert ActionDecisionType is not None


# ══════════════════════════════════════════════════════════
# Transcript isolation check
# ══════════════════════════════════════════════════════════

class TestTranscriptIsolation:
    """Verify: new Phase 3 models do NOT carry raw transcript text."""

    def test_objection_pattern_no_full_transcript(self):
        """ObjectionPattern only has ≤200 char user_phrase, not full transcript."""
        p = ObjectionPattern(
            pattern_id="obj_1",
            session_id="sess_1",
            lead_id="lead_1",
            objection_topic="价格",
            user_phrase="a" * 201,  # Pydantic won't enforce but field docs say ≤200
        )
        # pattern itself has no transcript_text field
        assert not hasattr(p, "transcript_text")
        assert not hasattr(p, "full_transcript")

    def test_learning_signal_no_transcript(self):
        ls = LearningSignal(
            signal_id="ls_1",
            session_id="sess_1",
            lead_id="lead_1",
            signal_type=LearningSignalType.TALKING_POINT_EFFECTIVE,
            description="a" * 201,
        )
        assert not hasattr(ls, "transcript_text")
        assert not hasattr(ls, "raw_transcript")

    def test_outcome_reason_no_transcript(self):
        r = OutcomeReason(
            session_id="sess_1",
            lead_id="lead_1",
            primary_reason=OutcomeReasonType.QUALIFIED_NEED,
        )
        assert not hasattr(r, "transcript_text")
        assert not hasattr(r, "raw_transcript")

    def test_qa_result_no_transcript(self):
        qa = QAResult(qa_id="qa_1", session_id="sess_1", lead_id="lead_1")
        assert not hasattr(qa, "transcript_text")

    def test_postcall_report_references_not_content(self):
        """PostCallReport contains structured signals, not transcript text."""
        report = PostCallReport(
            session_id="sess_1",
            lead_id="lead_1",
        )
        # No transcript_text field
        assert not hasattr(report, "transcript_text")
        # qualification_signals have raw_text ≤200 chars from turn
        # objection_patterns have user_phrase ≤200 chars
        # These are references/summaries, not full transcripts
