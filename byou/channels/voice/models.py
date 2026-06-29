# byou/channels/voice/models.py
"""Voice-specific data models.

Channel-neutral models are in byou.models.channel_contract.
This file only contains voice-only (or voice-first) types:
call state machine support, audio features, handoff, provider events.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# Re-export channel-neutral types for backward compatibility
from byou.models.channel_contract import (  # noqa: F401
    AgentTurn,
    BANTScore,
    BusinessOutcome,
    ChannelCapability,
    ChannelKind,
    FollowUpAction,
    FollowUpStatus,
    LearningSignal,
    LearningSignalType,
    LeadContext,
    MemorySummary,
    ObjectionOutcome,
    ObjectionPattern,
    OutcomeReason,
    OutcomeReasonType,
    PostCallReport,
    PreCallPackage,
    QAEvaluator,
    QAResult,
    QualificationSignal,
    SentimentPoint,
    TalkingPoint,
)


# ══════════════════════════════════════════════════════════
# Voice-specific enums
# ══════════════════════════════════════════════════════════

class CallDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallState(StrEnum):
    PENDING = "pending"
    RINGING = "ringing"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    FAILED = "failed"
    ENDED = "ended"


class Speaker(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class TechnicalOutcome(StrEnum):
    COMPLETED = "completed"
    NO_ANSWER = "no_answer"
    VOICEMAIL = "voicemail"
    BUSY = "busy"
    FAILED = "failed"
    TRANSFERRED = "transferred"
    USER_HANGUP = "user_hangup"


class HandoffReason(StrEnum):
    USER_REQUEST = "user_request"
    AGENT_UNABLE = "agent_unable"
    ESCALATION = "escalation"


# ══════════════════════════════════════════════════════════
# Voice-specific models
# ══════════════════════════════════════════════════════════

class AudioFeatures(BaseModel):
    """Voice-only metadata — Core may read but never requires."""
    speech_rate_wpm: float | None = None
    volume_mean: float | None = None
    pause_before_ms: int | None = None
    hesitation_count: int = 0
    emotion: str | None = None  # positive|neutral|negative|angry


class PreCallAudit(BaseModel):
    risk_level: str = "low"  # low|medium|high
    flags: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class CallSession(BaseModel):
    """Live call session state — shared between Voice Adapter and Core."""
    session_id: str
    lead_id: str
    channel: ChannelKind = ChannelKind.VOICE
    direction: CallDirection = CallDirection.OUTBOUND

    state: CallState = CallState.PENDING
    state_changed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Adapter-only: Core must not interpret this value
    provider_ref: str | None = None

    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    answered_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int = 0
    turn_count: int = 0

    technical_outcome: TechnicalOutcome | None = None
    business_outcome: BusinessOutcome | None = None
    outcome_detail: str | None = None

    pre_call_package: PreCallPackage | None = None


class CallTurn(BaseModel):
    """A single turn within a call session — voice-specific."""
    turn_id: str
    session_id: str
    sequence: int
    speaker: Speaker = Speaker.USER
    text: str
    audio_features: AudioFeatures | None = None

    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: int = 0

    # Adapter-only reference (audio chunk storage key etc.)
    audio_chunk_ref: str | None = None


class HandoffRequest(BaseModel):
    """Transfer-to-human request — evaluated by Core, executed by Adapter."""
    session_id: str
    reason: HandoffReason = HandoffReason.USER_REQUEST
    context: str = ""
    priority: str = "normal"

    # Core decision
    approved: bool = False
    target_queue: str | None = None
    handoff_notes: str | None = None

    # Adapter result
    transferred: bool = False
    transfer_target: str | None = None
    transfer_error: str | None = None


class CallOutcome(BaseModel):
    """Voice call result."""
    session_id: str
    lead_id: str
    technical_outcome: TechnicalOutcome = TechnicalOutcome.COMPLETED
    business_outcome: BusinessOutcome = BusinessOutcome.FOLLOW_UP

    intent_score: float = 0.0
    next_step: str | None = None
    next_step_detail: str | None = None


class ChannelEvent(BaseModel):
    """Provider-independent event emitted by an adapter into Core."""
    session_id: str
    event_type: str
    channel: ChannelKind = ChannelKind.VOICE
    direction: CallDirection = CallDirection.OUTBOUND
    provider_ref: str | None = None

    turn: CallTurn | None = None
    session: CallSession | None = None
    handoff: HandoffRequest | None = None
    outcome: CallOutcome | None = None
    error: str | None = None

    raw_meta: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"extra": "forbid"}
