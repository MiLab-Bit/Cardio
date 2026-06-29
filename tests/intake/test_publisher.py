# tests/intake/test_publisher.py
"""Intake Publisher tests."""

from dataclasses import dataclass, field
from typing import Any

import pytest

from byou.intake.models import IntakeProcessingResult
from byou.intake.publisher import IntakePublisher
from byou.models.channel_contract import (
    AuditEntry,
    CRMSeed,
    CanonicalParticipant,
    CanonicalSession,
    MemorySeed,
)


# ══════════════════════════════════════════════════════════
# Stub gateways
# ══════════════════════════════════════════════════════════

@dataclass
class MemoryStub:
    ingested: list = field(default_factory=list)

    async def ingest_signals(self, data: dict):
        self.ingested.append(data)


@dataclass
class CRMStub:
    upserted: list = field(default_factory=list)

    async def upsert_lead(self, data: dict):
        self.upserted.append(data)


@dataclass
class AuditStub:
    entries: list = field(default_factory=list)

    async def append(self, data: dict):
        self.entries.append(data)


@dataclass
class ReviewStub:
    items: list = field(default_factory=list)

    def enqueue(self, item):
        self.items.append(item)
        return item.item_id


@dataclass
class ConversationStub:
    sessions: list = field(default_factory=list)

    async def ingest_session(self, data: dict):
        self.sessions.append(data)


# ══════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════

class TestPublisher:
    async def test_publish_memory_seeds(self):
        memory = MemoryStub()
        publisher = IntakePublisher(memory_gateway=memory)

        result = await publisher.publish(
            session=CanonicalSession(sid="sid_001"),
            memory_seeds=[
                MemorySeed(uid="uid_001", sid="sid_001", company_name="腾讯"),
            ],
            crm_seeds=[],
            audit_entries=[],
        )

        assert isinstance(result, IntakeProcessingResult)
        assert len(memory.ingested) == 1
        assert memory.ingested[0]["company_name"] == "腾讯"

    async def test_publish_crm_seeds(self):
        crm = CRMStub()
        publisher = IntakePublisher(crm_gateway=crm)

        await publisher.publish(
            session=CanonicalSession(sid="sid_001"),
            memory_seeds=[],
            crm_seeds=[
                CRMSeed(uid="uid_001", action="create", contact_data={"name": "张三"}),
            ],
            audit_entries=[],
        )

        assert len(crm.upserted) == 1
        assert crm.upserted[0]["contact_data"]["name"] == "张三"

    async def test_publish_audit_entries(self):
        audit = AuditStub()
        publisher = IntakePublisher(audit_gateway=audit)

        await publisher.publish(
            session=CanonicalSession(sid="sid_001"),
            memory_seeds=[],
            crm_seeds=[],
            audit_entries=[
                AuditEntry(
                    audit_id="audit_001",
                    event_type="session_created",
                    event_id="sid_001",
                ),
            ],
        )

        assert len(audit.entries) == 1

    async def test_publish_review_for_ambiguous(self):
        review = ReviewStub()
        publisher = IntakePublisher(review_gateway=review)

        session = CanonicalSession(
            sid="sid_001",
            participants=[
                CanonicalParticipant(
                    participant_id="P0",
                    role="visitor",
                    identity_status="provisional",
                    identity_ref="uid_002",
                    identity_confidence=0.65,
                    display_name="张三",
                ),
            ],
        )

        result = await publisher.publish(
            session=session,
            memory_seeds=[],
            crm_seeds=[],
            audit_entries=[],
            review_required=True,
        )

        assert len(review.items) == 1
        assert review.items[0].source == "intake"
        assert "review_flags" in result.model_dump()

    async def test_no_review_when_not_required(self):
        review = ReviewStub()
        publisher = IntakePublisher(review_gateway=review)

        await publisher.publish(
            session=CanonicalSession(sid="sid_001"),
            memory_seeds=[],
            crm_seeds=[],
            audit_entries=[],
            review_required=False,
        )

        assert len(review.items) == 0

    async def test_review_only_for_provisional_unknown(self):
        """Confirmed participants should NOT trigger review items."""
        review = ReviewStub()
        publisher = IntakePublisher(review_gateway=review)

        session = CanonicalSession(
            sid="sid_001",
            participants=[
                CanonicalParticipant(
                    participant_id="P0",
                    role="bd_staff",
                    identity_status="confirmed",
                    identity_ref="bid_001",
                    identity_confidence=1.0,
                ),
            ],
        )

        await publisher.publish(
            session=session,
            memory_seeds=[],
            crm_seeds=[],
            audit_entries=[],
            review_required=True,
        )

        # BD staff is confirmed → no review
        assert len(review.items) == 0

    async def test_conversation_gateway(self):
        conv = ConversationStub()
        publisher = IntakePublisher(conversation_gateway=conv)

        await publisher.publish(
            session=CanonicalSession(sid="sid_001"),
            memory_seeds=[],
            crm_seeds=[],
            audit_entries=[],
        )

        assert len(conv.sessions) == 1

    async def test_graceful_degrade_missing_gateways(self):
        """No gateways at all → should not crash."""
        publisher = IntakePublisher()
        result = await publisher.publish(
            session=CanonicalSession(sid="sid_001"),
            memory_seeds=[MemorySeed(uid="uid_001", sid="sid_001")],
            crm_seeds=[CRMSeed(uid="uid_001", contact_data={})],
            audit_entries=[
                AuditEntry(audit_id="audit_001", event_type="test", event_id="sid_001"),
            ],
        )
        assert isinstance(result, IntakeProcessingResult)
        # No errors logged (all gateways missing → skip gracefully)

    async def test_gateway_error_does_not_crash(self):
        """If one gateway fails, others still succeed and errors are captured."""

        @dataclass
        class FailingMemory:
            async def ingest_signals(self, data):
                raise RuntimeError("DB connection lost")

        memory = FailingMemory()
        crm = CRMStub()
        publisher = IntakePublisher(memory_gateway=memory, crm_gateway=crm)

        result = await publisher.publish(
            session=CanonicalSession(sid="sid_001"),
            memory_seeds=[MemorySeed(uid="uid_001", sid="sid_001")],
            crm_seeds=[CRMSeed(uid="uid_001", contact_data={"name": "张三"})],
            audit_entries=[],
        )

        assert len(result.errors) >= 1
        assert "Memory publish failed" in result.errors[0]
        # CRM still succeeded
        assert len(crm.upserted) == 1

    async def test_crm_create_or_update_contact_fallback(self):
        """CRM gateway with create_or_update_contact method works."""
        @dataclass
        class CRMWithContact:
            contacts: list = field(default_factory=list)
            async def create_or_update_contact(self, data: dict):
                self.contacts.append(data)

        crm = CRMWithContact()
        publisher = IntakePublisher(crm_gateway=crm)

        await publisher.publish(
            session=CanonicalSession(sid="sid_001"),
            memory_seeds=[],
            crm_seeds=[CRMSeed(uid="uid_001", contact_data={"name": "张三"})],
            audit_entries=[],
        )

        assert len(crm.contacts) == 1
