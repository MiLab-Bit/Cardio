# byou/channels/voice/assembly.py
"""VoiceChannelAssembly — wires VoiceCallCoordinator to real Byou Core services.

This is the DI / factory that bridges the voice channel's Protocol interfaces
to the concrete Byou Core implementations.

Usage:
    from byou.channels.voice.assembly import VoiceChannelAssembly

    asm = VoiceChannelAssembly(orchestrator=orch, memory=mem, ...)
    coord = asm.build_coordinator()

    # Now coord.prepare_call(lead_id) goes through real Research + Enrichment + Memory
    # coord.handle_turn(...) goes through real Strategist
    # coord.finalize_session(...) goes through real SLM + Memory + CRM + Durable Exec
"""

from __future__ import annotations

import logging
from typing import Any

from byou.channels.voice.application.coordinator import VoiceCallCoordinator
from byou.channels.voice.application.policy import VoicePolicyEvaluator
from byou.channels.voice.application.postcall import PostCallIngestor
from byou.channels.voice.adapters.event_translator import VoiceEventTranslator
from byou.channels.voice.ports import (
    ApprovalGateway,
    CRMGateway,
    DurableExecutionGateway,
    MemoryGateway,
    SLMGateway,
)
from byou.core.conversation.pre_call import PreCallPreparation
from byou.core.conversation.turn_executor import TurnExecutor
from byou.core.conversation.post_call import PostCallAnalyzer

logger = logging.getLogger(__name__)


