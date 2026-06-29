# byou/channels/voice/application/coordinator.py
"""VoiceCallCoordinator — orchestrates a voice call across pre/in/post phases.

Delegates to Core services via injected Protocol dependencies.
Never imports provider SDKs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Protocol

from byou.channels.voice.domain.state_machine import CallStateMachine, InvalidTransition
from byou.channels.voice.models import (
    AgentTurn,
    CallDirection,
    CallOutcome,
    CallSession,
    CallState,
    CallTurn,
    ChannelEvent,
    ChannelKind,
    FollowUpAction,
    HandoffRequest,
    PostCallReport,
    PreCallPackage,
    QualificationSignal,
)
from byou.channels.voice.ports import (
    ApprovalGateway,
    DurableExecutionGateway,
    HandoffPort,
    MemoryGateway,
    PostCallAnalysisPort,
    SLMGateway,
)

logger = logging.getLogger(__name__)


# ── Placeholder delegate protocols for Core services ──

class PreCallPreparationPort(Protocol):
    """Fills LeadContext with Research + Enrichment + Memory data."""

    async def prepare(self, lead_id: str) -> PreCallPackage: ...


class TurnExecutorPort(Protocol):
    """Generates AgentTurn from user turn + session context."""

    async def execute(
        self, session: CallSession, turn: CallTurn, history: list[CallTurn]
    ) -> AgentTurn: ...


# ── Coordinator ──────────────────────────────────────────

class VoiceCallCoordinator:
    """Orchestrates a single voice call end-to-end.

    This is the "brain" of the voice channel — it coordinates:
      - pre-call preparation (Core)
      - in-call turn execution (Core)
      - post-call analysis + memory distillation (Core)

    It does NOT:
      - handle provider webhooks (→ adapters)
      - manage audio / STT / TTS (→ provider)
      - execute CRM writes directly (→ CRMGateway)
    """

    def __init__(
        self,
        *,
        pre_call: PreCallPreparationPort | None = None,
        turn_executor: TurnExecutorPort | None = None,
        post_call: PostCallAnalysisPort | None = None,
        handoff: HandoffPort | None = None,
        approval: ApprovalGateway | None = None,
        durable: DurableExecutionGateway | None = None,
        memory: MemoryGateway | None = None,
        slm: SLMGateway | None = None,
    ) -> None:
        self._pre_call = pre_call
        self._turn_executor = turn_executor
        self._post_call = post_call
        self._handoff = handoff
        self._approval = approval
        self._durable = durable
        self._memory = memory
        self._slm = slm

    # ── Pre-call ────────────────────────────────────────

    async def prepare_call(self, lead_id: str) -> PreCallPackage:
        """Assemble a PreCallPackage via Core services."""
        if not self._pre_call:
            return PreCallPackage(
                lead={"lead_id": lead_id, "company_name": "", "contact_name": "", "phone": ""}
            )
        return await self._pre_call.prepare(lead_id)

    async def initiate_call(self, package: PreCallPackage) -> CallSession:
        """Create a CallSession and optionally start a durable run."""
        session = CallSession(
            session_id=_new_id("sess"),
            lead_id=package.lead.lead_id,
            channel=ChannelKind.VOICE,
            direction=CallDirection.OUTBOUND,
            state=CallState.PENDING,
            pre_call_package=package,
        )

        if self._durable:
            try:
                await self._durable.start_run(session.session_id, session.session_id)
            except Exception:
                logger.warning("Durable run start failed for %s", session.session_id)

        return session

    # ── In-call ─────────────────────────────────────────

    async def on_event(self, session: CallSession, event: ChannelEvent) -> ChannelEvent:
        """Handle a provider event: update session, maybe generate AgentTurn."""
        sm = CallStateMachine(direction=session.direction)
        # restore state
        sm._state = session.state  # noqa: SLF001

        try:
            match event.event_type:
                case "call_started":
                    sm.initiate()
                case "call_answered":
                    sm.answer()
                    session.answered_at = datetime.now(timezone.utc)
                case "call_ended":
                    sm.hangup()
                    session.ended_at = datetime.now(timezone.utc)
                    if session.answered_at:
                        session.duration_seconds = int(
                            (session.ended_at - session.answered_at).total_seconds()
                        )
                case _:
                    pass  # unknown events don't change state
        except InvalidTransition:
            logger.warning("Invalid transition for session %s", session.session_id)

        session.state = sm.state
        return event

    async def handle_turn(
        self, session: CallSession, turn: CallTurn, history: list[CallTurn]
    ) -> AgentTurn:
        """Process a user turn → AgentTurn.

        Approval check: if risk_level is high, request approval before responding.
        """
        if session.pre_call_package and session.pre_call_package.risk_level == "high":
            if self._approval:
                decision = await self._approval.request_approval(
                    scope="action",
                    context={"session_id": session.session_id, "turn_text": turn.text},
                    mode="demand",
                )
                if not decision.get("approved"):
                    return AgentTurn(
                        text="我需要确认一些信息，请稍等。",
                        emotion="neutral",
                        confidence=0.5,
                    )

        if not self._turn_executor:
            return AgentTurn(text="Agent turn executor not configured.")

        return await self._turn_executor.execute(session, turn, history)

    # ── Post-call ───────────────────────────────────────

    async def finalize_session(
        self, session: CallSession, transcript: list[CallTurn]
    ) -> PostCallReport:
        """End-of-call: analyze, extract signals, distill memory."""
        # 1. Extract qualification signals via SLM
        signals: list[QualificationSignal] = []
        if self._slm:
            try:
                raw_signals = await self._slm.extract_signals(transcript)
                for s in raw_signals:
                    signals.append(QualificationSignal(**s))
            except Exception:
                logger.exception("SLM signal extraction failed")

        # 2. Deep analysis via PostCallAnalyzer
        report = PostCallReport(
            session_id=session.session_id,
            lead_id=session.lead_id,
            qualification_signals=signals,
        )
        if self._post_call:
            try:
                report = await self._post_call.analyze(session, transcript)
            except Exception:
                logger.exception("Post-call analysis failed")

        # 3. Memory distillation
        if self._memory:
            try:
                await self._memory.distill_from_session(
                    session.session_id, report.model_dump()
                )
            except Exception:
                logger.exception("Memory distillation failed")

        # 4. Durable run completion
        if self._durable:
            try:
                await self._durable.record_stage_complete(
                    session.session_id, "post_call", {}, report.model_dump()
                )
            except Exception:
                logger.warning("Durable checkpoint failed")

        return report

    # ── Handoff ─────────────────────────────────────────

    async def evaluate_handoff(
        self, session: CallSession, request: HandoffRequest
    ) -> HandoffRequest:
        """Evaluate whether to transfer to human."""
        if self._handoff:
            return await self._handoff.evaluate(request)
        # Default: approve if user explicitly requested
        if request.reason == "user_request":
            request.approved = True
            request.target_queue = "sales"
        return request


# ── Helpers ─────────────────────────────────────────────

def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
