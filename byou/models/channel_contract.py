# byou/models/channel_contract.py
"""Channel-neutral contract models — shared across Voice, Email, IM, CRM channels.

Phase 3 v1: Extracted from channels/voice/models.py.  New Phase 3 objects added.
All models here have zero dependency on any specific channel implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════
# Enums
# ══════════════════════════════════════════════════════════

class ChannelKind(StrEnum):
    VOICE = "voice"
    EMAIL = "email"
    IM = "im"


class BusinessOutcome(StrEnum):
    QUALIFIED = "qualified"
    NOT_QUALIFIED = "not_qualified"
    FOLLOW_UP = "follow_up"
    OPTED_OUT = "opted_out"
    RESCHEDULE = "reschedule"


class FollowUpStatus(StrEnum):
    PENDING = "pending"
    EXECUTING = "executing"
    DONE = "done"
    FAILED = "failed"


class OutcomeReasonType(StrEnum):
    """Structured reason why a call/outreach ended with this outcome."""
    QUALIFIED_BUDGET = "qualified_budget"
    QUALIFIED_AUTHORITY = "qualified_authority"
    QUALIFIED_NEED = "qualified_need"
    QUALIFIED_TIMELINE = "qualified_timeline"
    NO_AUTHORITY = "no_authority"
    NOT_NOW = "not_now"
    WRONG_PERSON = "wrong_person"
    COMPETITOR_LOCK = "competitor_lock"
    NO_NEED = "no_need"
    NO_BUDGET = "no_budget"
    HANGUP = "hangup"
    NO_ANSWER = "no_answer"
    VOICEMAIL = "voicemail"
    OPTED_OUT = "opted_out"
    OTHER = "other"


class LearningSignalType(StrEnum):
    """Types of learnable patterns from a single interaction."""
    TALKING_POINT_EFFECTIVE = "talking_point_effective"
    TALKING_POINT_FAILED = "talking_point_failed"
    OBJECTION_OVERCOME = "objection_overcome"
    OBJECTION_UNRESOLVED = "objection_unresolved"
    TURN_FLOW_ANOMALY = "turn_flow_anomaly"
    CONVERSION_INDICATOR = "conversion_indicator"
    SENTIMENT_SHIFT = "sentiment_shift"


class ObjectionOutcome(StrEnum):
    OVERCOME = "overcome"
    ESCALATED = "escalated"
    UNRESOLVED = "unresolved"


class QAEvaluator(StrEnum):
    SLM_AUTO = "slm_auto"
    HUMAN_REVIEW = "human_review"
    HYBRID = "hybrid"


class ActionDecisionType(StrEnum):
    CRM_NOTE_ONLY = "crm_note_only"
    FOLLOW_UP_TASK = "follow_up_task"
    DURABLE_RETRY = "durable_retry"
    HUMAN_REVIEW = "human_review"
    APPROVAL_REQUIRED = "approval_required"
    NO_ACTION = "no_action"
    SECONDARY_OUTREACH = "secondary_outreach"


# ══════════════════════════════════════════════════════════
# Supporting types
# ══════════════════════════════════════════════════════════

class TalkingPoint(BaseModel):
    angle: str = ""
    script: str = ""
    key_message: str = ""


class BANTScore(BaseModel):
    budget: float = 0.0
    authority: float = 0.0
    need: float = 0.0
    timeline: float = 0.0


class SentimentPoint(BaseModel):
    turn: int
    sentiment: str  # positive|neutral|negative


# ══════════════════════════════════════════════════════════
# Channel-neutral core models
# ══════════════════════════════════════════════════════════

class LeadContext(BaseModel):
    """Pre-outreach customer context — assembled by Core, consumed by any channel."""
    lead_id: str
    company_name: str
    contact_name: str
    contact_title: str | None = None
    phone: str = ""

    company_intel: dict[str, Any] = Field(default_factory=dict)
    enrichment_profile: dict[str, Any] = Field(default_factory=dict)

    prior_interactions: list[dict[str, Any]] = Field(default_factory=list)
    similar_cases: list[dict[str, Any]] = Field(default_factory=list)

    crm_stage: str | None = None
    crm_notes: str | None = None

    source: str = "manual"
    campaign_id: str | None = None


class PreCallPackage(BaseModel):
    """Prepared outreach package — Core → Adapter to initiate contact."""
    lead: LeadContext

    call_objective: str = ""
    talking_points: list[TalkingPoint] = Field(default_factory=list)
    objection_handling: dict[str, str] = Field(default_factory=dict)

    risk_level: str = "low"
    requires_approval: bool = False

    approval_id: str | None = None
    approved_by: str | None = None

    call_timeout_seconds: int = 300
    max_retries: int = 3
    retry_interval_minutes: int = 30


class QualificationSignal(BaseModel):
    """Sales qualification signal extracted from an interaction by SLM Gateway."""
    session_id: str
    turn_id: str
    signal_type: str
    raw_text: str
    confidence: float = 0.0

    extracted_value: str | None = None
    is_positive: bool | None = None
    bant_dimension: str | None = None


class FollowUpAction(BaseModel):
    """Follow-up task — executable by any channel."""
    action_id: str
    session_id: str
    lead_id: str

    action_type: str = "crm_task"
    priority: str = "medium"
    due_at: datetime | None = None

    payload: dict[str, Any] = Field(default_factory=dict)

    status: FollowUpStatus = FollowUpStatus.PENDING
    executed_at: datetime | None = None
    executed_by: str | None = None
    error: str | None = None


class ChannelCapability(BaseModel):
    """Declared capabilities of a channel adapter."""
    channel: ChannelKind
    capabilities: list[str] = Field(default_factory=list)
    rate_limits: dict[str, int] = Field(default_factory=dict)
    supported_regions: list[str] = Field(default_factory=list)


class AgentTurn(BaseModel):
    """Core response to an interaction turn — what the agent should say/do next."""
    text: str
    actions: list[str] = Field(default_factory=list)
    emotion: str = "neutral"
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


# ══════════════════════════════════════════════════════════
# Phase 3: Post-Call Learning & Quality objects
# ══════════════════════════════════════════════════════════

class ObjectionPattern(BaseModel):
    """A detected objection pattern from a call — durable, distillable.

    Stored in Memory (Vector + Graph).  Enters Batch Distillation.
    Does NOT enter CRM.
    """
    pattern_id: str
    session_id: str
    lead_id: str

    objection_topic: str  # "价格"|"竞品"|"不需要"|"时间"|"已有供应商"|"功能不足"
    user_phrase: str = ""  # ≤200 chars, user's original words (truncated)
    agent_response: str = ""  # how the agent responded
    outcome: ObjectionOutcome = ObjectionOutcome.UNRESOLVED
    confidence: float = 0.0

    # Clustering anchors
    industry: str | None = None
    lead_role: str | None = None
    company_scale: str | None = None

    # Evidence (reference only — no full transcript)
    related_turns: list[str] = Field(default_factory=list)  # turn_id[]
    related_talking_point: str | None = None

    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LearningSignal(BaseModel):
    """A learnable pattern from a single interaction — durable, distillable.

    NOT a BANT qualification signal.  This is about "what did we learn about
    HOW to sell", not about WHAT the lead wants.

    Stored in Memory (Vector + Graph).  Enters Batch Distillation.
    Does NOT enter CRM.
    """
    signal_id: str
    session_id: str
    lead_id: str

    signal_type: LearningSignalType
    description: str = ""  # ≤200 chars, human-readable
    confidence: float = 0.0

    related_turns: list[str] = Field(default_factory=list)  # turn_id[]
    related_talking_point: str | None = None

    industry: str | None = None
    company_scale: str | None = None
    lead_role: str | None = None

    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OutcomeReason(BaseModel):
    """Structured reason for the call outcome — durable, CRM-facing.

    Stored in Audit Log (full) + CRM (summarized).
    """
    session_id: str
    lead_id: str

    primary_reason: OutcomeReasonType = OutcomeReasonType.OTHER
    secondary_reasons: list[OutcomeReasonType] = Field(default_factory=list)
    confidence: float = 0.0

    evidence_turns: list[str] = Field(default_factory=list)  # turn_id[] reference
    narrative: str = ""  # ≤300 chars, human-readable

    # CRM-facing (this is what goes into CRM note)
    crm_summary: str = ""  # ≤200 chars

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class QAResult(BaseModel):
    """Dimensioned quality assessment of a call — durable, audit-facing.

    Stored in Audit Log (immutable).  Low score → Review Queue.
    Does NOT enter Memory or CRM.
    """
    qa_id: str
    session_id: str
    lead_id: str

    # Dimension scores (each 0-1)
    opening_score: float = 1.0
    discovery_score: float = 1.0
    objection_handling_score: float = 1.0
    closing_score: float = 1.0
    compliance_score: float = 1.0
    tone_score: float = 1.0

    overall_score: float = 1.0  # weighted average

    flags: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)

    evaluator: QAEvaluator = QAEvaluator.SLM_AUTO
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MemorySummary(BaseModel):
    """Per-lead aggregated memory — cross-call, durable.

    Updates after each call with that lead.  Queried by PreCallPreparation
    to inform the next outreach.

    Stored in Memory (Graph).  Not in CRM.
    """
    lead_id: str
    total_calls: int = 0
    last_call_at: datetime | None = None

    # Latest BANT status
    budget_signal: str | None = None
    authority_signal: str | None = None
    need_signal: str | None = None
    timeline_signal: str | None = None

    # Aggregated intent
    overall_intent_score: float = 0.0
    intent_trend: str | None = None  # "rising" | "stable" | "declining"

    # Learned best approach
    best_talking_points: list[str] = Field(default_factory=list)
    common_objections: list[str] = Field(default_factory=list)
    objection_pattern_ids: list[str] = Field(default_factory=list)
    learning_signal_ids: list[str] = Field(default_factory=list)

    # Timing preference
    best_time_to_call: str | None = None
    best_channel: str | None = None

    # CRM sync hints
    recommended_crm_stage: str | None = None
    recommended_next_action: str | None = None

    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PostCallReport(BaseModel):
    """Full post-call analysis — Critic + SLM output.  Channel-neutral.

    Contains structured signals and quality assessment.
    Does NOT contain full transcript text.
    """
    session_id: str
    lead_id: str

    # Summary (human-readable, CRM-safe)
    summary: str = ""
    business_decision: str = ""  # qualified|not_qualified|follow_up
    recommended_next_step: str = ""

    # Structured signals
    qualification_signals: list[QualificationSignal] = Field(default_factory=list)
    objection_patterns: list[ObjectionPattern] = Field(default_factory=list)
    learning_signals: list[LearningSignal] = Field(default_factory=list)

    # Outcome
    outcome_reason: OutcomeReason | None = None
    bant_score: BANTScore = Field(default_factory=BANTScore)

    # Quality
    quality_score: float = 0.5
    qa_result: QAResult | None = None

    # Legacy fields (backward compat with Phase 1/2)
    key_takeaways: list[str] = Field(default_factory=list)
    strategy_adherence: float = 1.0
    deviation_points: list[str] = Field(default_factory=list)
    objections_raised: list[str] = Field(default_factory=list)
    objections_handled: list[str] = Field(default_factory=list)
    objections_escalated: list[str] = Field(default_factory=list)
    sentiment_trajectory: list[SentimentPoint] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)
    distilled_insights: list[str] = Field(default_factory=list)
    recommended_actions: list[FollowUpAction] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════
# Intake → Core canonical objects (Phase 3 v2)
# ══════════════════════════════════════════════════════════

class CanonicalTurn(BaseModel):
    """A single turn/speech segment — channel-neutral.

    CanonicalTurn.text is stored in Evidence Store via EID reference.
    The `text` field is a truncated preview (≤500 chars).
    Full transcript NEVER enters Memory or CRM.
    """
    tid: str
    participant_ref: str  # participant index ("P0", "P1", ...)
    text: str = ""        # truncated preview, ≤500 chars
    start_ms: int = 0
    end_ms: int = 0
    language: str = "zh"
    confidence: float = 1.0  # ASR confidence
    source_evidence: str = ""  # EID reference


class CanonicalParticipant(BaseModel):
    """A participant in a canonical session — channel-neutral."""
    participant_id: str  # "P0", "P1", ...
    role: str = "unknown"  # "visitor" | "bd_staff" | "other_staff"

    # Identity resolution status
    identity_status: str = "unknown"  # "confirmed" | "provisional" | "unknown"
    identity_ref: str | None = None   # UID (visitor) or BID (staff)
    identity_confidence: float = 0.0

    # Resolved info (from identity match)
    display_name: str = ""
    company: str = ""
    title: str = ""
    phone: str = ""
    email: str = ""

    # Evidence
    evidence_refs: list[str] = Field(default_factory=list)  # EIDs


class CanonicalSession(BaseModel):
    """A complete session — channel-neutral canonical input for Core.

    Produced by Intake (expo) or directly by channel adapters (voice/email).
    Consumed by Core Conversation.
    """
    sid: str
    session_type: str = "expo"  # "expo" | "phone" | "meeting" | "email" | "im"

    participants: list[CanonicalParticipant] = Field(default_factory=list)
    turns: list[CanonicalTurn] = Field(default_factory=list)

    # Metadata
    venue: dict[str, str] = Field(default_factory=dict)  # {location, event_name, booth_id, ...}
    recorded_at: datetime | None = None
    duration_ms: int = 0

    # Evidence
    evidence_refs: list[str] = Field(default_factory=list)  # EIDs
    review_required: bool = False

    # Provisional vs final
    is_provisional: bool = False
    supersedes_sid: str | None = None


class MemorySeed(BaseModel):
    """Intake → Memory: per-participant structured signals.

    NEVER contains raw transcript.  Built from extraction results.
    Consumed by Memory.ingest_signals().
    """
    uid: str  # UID of the participant
    sid: str  # SID of the session

    # Extracted from business card
    industry: str = ""
    company_name: str = ""
    person_name: str = ""
    title: str = ""
    phone: str = ""
    email: str = ""

    # Derived signals
    intent_hints: list[str] = Field(default_factory=list)
    first_impression: str = ""
    notes: str = ""  # ≤300 chars

    # Evidence
    source_evidence: list[str] = Field(default_factory=list)  # EIDs


class CRMSeed(BaseModel):
    """Intake → CRM: contact creation/update.

    Only actionable, CRM-ready data.  No internal analysis objects.
    """
    action: str = "create"  # "create" | "update" | "noop"
    uid: str

    contact_data: dict[str, Any] = Field(default_factory=dict)
    # {name, company, title, phone, email, source, industry, ...}

    notes: str = ""  # brief note about the encounter, ≤500 chars
    source: str = "expo_intake"

    # Evidence
    evidence_refs: list[str] = Field(default_factory=list)  # EIDs


class AuditEntry(BaseModel):
    """Intake → L4 Audit Log: immutable record.

    Stored permanently.  Contains evidence references but not full data.
    """
    audit_id: str
    event_type: str  # "session_created" | "identity_resolved" | "voiceprint_registered" | ...
    event_id: str    # SID or UID or VPID
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)  # EIDs

    decision_type: str = ""  # "auto_match" | "ambiguous" | "manual_override"
    requires_review: bool = False
