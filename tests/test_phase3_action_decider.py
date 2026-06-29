# tests/test_phase3_action_decider.py
"""Phase 3 ActionDecider tests — decision matrix validation."""

from __future__ import annotations

import pytest

from byou.core.conversation.action_decider import (
    ActionDecider,
    ActionDecision,
    DecisionPriority,
)
from byou.models.channel_contract import (
    ActionDecisionType,
    FollowUpAction,
    FollowUpStatus,
    ObjectionOutcome,
    ObjectionPattern,
    OutcomeReason,
    OutcomeReasonType,
    PostCallReport,
    QAResult,
    QualificationSignal,
)


# ── Helpers ──────────────────────────────────────────────

def _make_report(
    session_id="sess_1",
    lead_id="lead_1",
    signals=None,
    objection_patterns=None,
    outcome_reason=None,
    qa_result=None,
    quality_score=0.8,
) -> PostCallReport:
    return PostCallReport(
        session_id=session_id,
        lead_id=lead_id,
        qualification_signals=signals or [],
        objection_patterns=objection_patterns or [],
        outcome_reason=outcome_reason,
        quality_score=quality_score,
        qa_result=qa_result,
        business_decision="follow_up",
    )


def _qa(score=0.8, flags=None) -> QAResult:
    return QAResult(
        qa_id="qa_1",
        session_id="sess_1",
        lead_id="lead_1",
        overall_score=score,
        flags=flags or [],
    )


def _positive_signal(sig_type="need", confidence=0.8) -> QualificationSignal:
    return QualificationSignal(
        session_id="sess_1",
        turn_id="turn_1",
        signal_type=sig_type,
        raw_text="需要AI解决方案",
        confidence=confidence,
        is_positive=True,
        bant_dimension=sig_type,
    )


def _objection(topic="价格", outcome=ObjectionOutcome.UNRESOLVED) -> ObjectionPattern:
    return ObjectionPattern(
        pattern_id=f"obj_{topic}",
        session_id="sess_1",
        lead_id="lead_1",
        objection_topic=topic,
        outcome=outcome,
    )


def _outcome_reason(primary=OutcomeReasonType.QUALIFIED_NEED) -> OutcomeReason:
    return OutcomeReason(
        session_id="sess_1",
        lead_id="lead_1",
        primary_reason=primary,
    )


# ══════════════════════════════════════════════════════════
# Test: Positive signals → FOLLOW_UP_TASK + CRM_NOTE_ONLY
# ══════════════════════════════════════════════════════════

class TestPositiveSignals:
    @pytest.mark.asyncio
    async def test_single_positive_need_signal(self):
        decider = ActionDecider()
        report = _make_report(signals=[_positive_signal("need")])
        decisions = decider.decide(report)

        types = {d.decision_type for d in decisions}
        assert ActionDecisionType.FOLLOW_UP_TASK in types
        assert ActionDecisionType.CRM_NOTE_ONLY in types

    @pytest.mark.asyncio
    async def test_budget_signal_high_priority(self):
        decider = ActionDecider()
        report = _make_report(signals=[_positive_signal("budget")])
        decisions = decider.decide(report)

        fu = [d for d in decisions if d.decision_type == ActionDecisionType.FOLLOW_UP_TASK]
        assert len(fu) == 1
        assert fu[0].priority == DecisionPriority.HIGH

    @pytest.mark.asyncio
    async def test_no_positive_signals_no_follow_up(self):
        decider = ActionDecider()
        report = _make_report(signals=[
            QualificationSignal(
                session_id="sess_1", turn_id="t1", signal_type="need",
                raw_text="no", confidence=0.3, is_positive=False, bant_dimension="need",
            )
        ])
        decisions = decider.decide(report)

        types = {d.decision_type for d in decisions}
        assert ActionDecisionType.FOLLOW_UP_TASK not in types
        # But should still have CRM_NOTE_ONLY as fallback
        assert ActionDecisionType.CRM_NOTE_ONLY in types

    @pytest.mark.asyncio
    async def test_multiple_positive_signals(self):
        decider = ActionDecider()
        report = _make_report(signals=[
            _positive_signal("budget"),
            _positive_signal("need"),
            _positive_signal("timing", confidence=0.6),
        ])
        decisions = decider.decide(report)
        assert len(decisions) >= 2
        types = {d.decision_type for d in decisions}
        assert ActionDecisionType.FOLLOW_UP_TASK in types


# ══════════════════════════════════════════════════════════
# Test: Low QA → HUMAN_REVIEW
# ══════════════════════════════════════════════════════════

