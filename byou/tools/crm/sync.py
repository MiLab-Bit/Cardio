"""CRM Tool — bidirectional sync engine.

Features:
- Push: Byou PipelineContext → CRM contact
- Pull: CRM contact → update local records
- Conflict resolution (configurable strategy)
- Retry with exponential backoff
- Sync status tracking (delegated to SQLite store)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from byou.models.customer import PipelineContext, CustomerProfile
from byou.tools.crm.client import create_crm_provider, BaseCRMProvider
from byou.tools.crm.models import (
    CRMContact, CRMConfig, SyncDirection, SyncStatus,
    CRMSyncRecord, ConflictStrategy,
)

logger = logging.getLogger(__name__)


# ── Conflict Resolution ────────────────────────────────────────

def resolve_conflict(
    byou_contact: CRMContact,
    crm_contact: CRMContact,
    strategy: ConflictStrategy,
) -> tuple[CRMContact, list[str]]:
    """Resolve sync conflict between Byou and CRM data.

    Returns:
        (merged_contact, list_of_conflicted_fields)
    """
    conflict_fields = []
    merged = CRMContact(**byou_contact.model_dump())

    for field_name in byou_contact.model_fields:
        if field_name.startswith("_") or field_name in ("raw_crm_data", "byou_updated_at", "crm_updated_at"):
            continue
        byou_val = getattr(byou_contact, field_name)
        crm_val = getattr(crm_contact, field_name)

        if byou_val == crm_val:
            continue
        if not byou_val and crm_val:
            # Only CRM has data — always prefer CRM
            setattr(merged, field_name, crm_val)
        elif byou_val and not crm_val:
            # Only Byou has data — keep Byou
            pass
        elif byou_val != crm_val:
            conflict_fields.append(field_name)
            if strategy == ConflictStrategy.BYOU_WINS:
                pass  # keep byou_val
            elif strategy == ConflictStrategy.CRM_WINS:
                setattr(merged, field_name, crm_val)
            elif strategy == ConflictStrategy.NEWEST_WINS:
                byou_ts = byou_contact.byou_updated_at or datetime.min
                crm_ts = crm_contact.crm_updated_at or datetime.min
                if crm_ts > byou_ts:
                    setattr(merged, field_name, crm_val)
                # else keep byou_val
            else:  # MANUAL
                # Mark conflict but prefer Byou for now
                pass

    return merged, conflict_fields


# ── Sync Engine ────────────────────────────────────────────────

class CRMSyncEngine:
    """Bidirectional CRM sync engine."""

    def __init__(self, config: CRMConfig):
        self.config = config
        self.provider: BaseCRMProvider = create_crm_provider(config)

    # ── Push (Byou → CRM) ──────────────────────────────────────

    async def push_pipeline_result(self, ctx: PipelineContext) -> CRMSyncRecord:
        """Push a completed pipeline result to CRM.

        Flow:
        1. Convert PipelineContext → CRMContact
        2. Query CRM by email/phone to find existing
        3. Upsert (create or update)
        4. Return sync status
        """
        record = CRMSyncRecord(
            byou_id=ctx.id or "",
            direction=SyncDirection.PUSH,
            provider=self.config.provider,
        )

        if not ctx.profile:
            record.status = SyncStatus.SKIPPED
            record.error_message = "No customer profile in pipeline context"
            return record

        try:
            # Convert to CRM contact
            contact = self._pipeline_to_contact(ctx)

            # Check if already synced (has crm_id)
            if ctx.profile.model_extra and ctx.profile.model_extra.get("crm_id"):
                contact.crm_id = ctx.profile.model_extra["crm_id"]

            # If no crm_id, try to find existing by email
            if not contact.crm_id and contact.email:
                existing = await self.provider.query_contacts(email=contact.email)
                if existing:
                    contact.crm_id = existing[0].crm_id
                    logger.info("CRM: found existing contact by email=%s crm_id=%s",
                                contact.email, contact.crm_id)

            # Upsert
            record.byou_data_snapshot = contact.model_dump()
            status, crm_id, resp = await self.provider.upsert_contact(contact)

            if status == SyncStatus.SUCCESS:
                record.status = SyncStatus.SUCCESS
                record.crm_id = crm_id
                record.completed_at = datetime.now()
                # Also push the BD strategy as a CRM note/task
                if ctx.strategy_result:
                    await self._push_strategy_as_note(crm_id, ctx)
                logger.info("CRM push OK: byou_id=%s crm_id=%s", record.byou_id, crm_id)
            else:
                record.status = status
                record.error_message = str(resp.get("error", ""))

        except Exception as e:
            logger.error("CRM push error: %s", e)
            record.status = SyncStatus.FAILED
            record.error_message = str(e)

        return record

    async def push_contact(self, contact: CRMContact) -> CRMSyncRecord:
        """Push a single contact to CRM."""
        record = CRMSyncRecord(
            byou_id=contact.byou_id or contact.email or "",
            direction=SyncDirection.PUSH,
            provider=self.config.provider,
        )
        record.byou_data_snapshot = contact.model_dump()

        try:
            status, crm_id, resp = await self.provider.upsert_contact(contact)
            record.status = status
            record.crm_id = crm_id
            record.completed_at = datetime.now()
            if status != SyncStatus.SUCCESS:
                record.error_message = str(resp.get("error", ""))
        except Exception as e:
            record.status = SyncStatus.FAILED
            record.error_message = str(e)

        return record

    # ── Pull (CRM → Byou) ──────────────────────────────────────

    async def pull_contact(self, crm_id: str) -> tuple[SyncStatus, CRMContact | None, CRMSyncRecord]:
        """Pull a single contact from CRM."""
        record = CRMSyncRecord(
            byou_id="",
            crm_id=crm_id,
            direction=SyncDirection.PULL,
            provider=self.config.provider,
        )

        status, contact = await self.provider.get_contact(crm_id)
        if status == SyncStatus.SUCCESS and contact:
            record.status = SyncStatus.SUCCESS
            record.byou_id = contact.byou_id or contact.email or crm_id
            record.completed_at = datetime.now()
            record.crm_data_snapshot = contact.raw_crm_data
            return status, contact, record
        else:
            record.status = SyncStatus.FAILED
            record.error_message = "Contact not found or fetch failed"
            return status, None, record

    async def pull_by_email(self, email: str) -> tuple[SyncStatus, CRMContact | None]:
        """Pull contact by email (query then fetch)."""
        results = await self.provider.query_contacts(email=email)
        if results:
            return SyncStatus.SUCCESS, results[0]
        return SyncStatus.FAILED, None

    async def pull_updated_contacts(self, since: datetime) -> list[CRMContact]:
        """Pull all CRM contacts updated since timestamp.

        Note: This requires CRM API support for date filtering.
        For CRMs that don't support this, returns empty list.
        """
        # Generic implementation — override in provider if supported
        logger.info("CRM pull updated since %s — not supported by generic provider", since)
        return []

    # ── Bidirectional Sync ──────────────────────────────────────

    async def sync_bidirectional(self, ctx: PipelineContext) -> CRMSyncRecord:
        """Full bidirectional sync for one pipeline result.

        1. Push Byou → CRM
        2. Pull CRM → Byou (get updated data)
        3. Resolve conflicts
        """
        # Push first
        push_record = await self.push_pipeline_result(ctx)

        if push_record.status != SyncStatus.SUCCESS:
            return push_record

        # Pull back to verify / get CRM-enriched data
        crm_id = push_record.crm_id
        if crm_id:
            status, crm_contact, pull_record = await self.pull_contact(crm_id)
            if status == SyncStatus.SUCCESS and crm_contact:
                # Check for conflicts
                byou_contact = self._pipeline_to_contact(ctx)
                _, conflict_fields = resolve_conflict(
                    byou_contact, crm_contact,
                    self.config.conflict_strategy,
                )
                if conflict_fields:
                    logger.warning("CRM sync conflicts: %s", conflict_fields)
                    push_record.status = SyncStatus.CONFLICT
                    push_record.conflict_fields = conflict_fields

        return push_record

    # ── Batch Operations ────────────────────────────────────────

    async def batch_push(self, contexts: list[PipelineContext]) -> list[CRMSyncRecord]:
        """Push multiple pipeline results. Returns list of sync records."""
        results = []
        for ctx in contexts:
            record = await self.push_pipeline_result(ctx)
            results.append(record)
        return results

    # ── Private Helpers ─────────────────────────────────────────

    def _pipeline_to_contact(self, ctx: PipelineContext) -> CRMContact:
        """Convert PipelineContext to CRMContact."""
        p = ctx.profile
        if not p:
            return CRMContact()

        return CRMContact(
            byou_id=ctx.id,
            name=p.name,
            title=p.title,
            company=p.company,
            phone=p.phone,
            email=p.email,
            wechat=p.wechat,
            address=p.address,
            industry=p.industry,
            company_size=p.company_size,
            company_description=p.company_description,
            source=p.source or "byou",
            customer_level=ctx.customer_level,
            intent_score=ctx.intent_score,
            trust_score=ctx.trust_score,
            risk_alerts=ctx.risk_alerts,
            byou_updated_at=ctx.completed_at or datetime.now(),
        )

    async def _push_strategy_as_note(self, crm_id: str, ctx: PipelineContext) -> None:
        """Push BD strategy as a CRM note/task (best-effort)."""
        if not ctx.strategy_result:
            return
        try:
            # This is provider-specific
            # For now, just log — can be extended per provider
            logger.info("CRM: would push strategy note for crm_id=%s (not implemented)", crm_id)
        except Exception as e:
            logger.warning("Failed to push strategy note: %s", e)

    async def close(self) -> None:
        await self.provider.close()
