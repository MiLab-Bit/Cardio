# byou/review/models.py
"""Unified Review Queue — shared models for identity + post-call review.

Single ReviewItem type, single queue, single resolver.
Source distinguishes identity review vs post-call review.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ReviewItemType(str, Enum):
    """All review item types — single enum, shared queue."""

    # ── Identity review (from Intake) ──
    IDENTITY_CONFLICT = "identity_conflict"        # VPID → UID ambiguous (≥2 candidates)
    AMBIGUOUS_MATCH = "ambiguous_match"            # match score 0.5-0.85
    NO_MATCH = "no_match"                          # no known identity
    CARD_VOICE_MISMATCH = "card_voice_mismatch"    # 名片名 ≠ 声纹匹配名
    MISSING_VOICEPRINT = "missing_voiceprint"      # no voiceprint on file
    MERGE_SUGGESTION = "merge_suggestion"          # two UIDs may be same person

    # ── Post-call review (from Core) ──
    QA_LOW_SCORE = "qa_low_score"                  # QAResult < 0.4
    QA_FLAGGED = "qa_flagged"                      # specific dimension flagged
    COMPLIANCE_VIOLATION = "compliance_violation"  # compliance score < threshold
    OBJECTION_ESCALATED = "objection_escalated"    # unresolved objection
    APPROVAL_REQUIRED = "approval_required"        # high-risk action pending
    HANDOFF_CONFLICT = "handoff_conflict"          # handoff evaluation ambiguous
    OUTCOME_UNCERTAIN = "outcome_uncertain"        # can't determine call outcome


class ReviewStatus(str, Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    SUPERSEDED = "superseded"  # replaced by newer review item


class ResolutionAction(str, Enum):
    """Actions available upon review resolution."""
    MERGE_UID = "merge_uid"                # merge two UIDs
    CONFIRM_NEW_UID = "confirm_new_uid"    # PersonCandidate → UID
    RE_ENROLL_VOICEPRINT = "re_enroll_voiceprint"
    REJECT_MATCH = "reject_match"          # dismiss false match
    APPROVE_TASK = "approve_task"
    REJECT_TASK = "reject_task"
    FLAG_FOR_RETRY = "flag_for_retry"
    UPDATE_CRM_NOTE = "update_crm_note"
    DISMISS = "dismiss"
    MANUAL_OVERRIDE = "manual_override"


class ReviewItem(BaseModel):
    """Single review item — works for any review source."""

    item_id: str = Field(default_factory=lambda: f"rev_{uuid4().hex[:12]}")
    item_type: ReviewItemType
    source: Literal["intake", "postcall", "handoff", "approval"]

    # Scope
    related_session_id: str
    related_uid: str | None = None
    related_qa_id: str | None = None
    related_approval_id: str | None = None
    related_followup_id: str | None = None

    # Priority & lifecycle
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    status: ReviewStatus = ReviewStatus.PENDING

    # Content
    title: str = ""
    description: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)  # EIDs

    # Resolution
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    resolution_action: ResolutionAction | None = None
    resolution_notes: str = ""
    resolution_writebacks: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-system writeback state: {merge_uid: done, crm_update: pending, ...}"
    )

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def mark_in_review(self, reviewer: str) -> None:
        self.status = ReviewStatus.IN_REVIEW
        self.resolved_by = reviewer
        self.updated_at = datetime.now(timezone.utc)

    def resolve(self, action: ResolutionAction, notes: str = "") -> None:
        self.status = ReviewStatus.RESOLVED
        self.resolution_action = action
        self.resolution_notes = notes
        self.resolved_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def dismiss(self, reason: str = "") -> None:
        self.status = ReviewStatus.DISMISSED
        self.resolution_notes = reason
        self.resolved_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


class ReviewQueueStats(BaseModel):
    """Queue-level statistics."""
    pending: int = 0
    in_review: int = 0
    resolved: int = 0
    dismissed: int = 0
    superseded: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)


class WritebackResult(BaseModel):
    """Result of a single resolution writeback."""
    target: str                           # "identity", "crm", "memory", "audit"
    action: str
    success: bool
    message: str = ""
    error: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
