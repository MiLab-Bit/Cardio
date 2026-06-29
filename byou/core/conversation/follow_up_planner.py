# byou/core/conversation/follow_up_planner.py
"""FollowUpPlanner — converts PostCallReport signals into FollowUpActions.

Channel-neutral.  Routes actions to appropriate channels based on signal type
and lead preference.  Wraps actions in Durable Execution when needed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from byou.models.channel_contract import (
    BusinessOutcome,
    FollowUpAction,
    FollowUpStatus,
    OutcomeReason,
    OutcomeReasonType,
    PostCallReport,
    QAResult,
    QualificationSignal,
)

logger = logging.getLogger(__name__)


class FollowUpPlanner:
    """Plans follow-up actions from post-call structured data.

    Input: PostCallReport (signals, outcome, quality)
    Output: FollowUpAction[] — channel-routable, durable-ready.

    Does NOT depend on raw transcript.  Does NOT depend on voice.
    """

    # ── Action type routing ─────────────────────────────

    @staticmethod
    def _action_type_for_signal(signal_type: str) -> str:
        """Map signal type to preferred action channel."""
        routing = {
            "budget": "schedule_call",       # budget → call (sensitive)
            "authority": "schedule_call",    # authority → call (decision maker)
            "need": "send_email",            # need → email (product info)
            "timing": "crm_task",            # timing → CRM reminder
        }
        return routing.get(signal_type, "crm_task")

    @staticmethod
    def _priority_for_signal(signal_type: str, is_positive: bool | None) -> str:
        """Map signal to priority."""
        if not is_positive:
            return "low"
        if signal_type in ("budget", "authority"):
            return "high"
        return "medium"

    @staticmethod
    def _due_at_for_priority(priority: str) -> datetime | None:
        """Set due date based on priority."""
        offsets = {
            "high": 24,       # tomorrow
            "critical": 4,    # 4 hours
            "medium": 72,     # 3 days
            "low": 168,       # 7 days
        }
        hours = offsets.get(priority)
        if hours is None:
            return None
        return datetime.now(timezone.utc) + timedelta(hours=hours)

    # ── Main entry ─────────────────────────────────────

    def plan(
        self,
        report: PostCallReport,
        *,
        signals: list[QualificationSignal] | None = None,
        lead_id: str = "",
        session_id: str = "",
        include_retry: bool = True,
        include_review: bool = False,
    ) -> list[FollowUpAction]:
        """Generate follow-up actions from post-call signals.

        Args:
            report: PostCallReport with structured data
            signals: override subset of signals (default: report.qualification_signals)
            lead_id: explicit lead_id (default: report.lead_id)
            session_id: explicit session_id (default: report.session_id)
            include_retry: generate retry actions for failed/no_answer calls
            include_review: generate human review actions for low QA

        Returns:
            Sorted list of FollowUpAction (high priority first)
        """
        lead = lead_id or report.lead_id
        sess = session_id or report.session_id
        sigs = signals or report.qualification_signals

        actions: list[FollowUpAction] = []

        # ── Per-signal follow-up actions ──
        for sig in sigs:
            action = self._action_for_signal(sig, lead, sess)
            if action is not None:
                actions.append(action)

        # ── Outcome-based actions ──
        if include_retry:
            retry = self._action_for_outcome(report.outcome_reason, lead, sess)
            if retry is not None:
                actions.append(retry)

        # ── QA-based review ──
        if include_review:
            review = self._action_for_qa(report.qa_result, lead, sess)
            if review is not None:
                actions.append(review)

        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        actions.sort(key=lambda a: priority_order.get(a.priority, 2))

        return actions

    # ── Per-signal logic ───────────────────────────────

    def _action_for_signal(
        self,
        signal: QualificationSignal,
        lead_id: str,
        session_id: str,
    ) -> FollowUpAction | None:
        """Create a FollowUpAction for a single qualification signal."""
        if not signal.is_positive:
            return None

        action_type = self._action_type_for_signal(signal.signal_type)
        priority = self._priority_for_signal(signal.signal_type, signal.is_positive)
        due_at = self._due_at_for_priority(priority)

        topic = {
            "budget": "预算确认与方案报价",
            "authority": "联系决策人",
            "need": "发送产品方案",
            "timing": "跟进采购时间线",
        }.get(signal.signal_type, f"跟进: {signal.signal_type}")

        return FollowUpAction(
            action_id=f"fu_{session_id}_{signal.signal_type}_{signal.turn_id}",
            session_id=session_id,
            lead_id=lead_id,
            action_type=action_type,
            priority=priority,
            due_at=due_at,
            payload={
                "topic": topic,
                "signal_type": signal.signal_type,
                "signal_value": signal.extracted_value,
                "signal_confidence": signal.confidence,
                "bant_dimension": signal.bant_dimension,
            },
            status=FollowUpStatus.PENDING,
        )

    # ── Outcome-based logic ────────────────────────────

    def _action_for_outcome(
        self,
        outcome: OutcomeReason | None,
        lead_id: str,
        session_id: str,
    ) -> FollowUpAction | None:
        """Create retry/reconnect action based on outcome."""
        if outcome is None:
            return None

        retry_scenarios = {
            OutcomeReasonType.NO_ANSWER: ("durable_retry", "high", 4),
            OutcomeReasonType.HANGUP: ("durable_retry", "high", 4),
            OutcomeReasonType.NOT_NOW: ("schedule_call", "medium", 168),  # 7 days
            OutcomeReasonType.VOICEMAIL: ("send_email", "medium", 48),
        }

        config = retry_scenarios.get(outcome.primary_reason)
        if config is None:
            return None

        action_type, priority, hours = config
        due_at = datetime.now(timezone.utc) + timedelta(hours=hours)

        return FollowUpAction(
            action_id=f"fu_{session_id}_outcome_{outcome.primary_reason.value}",
            session_id=session_id,
            lead_id=lead_id,
            action_type=action_type,
            priority=priority,
            due_at=due_at,
            payload={
                "reason": outcome.primary_reason.value,
                "crm_summary": outcome.crm_summary[:200] if outcome.crm_summary else "",
                "retry_context": {
                    "previous_outcome": outcome.primary_reason.value,
                    "confidence": outcome.confidence,
                },
            },
            status=FollowUpStatus.PENDING,
        )

    # ── QA-based logic ─────────────────────────────────

    def _action_for_qa(
        self,
        qa: QAResult | None,
        lead_id: str,
        session_id: str,
    ) -> FollowUpAction | None:
        """Create human review action if QA score is low."""
        if qa is None:
            return None

        if qa.overall_score >= 0.5:
            return None  # good enough, no review needed

        priority = "critical" if qa.overall_score < 0.3 else "high"
        due_at = self._due_at_for_priority(priority)

        return FollowUpAction(
            action_id=f"fu_{session_id}_qa_review",
            session_id=session_id,
            lead_id=lead_id,
            action_type="human_review",
            priority=priority,
            due_at=due_at,
            payload={
                "qa_score": qa.overall_score,
                "qa_flags": qa.flags,
                "qa_suggestions": qa.suggestions,
                "dimensions": {
                    "opening": qa.opening_score,
                    "discovery": qa.discovery_score,
                    "objection_handling": qa.objection_handling_score,
                    "closing": qa.closing_score,
                    "compliance": qa.compliance_score,
                },
            },
            status=FollowUpStatus.PENDING,
        )
