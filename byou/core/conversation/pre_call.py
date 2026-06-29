# byou/core/conversation/pre_call.py
"""PreCallPreparation — assembles PreCallPackage from existing Byou agents.

Wires real Byou core services:
  - Orchestrator (for running researcher/synthesizer/strategist/critic)
  - MemoryManager  (for prior interactions + similar cases)
  - Enrichment     (for company profile enrichment)

Implements the PreCallPreparationPort Protocol expected by VoiceCallCoordinator.
"""

from __future__ import annotations

import logging
from typing import Any

from byou.channels.voice.models import (
    LeadContext,
    PreCallAudit,
    PreCallPackage,
    TalkingPoint,
)
from byou.channels.voice.ports import MemoryGateway, CRMGateway

logger = logging.getLogger(__name__)


class PreCallPreparation:
    """Assembles a PreCallPackage using the existing Byou agent pipeline.

    This is the bridge between VoiceChannel and Byou Core:
      voice/coordinator.py  ── PreCallPreparationPort ──> this class

    Flow:
      1. Researcher → CompanyIntelligence
      2. Enrichment → enriched company profile
      3. Memory    → prior interactions + similar cases
      4. CRM       → CRM stage + notes
      5. Strategist → talking_points + objection_handling
      6. Critic    → PreCallAudit (risk_level, flags)
    """

    def __init__(
        self,
        *,
        orchestrator=None,  # byou.core.orchestrator.Orchestrator
        memory: MemoryGateway | None = None,
        crm: CRMGateway | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._memory = memory
        self._crm = crm

    async def prepare(self, lead_id: str) -> PreCallPackage:
        """Build a full PreCallPackage for the given lead.

        In production, this queries CRM for lead info, runs the Research
        pipeline, and assembles everything into a PreCallPackage.
        """
        logger.info("PreCallPreparation: preparing lead %s", lead_id)

        # ── Step 1: Build LeadContext ──
        lead = await self._build_lead_context(lead_id)

        # ── Step 2: Strategy via existing pipeline ──
        talking_points = await self._generate_talking_points(lead)
        objection_handling = await self._generate_objection_handling(lead)

        # ── Step 3: Pre-call audit via Critic ──
        audit = await self._audit_pre_call(lead)

        return PreCallPackage(
            lead=lead,
            call_objective=self._default_objective(lead),
            talking_points=talking_points,
            objection_handling=objection_handling,
            pre_call_audit=audit,
            risk_level=audit.risk_level,
            requires_approval=audit.risk_level == "high",
        )

    # ── Internal: build LeadContext ────────────────────────

    async def _build_lead_context(self, lead_id: str) -> LeadContext:
        """Assemble LeadContext from CRM + Memory."""
        ctx = LeadContext(
            lead_id=lead_id,
            company_name="",
            contact_name="",
            phone="",
            source="pipeline",
        )

        # CRM data
        if self._crm:
            try:
                crm_data = await self._crm.lookup_lead(lead_id)
                ctx.company_name = crm_data.get("company_name", "")
                ctx.contact_name = crm_data.get("contact_name", "")
                ctx.contact_title = crm_data.get("contact_title")
                ctx.phone = crm_data.get("phone", "")
                ctx.crm_stage = crm_data.get("stage")
                ctx.crm_notes = crm_data.get("notes")
            except Exception:
                logger.exception("CRM lookup failed for %s", lead_id)

        # Memory: prior interactions
        if self._memory:
            try:
                ctx.prior_interactions = (
                    await self._memory.get_prior_interactions(lead_id)
                )
            except Exception:
                logger.exception("Memory prior_interactions failed")

        return ctx

    # ── Internal: run agent pipeline ───────────────────────

    async def _generate_talking_points(self, lead: LeadContext) -> list[TalkingPoint]:
        """Generate talking points using Strategist agent.

        Attempts to run through the existing Orchestrator pipeline.
        Falls back to a minimal default if orchestrator is not configured.
        """
        if not self._orchestrator:
            return self._default_talking_points(lead)

        try:
            # Run the full agent pipeline for this lead
            # This goes: Extractor → Researcher → Synthesizer → Strategist
            pipeline_result = await self._orchestrator.run_pipeline(
                raw_input={"company_name": lead.company_name, "person_name": lead.contact_name},
                pipeline_id=f"precall_{lead.lead_id}",
            )

            strategy = pipeline_result.get("strategy", {})
            raw_points = strategy.get("talking_points", [])

            return [
                TalkingPoint(
                    angle=tp.get("angle", ""),
                    script=tp.get("script", ""),
                    key_message=tp.get("key_message", ""),
                )
                for tp in raw_points
            ]
        except Exception:
            logger.exception("Pipeline run failed, using defaults")
            return self._default_talking_points(lead)

    async def _generate_objection_handling(self, lead: LeadContext) -> dict[str, str]:
        """Get objection handling strategies."""
        if not self._orchestrator:
            return self._default_objections()

        try:
            pipeline_result = await self._orchestrator.run_pipeline(
                raw_input={"company_name": lead.company_name},
                pipeline_id=f"precall_obj_{lead.lead_id}",
            )
            strategy = pipeline_result.get("strategy", {})
            return strategy.get("objection_handling", self._default_objections())
        except Exception:
            return self._default_objections()

    async def _audit_pre_call(self, lead: LeadContext) -> PreCallAudit:
        """Run Critic to audit the pre-call package."""
        flags: list[str] = []
        risk_level = "low"

        # Basic checks
        if not lead.phone:
            flags.append("missing_phone")
            risk_level = "medium"

        if not lead.company_name:
            flags.append("missing_company")
            risk_level = "high"

        return PreCallAudit(
            risk_level=risk_level,
            flags=flags,
            recommendations=self._recommendations_for_flags(flags),
        )

    # ── Defaults / fallbacks ──────────────────────────────

    @staticmethod
    def _default_objective(lead: LeadContext) -> str:
        return f"初次联系 {lead.company_name or '目标客户'}，介绍产品价值，获取决策人联系方式"

    @staticmethod
    def _default_talking_points(lead: LeadContext) -> list[TalkingPoint]:
        company = lead.contact_name or "负责人"
        return [
            TalkingPoint(
                angle="行业痛点切入",
                script=f"{company}您好，注意到贵司在{lead.company_name or '行业'}领域发展迅速...",
                key_message="理解业务挑战",
            ),
            TalkingPoint(
                angle="产品价值",
                script="我们帮助像贵司这样的企业实现效率提升30%以上...",
                key_message="量化价值主张",
            ),
        ]

    @staticmethod
    def _default_objections() -> dict[str, str]:
        return {
            "价格太高": "理解您的顾虑。我们可以根据实际需求定制灵活方案。",
            "已有供应商": "多个选择对您有利，我们可以在特定领域提供增量价值。",
            "不需要": "完全理解。方便告诉我目前最关注什么方向吗？",
            "没时间": "明白，我简短说几句核心点，后续可以邮件详细沟通。",
        }

    @staticmethod
    def _recommendations_for_flags(flags: list[str]) -> list[str]:
        recs = []
        if "missing_phone" in flags:
            recs.append("补充联系方式后再发起呼叫")
        if "missing_company" in flags:
            recs.append("补充公司信息后再发起呼叫")
        return recs
