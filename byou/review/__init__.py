# byou/review/__init__.py
"""Unified Review Queue — Phase 3 v3.

Shared queue for identity resolution reviews (Intake) and post-call quality
reviews (Core).  Single ReviewItem type, single gateway, single resolver.

v3: review writeback layer — resolution → upstream (identity, crm, memory,
    approval, distillation, audit).
"""

from byou.review.models import (
    ResolutionAction,
    ReviewItem,
    ReviewItemType,
    ReviewQueueStats,
    ReviewStatus,
    WritebackResult,
)
from byou.review.gateway import ReviewQueueGateway, ReviewResolver
from byou.review.writeback import (
    AuditWritebackHandler,
    CRMWritebackHandler,
    IdentityWritebackHandler,
    MemoryWritebackHandler,
    ReviewOutcomeApplier,
    ReviewResolutionResult,
    ReviewWriteback,
    ReviewWritebackDispatcher,
)

__all__ = [
    "AuditWritebackHandler",
    "CRMWritebackHandler",
    "IdentityWritebackHandler",
    "MemoryWritebackHandler",
    "ResolutionAction",
    "ReviewItem",
    "ReviewItemType",
    "ReviewOutcomeApplier",
    "ReviewQueueGateway",
    "ReviewQueueStats",
    "ReviewResolutionResult",
    "ReviewResolver",
    "ReviewStatus",
    "ReviewWriteback",
    "ReviewWritebackDispatcher",
    "WritebackResult",
]
