# tests/test_phase3_follow_up_planner.py
"""Phase 3 FollowUpPlanner tests — action generation and routing."""

from __future__ import annotations

import pytest

from byou.core.conversation.follow_up_planner import FollowUpPlanner
from byou.models.channel_contract import (
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


def _make_report(
    session_id="sess_1",
    lead_id="lead_1",
    signals=None,
    outcome_reason=None,
    qa_result=None,
) -> PostCallReport:
    return PostCallReport(
        session_id=session_id,
        lead_id=lead_id,
        qualification_signals=signals or [],
        outcome_reason=outcome_reason,
        qa_result=qa_result,
        business_decision="follow_up",
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


def _outcome_reason(primary=OutcomeReasonType.QUALIFIED_NEED) -> OutcomeReason:
    return OutcomeReason(
        session_id="sess_1",
        lead_id="lead_1",
        primary_reason=primary,
    )


def _qa(score=0.8) -> QAResult:
    return QAResult(
        qa_id="qa_1",
        session_id="sess_1",
        lead_id="lead_1",
        overall_score=score,
    )


# ══════════════════════════════════════════════════════════
# Signal-based action generation
# ══════════════════════════════════════════════════════════

class TestSignalActions:
    def test_need_signal_generates_email(self):
        planner = FollowUpPlanner()
        report = _make_report(signals=[_positive_signal("need")])
        actions = planner.plan(report)
        assert len(actions) == 1
        assert actions[0].action_type == "send_email"

    def test_budget_signal_generates_call(self):
        planner = FollowUpPlanner()
        report = _make_report(signals=[_positive_signal("budget")])
        actions = planner.plan(report)
        assert len(actions) == 1
        assert actions[0].action_type == "schedule_call"

    def test_authority_signal_generates_call(self):
        planner = FollowUpPlanner()
        report = _make_report(signals=[_positive_signal("authority")])
        actions = planner.plan(report)
        assert len(actions) == 1
        assert actions[0].action_type == "schedule_call"

    def test_multiple_signals_generate_multiple_actions(self):
        planner = FollowUpPlanner()
        report = _make_report(signals=[
            _positive_signal("budget"),
            _positive_signal("need"),
            _positive_signal("timing"),
        ])
        actions = planner.plan(report)
        assert len(actions) == 3

    def test_negative_signal_no_action(self):
        planner = FollowUpPlanner()
        report = _make_report(signals=[
            QualificationSignal(
                session_id="sess_1", turn_id="t1", signal_type="budget",
                raw_text="no budget", confidence=0.3,
                is_positive=False, bant_dimension="budget",
            )
        ])
        actions = planner.plan(report)
        assert len(actions) == 0

    def test_no_signals_no_actions(self):
        planner = FollowUpPlanner()
        report = _make_report(signals=[])
        actions = planner.plan(report, include_retry=False, include_review=False)
        assert len(actions) == 0


# ══════════════════════════════════════════════════════════
# Outcome-based retry actions
# ══════════════════════════════════════════════════════════

class TestOutcomeActions:
    def test_no_answer_generates_retry(self):
        planner = FollowUpPlanner()
        report = _make_report(
            outcome_reason=_outcome_reason(OutcomeReasonType.NO_ANSWER),
        )
        actions = planner.plan(report, include_retry=True)
        retry = [a for a in actions if a.action_type == "durable_retry"]
        assert len(retry) == 1

    def test_hangup_generates_retry(self):
        planner = FollowUpPlanner()
        report = _make_report(
            outcome_reason=_outcome_reason(OutcomeReasonType.HANGUP),
        )
        actions = planner.plan(report, include_retry=True)
        retry = [a for a in actions if a.action_type == "durable_retry"]
        assert len(retry) == 1

    def test_not_now_generates_call(self):
        planner = FollowUpPlanner()
        report = _make_report(
            outcome_reason=_outcome_reason(OutcomeReasonType.NOT_NOW),
        )
        actions = planner.plan(report, include_retry=True)
        retry = [a for a in actions if a.action_type == "schedule_call"]
        assert len(retry) == 1

    def test_voicemail_generates_email(self):
        planner = FollowUpPlanner()
        report = _make_report(
            outcome_reason=_outcome_reason(OutcomeReasonType.VOICEMAIL),
        )
        actions = planner.plan(report, include_retry=True)
        retry = [a for a in actions if a.action_type == "send_email"]
        assert len(retry) == 1

    def test_qualified_no_retry(self):
        planner = FollowUpPlanner()
        report = _make_report(
            outcome_reason=_outcome_reason(OutcomeReasonType.QUALIFIED_NEED),
        )
        actions = planner.plan(report, include_retry=True)
        retry = [a for a in actions if a.action_type == "durable_retry"]
        assert len(retry) == 0

    def test_retry_can_be_disabled(self):
        planner = FollowUpPlanner()
        report = _make_report(
            outcome_reason=_outcome_reason(OutcomeReasonType.NO_ANSWER),
        )
        actions = planner.plan(report, include_retry=False)
        assert len(actions) == 0


# ══════════════════════════════════════════════════════════
# QA-based review actions
# ══════════════════════════════════════════════════════════

class TestQAReviewActions:
    def test_low_qa_generates_review(self):
        planner = FollowUpPlanner()
        report = _make_report(qa_result=_qa(0.25))
        actions = planner.plan(report, include_review=True)
        review = [a for a in actions if a.action_type == "human_review"]
        assert len(review) == 1
        assert review[0].priority == "critical"

    def test_medium_qa_generates_high_priority_review(self):
        planner = FollowUpPlanner()
        report = _make_report(qa_result=_qa(0.4))
        actions = planner.plan(report, include_review=True)
        review = [a for a in actions if a.action_type == "human_review"]
        assert len(review) == 1
        assert review[0].priority == "high"

    def test_good_qa_no_review(self):
        planner = FollowUpPlanner()
        report = _make_report(qa_result=_qa(0.8))
        actions = planner.plan(report, include_review=True)
        review = [a for a in actions if a.action_type == "human_review"]
        assert len(review) == 0

    def test_no_qa_no_review(self):
        planner = FollowUpPlanner()
        report = _make_report(qa_result=None)
        actions = planner.plan(report, include_review=True)
        review = [a for a in actions if a.action_type == "human_review"]
        assert len(review) == 0

    def test_review_can_be_disabled(self):
        planner = FollowUpPlanner()
        report = _make_report(qa_result=_qa(0.2))
        actions = planner.plan(report, include_review=False)
        review = [a for a in actions if a.action_type == "human_review"]
        assert len(review) == 0


# ══════════════════════════════════════════════════════════
# Priority ordering
# ══════════════════════════════════════════════════════════

class TestPriorityOrdering:
    def test_actions_sorted_by_priority(self):
        planner = FollowUpPlanner()
        report = _make_report(
            signals=[_positive_signal("budget"), _positive_signal("timing")],
            qa_result=_qa(0.25),
        )
        actions = planner.plan(report, include_review=True)
        assert len(actions) >= 2
        # critical (review) comes before high (budget call) before medium (timing)
        priorities = [a.priority for a in actions]
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for i in range(len(priorities) - 1):
            assert priority_order.get(priorities[i], 9) <= priority_order.get(priorities[i + 1], 9)

    def test_all_actions_have_status_pending(self):
        planner = FollowUpPlanner()
        report = _make_report(signals=[_positive_signal("budget")])
        actions = planner.plan(report)
        for a in actions:
            assert a.status == FollowUpStatus.PENDING

    def test_actions_have_due_at(self):
        planner = FollowUpPlanner()
        report = _make_report(
            signals=[_positive_signal("budget")],
            qa_result=_qa(0.25),
        )
        actions = planner.plan(report, include_review=True)
        for a in actions:
            assert a.due_at is not None, f"{a.action_type} missing due_at"

    def test_actions_have_valid_action_id(self):
        planner = FollowUpPlanner()
        report = _make_report(signals=[_positive_signal("need")])
        actions = planner.plan(report)
        for a in actions:
            assert a.action_id
            assert a.session_id == "sess_1"
            assert a.lead_id == "lead_1"
