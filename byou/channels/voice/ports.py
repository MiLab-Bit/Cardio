# byou/channels/voice/ports.py
"""Abstract ports / protocols for voice channel.

All adapters implement these. Core depends only on these interfaces,
never on concrete adapters or provider SDKs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from byou.channels.voice.models import (
    AgentTurn,
    CallOutcome,
    CallSession,
    CallTurn,
    ChannelEvent,
    FollowUpAction,
    HandoffRequest,
    PostCallReport,
    PreCallPackage,
    QualificationSignal,
)


# ══════════════════════════════════════════════════════════
# Channel lifecycle
# ══════════════════════════════════════════════════════════

class ChannelPort(ABC):
    """Every channel adapter must implement this."""

    @abstractmethod
    async def on_session_start(self, session: CallSession) -> None: ...

    @abstractmethod
    async def on_session_end(self, session_id: str, outcome: CallOutcome) -> None: ...

    @abstractmethod
    async def ingest_event(self, event: ChannelEvent) -> ChannelEvent: ...

    @abstractmethod
    async def on_user_turn(self, session_id: str, turn: CallTurn) -> AgentTurn: ...

    @abstractmethod
    async def request_guidance(
        self, session_id: str, context: dict
    ) -> AgentTurn | None: ...

    @abstractmethod
    async def request_handoff(
        self, session_id: str, request: HandoffRequest
    ) -> HandoffRequest: ...

    @abstractmethod
    async def ingest_transcript(
        self, session_id: str, transcript: list[CallTurn]
    ) -> PostCallReport: ...


class OutboundChannelPort(ABC):
    """For channels that can initiate outbound communication."""

    @abstractmethod
    async def initiate_call(self, package: PreCallPackage) -> CallSession: ...

    @abstractmethod
    async def cancel_call(self, session_id: str, reason: str) -> None: ...


class InboundChannelEventPort(ABC):
    """For channels that receive events from external providers."""

    @abstractmethod
    async def handle_webhook(
        self, raw_payload: dict, headers: dict
    ) -> ChannelEvent: ...


class TranscriptIngestionPort(ABC):
    """Post-call transcript processing."""

    @abstractmethod
    async def ingest(self, session_id: str, turns: list[CallTurn]) -> PostCallReport: ...


class HandoffPort(ABC):
    """Handoff evaluation and execution."""

    @abstractmethod
    async def evaluate(self, request: HandoffRequest) -> HandoffRequest: ...

    @abstractmethod
    async def execute(self, request: HandoffRequest) -> HandoffRequest: ...


class PostCallAnalysisPort(ABC):
    """Post-call deep analysis."""

    @abstractmethod
    async def analyze(
        self, session: CallSession, turns: list[CallTurn]
    ) -> PostCallReport: ...


# ══════════════════════════════════════════════════════════
# Dependency injection protocols for Core services
# ══════════════════════════════════════════════════════════

class ApprovalGateway(Protocol):
    """Protocol for Core Governance / Approval Manager.

    Voice layer uses this to request approval for high-risk actions.
    Real implementation: byou.production.governance.ApprovalManager
    """

    async def request_approval(
        self, scope: str, context: dict, mode: str = "demand"
    ) -> dict: ...

    async def check_approved(self, approval_id: str) -> bool: ...


class DurableExecutionGateway(Protocol):
    """Protocol for Core Durable Execution.

    Voice layer uses this for call reliability: retry, checkpoint, recovery.
    Real implementation: byou.production.execution.DurableCoordinator
    """

    async def start_run(self, run_id: str, trace_id: str) -> object: ...

    async def record_stage_complete(
        self, run_id: str, stage: str, input_snap: dict, output_snap: dict
    ) -> None: ...

    async def record_failure(self, run_id: str, error: str) -> None: ...

    async def save_checkpoint(self, run_id: str, state: dict) -> None: ...

    async def build_recovery_plan(self, run_id: str) -> list[dict]: ...

    async def schedule_retry(
        self, run_id: str, interval_minutes: int, payload: dict
    ) -> None: ...


class MemoryGateway(Protocol):
    """Protocol for Core Memory.

    Voice layer uses this to store/retrieve interaction history and patterns.
    Real implementation: byou.memory.manager.MemoryManager
    """

    async def get_prior_interactions(self, lead_id: str) -> list[dict]: ...

    async def find_similar_cases(self, industry: str, scale: str) -> list[dict]: ...

    async def ingest_interaction(self, interaction: dict) -> None: ...

    async def distill_from_session(self, session_id: str, report: dict) -> None: ...

    async def distill_postcall(self, report: "PostCallReport") -> None: ...


class SLMGateway(Protocol):
    """Protocol for Small Language Model Gateway.

    Used for qualification signal extraction, intent classification,
    sentiment analysis — cheap, fast models (<1B params).
    Real implementation: byou.tools.slm.gateway.SLMGateway
    """

    async def extract_signals(self, turns: list[CallTurn] | None = None, *, text: str = "", signal_types: list[str] | None = None) -> list[dict]: ...

    async def classify_intent(self, text: str) -> dict: ...

    async def analyze_sentiment(self, text: str) -> dict: ...

    async def distill_postcall(self, report: PostCallReport) -> None: ...

    async def update_from_report(self, lead_id: str, signals: list[QualificationSignal]) -> None: ...


class CRMGateway(Protocol):
    """Protocol for CRM integration.

    Real implementation: byou.tools.crm.client.CRMTool
    """

    async def lookup_lead(self, lead_id: str) -> dict: ...

    async def create_task(self, task: dict) -> dict: ...

    async def add_note(self, contact_id: str, note: str) -> dict: ...

    async def update_from_report(self, lead_id: str, signals: list[QualificationSignal]) -> None: ...
