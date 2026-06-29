# byou/intake/publisher.py
"""Intake Publisher — distribute canonical results to downstream gateways.

Receives assembled results from CanonicalSessionAssembler and dispatches:
  - MemorySeed[] → Memory gateway
  - CRMSeed[] → CRM gateway
  - AuditEntry[] → Audit Log
  - Review flags → Review Queue
  - CanonicalSession → Core conversation (via MessageBus or direct call)
"""

from __future__ import annotations

import logging
from typing import Any

from byou.intake.models import IntakeProcessingResult
from byou.models.channel_contract import (
    AuditEntry,
    CRMSeed,
    CanonicalSession,
    MemorySeed,
)
from byou.intake.types import (
    MemoryGatewayProtocol,
    CRMGatewayProtocol,
    AuditGatewayProtocol,
    ReviewGatewayProtocol,
    ConversationGatewayProtocol,
)

logger = logging.getLogger(__name__)


class IntakePublisher:
    """Publish Intake results to downstream systems.

    All gateways are injected — publisher has no hard dependencies.
    Missing gateway → graceful degrade (log warning, continue).
    """

    def __init__(
        self,
        memory_gateway: MemoryGatewayProtocol | None = None,
        crm_gateway: CRMGatewayProtocol | None = None,
        audit_gateway: AuditGatewayProtocol | None = None,
        review_gateway: ReviewGatewayProtocol | None = None,
        conversation_gateway: ConversationGatewayProtocol | None = None,
    ):
        self._memory = memory_gateway
        self._crm = crm_gateway
        self._audit = audit_gateway
        self._review = review_gateway
        self._conversation = conversation_gateway

    async def publish(
        self,
        *,
        session: CanonicalSession,
        memory_seeds: list[MemorySeed],
        crm_seeds: list[CRMSeed],
        audit_entries: list[AuditEntry],
        review_required: bool = False,
    ) -> IntakeProcessingResult:
        """Publish all assembled results to downstream systems.

        Returns IntakeProcessingResult with success/failure per pipeline.
        """
        errors: list[str] = []
        review_flags: list[str] = []

        # ── Memory ──────────────────────────────────────
        if memory_seeds and self._memory:
            for seed in memory_seeds:
                try:
                    if hasattr(self._memory, "ingest_signals"):
                        await self._memory.ingest_signals(seed.model_dump())
                    elif hasattr(self._memory, "ingest"):
                        await self._memory.ingest(seed)
                except Exception as e:
                    msg = f"Memory publish failed for {seed.uid}: {e}"
                    logger.warning(msg)
                    errors.append(msg)

        # ── CRM ─────────────────────────────────────────
        if crm_seeds and self._crm:
            for seed in crm_seeds:
                try:
                    if hasattr(self._crm, "upsert_lead"):
                        await self._crm.upsert_lead(seed.model_dump())
                    elif hasattr(self._crm, "create_or_update_contact"):
                        await self._crm.create_or_update_contact(
                            seed.contact_data
                        )
                except Exception as e:
                    msg = f"CRM publish failed for {seed.uid}: {e}"
                    logger.warning(msg)
                    errors.append(msg)

        # ── Audit ───────────────────────────────────────
        if audit_entries and self._audit:
            for entry in audit_entries:
                try:
                    if hasattr(self._audit, "append"):
                        await self._audit.append(entry.model_dump())
                    elif hasattr(self._audit, "write"):
                        self._audit.write(entry.model_dump())
                except Exception as e:
                    msg = f"Audit publish failed for {entry.audit_id}: {e}"
                    logger.warning(msg)
                    errors.append(msg)

        # ── Review Queue ────────────────────────────────
        if review_required and self._review:
            try:
                from byou.review.models import ReviewItem, ReviewItemType

                # Create a review item for ambiguous identities
                # Check if any participant has provisional status
                for participant in session.participants:
                    if participant.identity_status in ("provisional", "unknown"):
                        item = ReviewItem(
                            item_type=ReviewItemType.AMBIGUOUS_MATCH,
                            source="intake",
                            related_session_id=session.sid,
                            related_uid=participant.identity_ref,
                            priority="medium",
                            title=f"Identity resolution needed for {participant.display_name or participant.participant_id}",
                            description=f"Status: {participant.identity_status}, confidence: {participant.identity_confidence}",
                            evidence_refs=participant.evidence_refs,
                        )
                        self._review.enqueue(item)
                        review_flags.append(item.item_id)

            except Exception as e:
                msg = f"Review queue publish failed: {e}"
                logger.warning(msg)
                errors.append(msg)

        # ── Core Conversation (optional, v2) ────────────
        if self._conversation:
            try:
                if hasattr(self._conversation, "ingest_session"):
                    await self._conversation.ingest_session(
                        session.model_dump()
                    )
            except Exception as e:
                msg = f"Conversation gateway publish failed: {e}"
                logger.warning(msg)
                errors.append(msg)

        return IntakeProcessingResult(
            session_id=session.sid,
            canonical_session=session.model_dump(mode="json"),
            memory_seeds=[s.model_dump(mode="json") for s in memory_seeds],
            crm_seeds=[s.model_dump(mode="json") for s in crm_seeds],
            audit_entries=[e.model_dump(mode="json") for e in audit_entries],
            review_required=review_required,
            review_flags=review_flags,
            errors=errors,
        )
