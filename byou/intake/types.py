# byou/intake/types.py
"""Protocol types for Intake Pipeline gateways.

Defines typed interfaces so that callers know what methods each gateway
must implement.  Inject these via IntakeHandler / IntakePublisher instead
of passing ``Any``.
"""

from __future__ import annotations

from typing import Protocol, Any

from byou.models.channel_contract import (
    AuditEntry,
    CRMSeed,
    CanonicalSession,
    MemorySeed,
)


# ════════════════════════════════════════════════════════
# IdentityGraphProtocol
# ════════════════════════════════════════════════════════

class IdentityGraphProtocol(Protocol):
    """Minimal interface that identity_graph must implement.

    Used by CrossSessionMatcher and IntakeHandler.
    """

    def find_by_type(self, node_type: str) -> list[Any]: ...
    def match_voiceprint(self, embedding: list[float], top_k: int = 3) -> Any: ...
    def register_identity(self, uid: str, **kwargs: Any) -> None: ...
    def add_node(self, node: Any) -> None: ...


# ════════════════════════════════════════════════════════
# MemoryGatewayProtocol
# ════════════════════════════════════════════════════════

class MemoryGatewayProtocol(Protocol):
    """Gateway to long-term memory storage (e.g. vector DB, Notion).

    Primary method: ``ingest_signals``.
    Alternative (legacy): ``ingest``.
    """

    async def ingest_signals(self, signals: list[dict[str, Any]] | dict[str, Any]) -> None:
        """Ingest memory signals into long-term storage."""
        ...


# ════════════════════════════════════════════════════════
# CRMGatewayProtocol
# ════════════════════════════════════════════════════════

class CRMGatewayProtocol(Protocol):
    """Gateway to CRM system (e.g. Salesforce, HubSpot).

    Primary method: ``upsert_lead``.
    Alternative (legacy): ``create_or_update_contact``.
    """

    async def upsert_lead(self, lead_data: dict[str, Any]) -> dict[str, Any]:
        """Create or update a lead in the CRM."""
        ...


# ════════════════════════════════════════════════════════
# AuditGatewayProtocol
# ════════════════════════════════════════════════════════

class AuditGatewayProtocol(Protocol):
    """Gateway to audit log storage."""

    async def append(self, entry: dict[str, Any] | AuditEntry) -> None:
        """Append an audit entry."""
        ...


# ════════════════════════════════════════════════════════
# ReviewGatewayProtocol
# ════════════════════════════════════════════════════════

class ReviewGatewayProtocol(Protocol):
    """Gateway to human review queue."""

    def enqueue(self, item: Any) -> None:
        """Enqueue a review item for human approval."""
        ...


# ════════════════════════════════════════════════════════
# ConversationGatewayProtocol
# ════════════════════════════════════════════════════════

class ConversationGatewayProtocol(Protocol):
    """Gateway to core conversation system (v2)."""

    async def ingest_session(self, session: dict[str, Any] | CanonicalSession) -> None:
        """Ingest a canonical session into the conversation system."""
        ...
