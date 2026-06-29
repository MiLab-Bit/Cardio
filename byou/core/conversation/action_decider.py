# byou/core/conversation/action_decider.py
"""ActionDecider — post-call decision engine: what to do after a call ends.

Inputs:
  - CallOutcome (technical + business outcome)
  - QAResult (dimensioned quality assessment)
  - OutcomeReason (structured reason for outcome)
  - QualificationSignal[] (BANT signals)

Outputs:
  - ActionDecision[] — one per required action, with type + priority

Decision matrix (Phase 3 v1: rule-based, v2: ML-enhanced).
Never depends on raw transcript or voice-specific payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from byou.models.channel_contract import (
    ActionDecisionType,
    BusinessOutcome,
    FollowUpAction,
    FollowUpStatus,
    OutcomeReason,
    OutcomeReasonType,
    PostCallReport,
    QAResult,
    QualificationSignal,
)


class DecisionPriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ActionDecision:
    """Single post-call action decision."""
    decision_type: ActionDecisionType
    priority: DecisionPriority = DecisionPriority.MEDIUM
    reason: str = ""
    follow_up: FollowUpAction | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Decision matrix ────────────────────────────────────────

class ActionDecider:
    """Post-call action decision engine.

    Rules (v1, priority-ordered):
      1. QAResult < 0.3  → HUMAN_REVIEW
      2. Compliance flag  → HUMAN_REVIEW (regardless of QAResult)
      3. High risk level   → APPROVAL_REQUIRED (if positive signals)
      4. Positive signals  → FOLLOW_UP_TASK + CRM_NOTE_ONLY
      5. No answer / No signal → CRM_NOTE_ONLY (no follow-up)
      6. Technical failure → DURABLE_RETRY
      7. Not_now outcome   → SECONDARY_OUTREACH (schedule follow-up)
      8. Unresolved objection → CRM_NOTE_ONLY + flag for review
    """

    # Order matters: first match wins
    _RULES: list[tuple[str, Any]] = [
        ("low_qa", lambda s: _low_qa(s)),
        ("compliance_flag", lambda s: _compliance_flag(s)),
        ("high_risk_positive", lambda s: _high_risk_positive(s)),
        ("positive_signals", lambda s: _positive_signals(s)),
        ("no_answer", lambda s: _no_answer(s)),
        ("technical_failure", lambda s: _technical_failure(s)),
        ("not_now_interest", lambda s: _not_now_interest(s)),
        ("unresolved_objections", lambda s: _unresolved_objections(s)),
    ]

    def decide(
        self,
        report: PostCallReport,
        *,
        risk_level: str = "low",
        approval_required: bool = False,
        signals: list[QualificationSignal] | None = None,
    ) -> list[ActionDecision]:
        """Evaluate post-call state and produce action decision list.

        Returns at least one decision (at minimum: CRM_NOTE_ONLY).
        Each decision may carry a FollowUpAction for execution.
        """
        state = _DecisionState(
            report=report,
            risk_level=risk_level,
            approval_required=approval_required,
            signals=signals or report.qualification_signals,
        )

        decisions: list[ActionDecision] = []

        for name, check_fn in self._RULES:
            result = check_fn(state)
            if result is not None:
                decisions.append(result)

        # Fallback: always write a CRM note
        if not any(d.decision_type == ActionDecisionType.CRM_NOTE_ONLY for d in decisions):
            decisions.append(ActionDecision(
                decision_type=ActionDecisionType.CRM_NOTE_ONLY,
                priority=DecisionPriority.LOW,
                reason="Default CRM note for every completed call",
            ))

        return decisions

    # ── Plan helpers ───────────────────────────────────

    def generate_follow_up_actions(
        self,
        decisions: list[ActionDecision],
        report: PostCallReport,
        lead_id: str,
    ) -> list[FollowUpAction]:
        """Generate executable FollowUpAction list from decisions.

        Call this after decide().  Each FOLLOW_UP_TASK / SECONDARY_OUTREACH
        decision produces a FollowUpAction.
        """
        actions: list[FollowUpAction] = []

        for d in decisions:
            action = _decision_to_action(d, report, lead_id)
            if action is not None:
                actions.append(action)

        return actions


# ── Rule checks (internal) ──────────────────────────────────

@dataclass
class _DecisionState:
    report: PostCallReport
    risk_level: str
    approval_required: bool
    signals: list[QualificationSignal]


def _low_qa(s: _DecisionState) -> ActionDecision | None:
    qa = s.report.qa_result
    if qa is None:
        return None
    if qa.overall_score < 0.3:
        return ActionDecision(
            decision_type=ActionDecisionType.HUMAN_REVIEW,
            priority=DecisionPriority.CRITICAL,
            reason=f"QA score too low ({qa.overall_score:.2f})",
        )
    if qa.overall_score < 0.5:
        return ActionDecision(
            decision_type=ActionDecisionType.HUMAN_REVIEW,
            priority=DecisionPriority.MEDIUM,
            reason=f"QA score borderline ({qa.overall_score:.2f})",
        )
    return None


def _compliance_flag(s: _DecisionState) -> ActionDecision | None:
    qa = s.report.qa_result
    if qa is None:
        return None
    if any("compliance" in f.lower() for f in qa.flags):
        return ActionDecision(
            decision_type=ActionDecisionType.HUMAN_REVIEW,
            priority=DecisionPriority.CRITICAL,
            reason="Compliance flag raised — requires human review",
        )
    return None


def _high_risk_positive(s: _DecisionState) -> ActionDecision | None:
    if s.risk_level != "high":
        return None
    positive = [sig for sig in s.signals if sig.is_positive]
    if not positive:
        return None
    return ActionDecision(
        decision_type=ActionDecisionType.APPROVAL_REQUIRED,
        priority=DecisionPriority.HIGH,
        reason=f"High-risk lead with {len(positive)} positive signals",
    )


def _positive_signals(s: _DecisionState) -> ActionDecision | None:
    positive = [sig for sig in s.signals if sig.is_positive]
    if not positive:
        return None
    high_prio = [sig for sig in positive if sig.signal_type in ("budget", "need")]
    priority = DecisionPriority.HIGH if high_prio else DecisionPriority.MEDIUM
    return ActionDecision(
        decision_type=ActionDecisionType.FOLLOW_UP_TASK,
        priority=priority,
        reason=f"{len(positive)} positive qualification signals detected",
    )


def _no_answer(s: _DecisionState) -> ActionDecision | None:
    reason = s.report.outcome_reason
    if reason is None:
        return None
    if reason.primary_reason == OutcomeReasonType.NO_ANSWER:
        return ActionDecision(
            decision_type=ActionDecisionType.DURABLE_RETRY,
            priority=DecisionPriority.MEDIUM,
            reason="No answer — schedule retry",
        )
    return None


def _technical_failure(s: _DecisionState) -> ActionDecision | None:
    reason = s.report.outcome_reason
    if reason is None:
        return None
    if reason.primary_reason == OutcomeReasonType.HANGUP:
        return ActionDecision(
            decision_type=ActionDecisionType.DURABLE_RETRY,
            priority=DecisionPriority.MEDIUM,
            reason="Technical failure — durable retry",
        )
    return None


def _not_now_interest(s: _DecisionState) -> ActionDecision | None:
    reason = s.report.outcome_reason
    if reason is None:
        return None
    if reason.primary_reason == OutcomeReasonType.NOT_NOW:
        positive = [sig for sig in s.signals if sig.is_positive]
        if positive:
            return ActionDecision(
                decision_type=ActionDecisionType.SECONDARY_OUTREACH,
                priority=DecisionPriority.MEDIUM,
                reason="Not now but showed interest — schedule secondary outreach",
            )
    return None


def _unresolved_objections(s: _DecisionState) -> ActionDecision | None:
    unresolved = [p for p in s.report.objection_patterns
                  if p.outcome.value == "unresolved"]
    if not unresolved:
        return None
    topics = list({p.objection_topic for p in unresolved})
    return ActionDecision(
        decision_type=ActionDecisionType.CRM_NOTE_ONLY,
        priority=DecisionPriority.LOW,
        reason=f"Unresolved objections: {', '.join(topics)}",
        metadata={"unresolved_topics": topics},
    )


# ── Decision → FollowUpAction ──────────────────────────────

def _decision_to_action(
    d: ActionDecision, report: PostCallReport, lead_id: str,
) -> FollowUpAction | None:
    """Map a decision to executable FollowUpAction."""

    action_type_map = {
        ActionDecisionType.FOLLOW_UP_TASK: "schedule_call",
        ActionDecisionType.SECONDARY_OUTREACH: "schedule_call",
        ActionDecisionType.DURABLE_RETRY: "durable_retry",
        ActionDecisionType.HUMAN_REVIEW: "human_review",
    }

    action_type = action_type_map.get(d.decision_type)
    if action_type is None:
        return None

    priority_map = {
        DecisionPriority.CRITICAL: "critical",
        DecisionPriority.HIGH: "high",
        DecisionPriority.MEDIUM: "medium",
        DecisionPriority.LOW: "low",
    }

    return FollowUpAction(
        action_id=f"{d.decision_type.value}_{report.session_id}",
        session_id=report.session_id,
        lead_id=lead_id,
        action_type=action_type,
        priority=priority_map.get(d.priority, "medium"),
        payload={
            "reason": d.reason,
            "decision_type": d.decision_type.value,
            "metadata": d.metadata,
        },
        status=FollowUpStatus.PENDING,
    )
