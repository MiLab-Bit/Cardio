# byou/channels/voice/application/postcall.py
"""PostCallIngestor — end-of-call transcript processing pipeline.

Transcript → SLM signal extraction → PostCallReport → Memory distillation.

Does NOT store raw audio or full transcripts in Memory.
Only structured signals and distilled insights enter the memory graph.
"""

from __future__ import annotations

import logging

from byou.channels.voice.models import (
    CallSession,
    CallTurn,
    FollowUpAction,
    PostCallReport,
    QualificationSignal,
)
from byou.channels.voice.ports import (
    HandoffPort,
    MemoryGateway,
    PostCallAnalysisPort,
    SLMGateway,
)

logger = logging.getLogger(__name__)


class PostCallIngestor:
    """Orchestrates post-call data processing.

    Pipeline:
      1. SLM Gateway: extract QualificationSignals
      2. PostCallAnalyzer: deep analysis → PostCallReport
      3. Memory Gateway: distill insights into memory graph
      4. Generate FollowUpActions

    Key design constraint: raw transcript never enters Memory directly.
    """

    def __init__(
        self,
        *,
        slm: SLMGateway | None = None,
        analyzer: PostCallAnalysisPort | None = None,
        memory: MemoryGateway | None = None,
        handoff: HandoffPort | None = None,
    ) -> None:
        self._slm = slm
        self._analyzer = analyzer
        self._memory = memory
        self._handoff = handoff

    async def ingest(
        self, session: CallSession, transcript: list[CallTurn]
    ) -> PostCallReport:
        """Run the full post-call ingestion pipeline."""

        # ── Step 1: Extract qualification signals via SLM ──
        signals = await self._extract_signals(session.session_id, transcript)

        # ── Step 2: Deep analysis ──
        report = await self._analyze(session, transcript, signals)

        # ── Step 3: Memory distillation ──
        await self._distill(session.session_id, report)

        # ── Step 4: Generate follow-up actions ──
        report.recommended_actions = await self._generate_actions(session, report)

        return report

    # ── Internal steps ──────────────────────────────────

    async def _extract_signals(
        self, session_id: str, transcript: list[CallTurn]
    ) -> list[QualificationSignal]:
        if not self._slm:
            logger.debug("No SLM gateway configured, skipping signal extraction")
            return []

        try:
            raw = await self._slm.extract_signals(transcript)
            return [
                QualificationSignal(session_id=session_id, **s)
                for s in raw
            ]
        except Exception:
            logger.exception("SLM signal extraction failed")
            return []

    async def _analyze(
        self,
        session: CallSession,
        transcript: list[CallTurn],
        signals: list[QualificationSignal],
    ) -> PostCallReport:
        if self._analyzer:
            try:
                return await self._analyzer.analyze(session, transcript)
            except Exception:
                logger.exception("PostCallAnalyzer failed")

        # Fallback: minimal report
        return PostCallReport(
            session_id=session.session_id,
            lead_id=session.lead_id,
            qualification_signals=signals,
            summary=f"Call {session.session_id}: {len(transcript)} turns, {session.duration_seconds}s",
        )

    async def _distill(self, session_id: str, report: PostCallReport) -> None:
        if not self._memory:
            return
        try:
            await self._memory.distill_from_session(session_id, report.model_dump())
        except Exception:
            logger.exception("Memory distillation failed for %s", session_id)

    async def _generate_actions(
        self, session: CallSession, report: PostCallReport
    ) -> list[FollowUpAction]:
        """Generate follow-up actions from report insights."""
        actions: list[FollowUpAction] = []

        # Basic: always add a CRM note action if outcome suggests follow-up
        if report.bant_score.need > 0.5:
            actions.append(
                FollowUpAction(
                    action_id=f"fa_{session.session_id}_crm",
                    session_id=session.session_id,
                    lead_id=session.lead_id,
                    action_type="crm_task",
                    priority="high",
                    payload={
                        "task": "follow_up",
                        "notes": report.summary[:500],
                        "key_takeaways": report.key_takeaways,
                    },
                )
            )

        return actions