class TestLowQA:
    @pytest.mark.asyncio
    async def test_qa_below_0_3_triggers_review(self):
        decider = ActionDecider()
        report = _make_report(qa_result=_qa(0.25))
        decisions = decider.decide(report)

        review = [d for d in decisions if d.decision_type == ActionDecisionType.HUMAN_REVIEW]
        assert len(review) == 1
        assert review[0].priority == DecisionPriority.CRITICAL

    @pytest.mark.asyncio
    async def test_qa_below_0_5_medium_review(self):
        decider = ActionDecider()
        report = _make_report(qa_result=_qa(0.4))
        decisions = decider.decide(report)

        review = [d for d in decisions if d.decision_type == ActionDecisionType.HUMAN_REVIEW]
        assert len(review) == 1
        assert review[0].priority == DecisionPriority.MEDIUM

    @pytest.mark.asyncio
    async def test_qa_above_0_5_no_review(self):
        decider = ActionDecider()
        report = _make_report(qa_result=_qa(0.7))
        decisions = decider.decide(report)

        review = [d for d in decisions if d.decision_type == ActionDecisionType.HUMAN_REVIEW]
        assert len(review) == 0

    @pytest.mark.asyncio
    async def test_no_qa_result_no_review(self):
        decider = ActionDecider()
        report = _make_report(qa_result=None)
        decisions = decider.decide(report)

        review = [d for d in decisions if d.decision_type == ActionDecisionType.HUMAN_REVIEW]
        assert len(review) == 0


# ══════════════════════════════════════════════════════════
# Test: Compliance flag → HUMAN_REVIEW (always)
# ══════════════════════════════════════════════════════════

class TestComplianceFlag:
    @pytest.mark.asyncio
    async def test_compliance_flag_triggers_review(self):
        decider = ActionDecider()
        report = _make_report(qa_result=_qa(0.9, flags=["compliance_violation"]))
        decisions = decider.decide(report)

        review = [d for d in decisions if d.decision_type == ActionDecisionType.HUMAN_REVIEW]
        assert len(review) == 1
        assert review[0].priority == DecisionPriority.CRITICAL


# ══════════════════════════════════════════════════════════
# Test: No answer / Technical failure → DURABLE_RETRY
# ══════════════════════════════════════════════════════════

class TestRetryDecision:
    @pytest.mark.asyncio
    async def test_no_answer_triggers_retry(self):
        decider = ActionDecider()
        report = _make_report(
            outcome_reason=_outcome_reason(OutcomeReasonType.NO_ANSWER),
        )
        decisions = decider.decide(report)

        retry = [d for d in decisions if d.decision_type == ActionDecisionType.DURABLE_RETRY]
        assert len(retry) == 1
        assert retry[0].priority == DecisionPriority.MEDIUM

    @pytest.mark.asyncio
    async def test_hangup_triggers_retry(self):
        decider = ActionDecider()
        report = _make_report(
            outcome_reason=_outcome_reason(OutcomeReasonType.HANGUP),
        )
        decisions = decider.decide(report)

        retry = [d for d in decisions if d.decision_type == ActionDecisionType.DURABLE_RETRY]
        assert len(retry) == 1


# ══════════════════════════════════════════════════════════
# Test: NOT_NOW with interest → SECONDARY_OUTREACH
# ══════════════════════════════════════════════════════════

class TestNotNowOutreach:
    @pytest.mark.asyncio
    async def test_not_now_with_positive_signals(self):
        decider = ActionDecider()
        report = _make_report(
            signals=[_positive_signal("need")],
            outcome_reason=_outcome_reason(OutcomeReasonType.NOT_NOW),
        )
        decisions = decider.decide(report)

        outreach = [d for d in decisions if d.decision_type == ActionDecisionType.SECONDARY_OUTREACH]
        assert len(outreach) == 1

    @pytest.mark.asyncio
    async def test_not_now_without_signals_no_outreach(self):
        decider = ActionDecider()
        report = _make_report(
            signals=[],
            outcome_reason=_outcome_reason(OutcomeReasonType.NOT_NOW),
        )
        decisions = decider.decide(report)

        outreach = [d for d in decisions if d.decision_type == ActionDecisionType.SECONDARY_OUTREACH]
        assert len(outreach) == 0


# ══════════════════════════════════════════════════════════
# Test: Edge cases
# ══════════════════════════════════════════════════════════

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_report_defaults_to_crm_note(self):
        decider = ActionDecider()
        report = _make_report()
        decisions = decider.decide(report)
        assert len(decisions) >= 1
        types = {d.decision_type for d in decisions}
        assert ActionDecisionType.CRM_NOTE_ONLY in types

    @pytest.mark.asyncio
    async def test_generate_follow_up_actions(self):
        decider = ActionDecider()
        report = _make_report(signals=[_positive_signal("budget")])
        decisions = decider.decide(report)
        actions = decider.generate_follow_up_actions(decisions, report, "lead_1")
        assert len(actions) >= 1
        assert all(isinstance(a, FollowUpAction) for a in actions)

    @pytest.mark.asyncio
    async def test_generated_action_has_status_pending(self):
        decider = ActionDecider()
        report = _make_report(signals=[_positive_signal("need")])
        decisions = decider.decide(report)
        actions = decider.generate_follow_up_actions(decisions, report, "lead_1")
        for a in actions:
            assert a.status == FollowUpStatus.PENDING
