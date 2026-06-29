# byou/review/gateway.py
"""ReviewQueueGateway — abstraction + in-memory implementation.

v2: in-memory queue backed by deque.  v3: persistent queue (DB/Redis).

Shared by Intake (identity review) and Core (post-call review).
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from byou.review.models import (
    ResolutionAction,
    ReviewItem,
    ReviewItemType,
    ReviewQueueStats,
    ReviewStatus,
    WritebackResult,
)

logger = logging.getLogger(__name__)


class ReviewQueueGateway:
    """Unified review queue — identity + post-call.

    Usage:
        gw = ReviewQueueGateway()
        item = gw.enqueue(ReviewItem(...))
        next_item = gw.dequeue()
        gw.resolve(item.item_id, ResolutionAction.MERGE_UID, notes="...")
    """

    def __init__(self) -> None:
        self._queue: deque[ReviewItem] = deque()
        self._all_items: dict[str, ReviewItem] = {}  # item_id → item
        self._auto_id = 0

    # ── Enqueue ───────────────────────────────────────

    def enqueue(self, item: ReviewItem) -> str:
        """Enqueue a review item. Returns item_id."""
        # Check for duplicate (same session + type)
        for existing in self._all_items.values():
            if (existing.related_session_id == item.related_session_id
                    and existing.item_type == item.item_type
                    and existing.status in (ReviewStatus.PENDING, ReviewStatus.IN_REVIEW)):
                logger.debug("Duplicate review item suppressed: %s / %s",
                             item.related_session_id, item.item_type)
                existing.updated_at = datetime.now(timezone.utc)
                return existing.item_id

        self._all_items[item.item_id] = item
        if item.status == ReviewStatus.PENDING:
            self._queue.append(item)
        logger.info("Review item enqueued: %s [%s]", item.item_id, item.item_type)
        return item.item_id

    # ── Dequeue ───────────────────────────────────────

    def dequeue(self, reviewer: str = "system") -> ReviewItem | None:
        """Dequeue the highest-priority pending item."""
        if not self._queue:
            return None
        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_items = sorted(
            self._queue, key=lambda i: (priority_order.get(i.priority, 9), i.created_at)
        )
        item = sorted_items[0]
        self._queue.remove(item)
        item.mark_in_review(reviewer)
        return item

    def peek(self, limit: int = 10) -> list[ReviewItem]:
        """Peek at pending items without dequeuing."""
        return list(self._queue)[:limit]

    # ── Resolve / Dismiss ─────────────────────────────

    def resolve(
        self, item_id: str, action: ResolutionAction, notes: str = "",
        reviewer: str = "system",
    ) -> ReviewItem | None:
        """Resolve a review item with the given action."""
        item = self._all_items.get(item_id)
        if not item:
            return None
        item.mark_in_review(reviewer)
        item.resolve(action, notes)
        logger.info("Review item resolved: %s → %s", item_id, action)
        return item

    def dismiss(self, item_id: str, reason: str = "") -> ReviewItem | None:
        """Dismiss a review item."""
        item = self._all_items.get(item_id)
        if not item:
            return None
        item.dismiss(reason)
        logger.info("Review item dismissed: %s — %s", item_id, reason)
        return item

    # ── Query ─────────────────────────────────────────

    def get(self, item_id: str) -> ReviewItem | None:
        return self._all_items.get(item_id)

    def list_by_session(self, session_id: str) -> list[ReviewItem]:
        return [
            i for i in self._all_items.values()
            if i.related_session_id == session_id
        ]

    def list_by_status(self, status: ReviewStatus) -> list[ReviewItem]:
        return [
            i for i in self._all_items.values()
            if i.status == status
        ]

    def list_pending(self) -> list[ReviewItem]:
        return self.list_by_status(ReviewStatus.PENDING)

    # ── Stats ─────────────────────────────────────────

    def stats(self) -> ReviewQueueStats:
        by_type: dict[str, int] = {}
        by_source: dict[str, int] = {}
        pending = in_review = resolved = dismissed = superseded = 0

        for item in self._all_items.values():
            if item.status == ReviewStatus.PENDING:
                pending += 1
            elif item.status == ReviewStatus.IN_REVIEW:
                in_review += 1
            elif item.status == ReviewStatus.RESOLVED:
                resolved += 1
            elif item.status == ReviewStatus.DISMISSED:
                dismissed += 1
            elif item.status == ReviewStatus.SUPERSEDED:
                superseded += 1

            by_type[item.item_type.value] = by_type.get(item.item_type.value, 0) + 1
            by_source[item.source] = by_source.get(item.source, 0) + 1

        return ReviewQueueStats(
            pending=pending,
            in_review=in_review,
            resolved=resolved,
            dismissed=dismissed,
            superseded=superseded,
            by_type=by_type,
            by_source=by_source,
        )


# ══════════════════════════════════════════════════════════
# Resolver — action → writeback dispatch
# ══════════════════════════════════════════════════════════

class ReviewResolver:
    """Review item → resolution action → writeback to downstream systems.

    Does NOT implement the writeback logic itself — delegates to registered
    writeback handlers.  The resolver's job is:
      1. Validate the resolution action against item type
      2. Determine which systems need writeback
      3. Dispatch to handlers
      4. Record writeback status in item.resolution_writebacks
    """

    def __init__(self, gateway: ReviewQueueGateway) -> None:
        self._gw = gateway
        self._handlers: dict[str, Any] = {}  # system_name → handler

    def register_handler(self, system: str, handler: Any) -> None:
        """Register a writeback handler for a system.

        Handler signature: async def handler(item: ReviewItem) -> WritebackResult
        """
        self._handlers[system] = handler

    async def resolve(
        self, item_id: str, action: ResolutionAction, notes: str = "",
        reviewer: str = "system",
    ) -> list[WritebackResult]:
        """Resolve and dispatch writebacks."""
        item = self._gw.resolve(item_id, action, notes, reviewer)
        if not item:
            return [WritebackResult(
                target="__error__", action="resolve",
                success=False, message=f"Item {item_id} not found"
            )]

        # Determine which systems need writeback
        targets = self._writeback_targets(item, action)
        results: list[WritebackResult] = []

        for system in targets:
            handler = self._handlers.get(system)
            if handler:
                try:
                    result = await handler(item)
                    results.append(result)
                    item.resolution_writebacks[system] = result.model_dump(mode="json")
                except Exception as e:
                    results.append(WritebackResult(
                        target=system, action=action,
                        success=False, message=str(e),
                    ))
                    item.resolution_writebacks[system] = {"error": str(e)}
            else:
                results.append(WritebackResult(
                    target=system, action=action,
                    success=False, message=f"No handler registered for {system}",
                ))

        return results

    @staticmethod
    def _writeback_targets(item: ReviewItem, action: ResolutionAction) -> list[str]:
        """Determine which systems need writeback for this resolution."""
        always_audit = ["audit"]

        # Action → system mapping
        mapping = {
            ResolutionAction.MERGE_UID: ["identity", "crm"],
            ResolutionAction.CONFIRM_NEW_UID: ["identity", "crm"],
            ResolutionAction.RE_ENROLL_VOICEPRINT: ["identity"],
            ResolutionAction.REJECT_MATCH: ["identity"],
            ResolutionAction.APPROVE_TASK: ["approval", "durable_exec"],
            ResolutionAction.REJECT_TASK: ["approval", "durable_exec"],
            ResolutionAction.FLAG_FOR_RETRY: ["durable_exec"],
            ResolutionAction.UPDATE_CRM_NOTE: ["crm"],
            ResolutionAction.DISMISS: [],
            ResolutionAction.MANUAL_OVERRIDE: ["identity", "memory", "crm"],
        }

        targets = mapping.get(action, [])
        return targets + always_audit