class VoiceChannelAssembly:
    """Dependency-injection assembly for the voice channel.

    Creates a fully wired VoiceCallCoordinator backed by real Byou Core
    services (Orchestrator, MemoryManager, SLMGateway, etc.) via Protocol
    adapters that map existing interfaces to the expected shape.
    """

    def __init__(
        self,
        *,
        orchestrator=None,       # byou.core.orchestrator.Orchestrator
        memory_manager=None,     # byou.memory.manager.MemoryManager
        slm_gateway=None,        # byou.tools.slm.gateway.SLMGateway
        durable_coordinator=None,  # byou.production.execution.DurableCoordinator
        approval_manager=None,   # byou.production.governance.ApprovalManager
        crm_tool=None,           # byou.tools.crm.client.CRMTool
    ) -> None:
        self._orchestrator = orchestrator
        self._memory_manager = memory_manager
        self._slm_gateway = slm_gateway
        self._durable_coordinator = durable_coordinator
        self._approval_manager = approval_manager
        self._crm_tool = crm_tool

        # Protocol adapters (lazy-built)
        self._memory_gw: MemoryGateway | None = None
        self._slm_gw: SLMGateway | None = None
        self._approval_gw: ApprovalGateway | None = None
        self._durable_gw: DurableExecutionGateway | None = None
        self._crm_gw: CRMGateway | None = None

    # ── Build ──────────────────────────────────────────

    def build_coordinator(self) -> VoiceCallCoordinator:
        """Build a fully wired VoiceCallCoordinator."""
        return VoiceCallCoordinator(
            pre_call=PreCallPreparation(
                orchestrator=self._orchestrator,
                memory=self.memory_gateway,
                crm=self.crm_gateway,
            ),
            turn_executor=TurnExecutor(
                orchestrator=self._orchestrator,
                slm=self.slm_gateway,
            ),
            post_call=PostCallAnalyzer(
                slm=self.slm_gateway,
                memory=self.memory_gateway,
                crm=self.crm_gateway,
                durable=self.durable_gateway,
            ),
            approval=self.approval_gateway,
            durable=self.durable_gateway,
            memory=self.memory_gateway,
            slm=self.slm_gateway,
        )

    def build_policy_evaluator(self) -> VoicePolicyEvaluator:
        return VoicePolicyEvaluator(
            memory=self.memory_gateway,
            crm=self.crm_gateway,
        )

    def build_event_translator(self) -> VoiceEventTranslator:
        return VoiceEventTranslator()

    # ── Protocol adapters (lazy, adapt real interfaces) ──

    @property
    def memory_gateway(self) -> MemoryGateway | None:
        if self._memory_gw is not None:
            return self._memory_gw
        if self._memory_manager is None:
            return None
        self._memory_gw = self._MemoryManagerAdapter(self._memory_manager)
        return self._memory_gw

    @property
    def slm_gateway(self) -> SLMGateway | None:
        if self._slm_gw is not None:
            return self._slm_gw
        if self._slm_gateway is None:
            return None
        self._slm_gw = self._SLMGatewayAdapter(self._slm_gateway)
        return self._slm_gw

    @property
    def approval_gateway(self) -> ApprovalGateway | None:
        if self._approval_gw is not None:
            return self._approval_gw
        if self._approval_manager is None:
            return None
        self._approval_gw = self._ApprovalManagerAdapter(self._approval_manager)
        return self._approval_gw

    @property
    def durable_gateway(self) -> DurableExecutionGateway | None:
        if self._durable_gw is not None:
            return self._durable_gw
        if self._durable_coordinator is None:
            return None
        self._durable_gw = self._DurableCoordinatorAdapter(self._durable_coordinator)
        return self._durable_gw

    @property
    def crm_gateway(self) -> CRMGateway | None:
        if self._crm_gw is not None:
            return self._crm_gw
        if self._crm_tool is None:
            return None
        self._crm_gw = self._CRMToolAdapter(self._crm_tool)
        return self._crm_gw

    # ── Adapter: MemoryManager → MemoryGateway Protocol ──

    class _MemoryManagerAdapter:
        """Adapts byou.memory.manager.MemoryManager to MemoryGateway."""

        def __init__(self, mm):
            self._mm = mm

        async def get_prior_interactions(self, lead_id: str) -> list[dict]:
            history = self._mm.history(lead_id, top_k=5)
            return [h.model_dump() if hasattr(h, "model_dump") else h for h in history]

        async def find_similar_cases(self, industry: str, scale: str) -> list[dict]:
            patterns = self._mm.lookup_patterns(industry=industry, scale=scale)
            return [p.model_dump() if hasattr(p, "model_dump") else {} for p in patterns]

        async def ingest_interaction(self, interaction: dict) -> None:
            self._mm.remember(interaction)

        async def distill_from_session(self, session_id: str, report: dict) -> None:
            self._mm.distill_strategy(
                strategy_json=report,
                company_context={},
                outcome=(report.get("business_outcome") or "unknown"),
            )

        async def distill_postcall(self, report: Any) -> None:
            """Store PostCallReport in memory."""
            self._mm.remember(report.model_dump() if hasattr(report, "model_dump") else report)

    # ── Adapter: SLMGateway → SLMGateway Protocol ────────

    class _SLMGatewayAdapter:
        """Adapts byou.tools.slm.gateway.SLMGateway to SLMGateway Protocol."""

        def __init__(self, slm):
            self._slm = slm

        async def extract_signals(self, turns: list) -> list[dict]:
            """Extract BANT signals from call turns."""
            if hasattr(turns[0], "text"):
                text = "\n".join(
                    f"[turn_{t.sequence}] {t.text}"
                    if hasattr(t, "sequence") else t.text
                    for t in turns
                )
            else:
                text = "\n".join(str(t) for t in turns)
            result = await self._slm.extract(text, capability="signal_extraction")
            return result.data if hasattr(result, "data") else []

        async def classify_intent(self, text: str) -> dict:
            result = await self._slm.classify(text)
            return result.data if hasattr(result, "data") else {"intent": "general"}

        async def analyze_sentiment(self, text: str) -> dict:
            result = await self._slm.score(text, capability="sentiment")
            return result.data if hasattr(result, "data") else {"sentiment": "neutral"}

    # ── Adapter: ApprovalManager → ApprovalGateway Protocol

    class _ApprovalManagerAdapter:
        """Adapts byou.production.governance.ApprovalManager to ApprovalGateway."""

        def __init__(self, am):
            self._am = am

        async def request_approval(
            self, scope: str, context: dict, mode: str = "demand",
        ) -> dict:
            from byou.production.governance.types import ApprovalMode, ApprovalScope
            try:
                sc = ApprovalScope(scope) if hasattr(ApprovalScope, scope) else ApprovalScope.ACTION  # noqa: E501
                md = ApprovalMode(mode) if hasattr(ApprovalMode, mode) else ApprovalMode.DEMAND  # noqa: E501
            except (ValueError, KeyError, AttributeError):
                sc = ApprovalScope.ACTION  # type: ignore[attr-defined]
                md = ApprovalMode.DEMAND  # type: ignore[attr-defined]
            result = await self._am.engine.request(
                scope=sc, mode=md, context=context,
            )
            return {"approved": result.approved, "request_id": result.id}

        async def check_approved(self, approval_id: str) -> bool:
            return await self._am.engine.is_approved(approval_id)

    # ── Adapter: DurableCoordinator → DurableExecutionGateway

    class _DurableCoordinatorAdapter:
        """Adapts DurableCoordinator to DurableExecutionGateway."""

        def __init__(self, dc):
            self._dc = dc

        async def start_run(self, run_id: str, trace_id: str) -> object:
            self._dc.create_run(run_id, trace_id)
            return self._dc.start_run(run_id)

        async def record_stage_complete(
            self, run_id: str, stage: str, input_snap: dict, output_snap: dict,
        ) -> None:
            self._dc.start_stage(run_id, stage)
            self._dc.complete_stage(run_id, stage, input_snap, output_snap)

        async def record_failure(self, run_id: str, error: str) -> None:
            self._dc.fail_run(run_id, error)

        async def save_checkpoint(self, run_id: str, state: dict) -> None:
            self._dc.start_stage(run_id, "checkpoint")
            self._dc.complete_stage(run_id, "checkpoint", input_snap=state, output_snap=state)

        async def build_recovery_plan(self, run_id: str) -> list[dict]:
            plan = self._dc.build_recovery_plan(run_id)
            return [a.model_dump() if hasattr(a, "model_dump") else a for a in plan.actions]

        async def schedule_retry(
            self, run_id: str, interval_minutes: int, payload: dict,
        ) -> None:
            # Delegate to cron / scheduler — placeholder
            logger.info("Retry scheduled: run=%s interval=%dmin", run_id, interval_minutes)

        async def create_run(
            self, run_id: str, trace_id: str, extra_context: dict | None = None,
            tags: dict | None = None,
        ) -> object:
            return self._dc.create_run(
                run_id=run_id, trace_id=trace_id,
                extra_context=extra_context, tags=tags,
            )

    # ── Adapter: CRMTool → CRMGateway ────────────────────

    class _CRMToolAdapter:
        """Adapts byou.tools.crm.client.CRMTool to CRMGateway."""

        def __init__(self, crm):
            self._crm = crm

        async def lookup_lead(self, lead_id: str) -> dict:
            result = await self._crm.get_contact(lead_id)
            return result if isinstance(result, dict) else {}

        async def create_task(self, task: dict) -> dict:
            return await self._crm.create_task(task)

        async def add_note(self, contact_id: str, note: str) -> dict:
            return await self._crm.add_note(contact_id, note)

        async def update_from_report(
            self, lead_id: str, signals: list,
        ) -> None:
            """Update CRM contact with post-call qualification signals."""
            for sig in signals:
                note = f"[{sig.signal_type}] {sig.raw_text[:200]}"
                await self._crm.add_note(lead_id, note)
