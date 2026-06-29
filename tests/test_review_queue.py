# tests/test_review_queue.py
"""Unified Review Queue tests — identity + post-call reviews share one queue."""

from __future__ import annotations

import pytest

from byou.review.models import (
    ResolutionAction,
    ReviewItem,
    ReviewItemType,
    ReviewQueueStats,
    ReviewStatus,
)
from byou.review.gateway import ReviewQueueGateway, ReviewResolver


# ══════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════

def _identity_item(item_type=ReviewItemType.IDENTITY_CONFLICT, priority="high"):
    return ReviewItem(
        item_type=item_type,
        source="intake",
        related_session_id="sess_001",
        related_uid="uid_alpha",
        priority=priority,
        title="Identity conflict",
        description="VPID matched two UIDs",
        evidence_refs=["eid_001"],
    )


def _postcall_item(item_type=ReviewItemType.QA_LOW_SCORE, priority="medium"):
    return ReviewItem(
        item_type=item_type,
        source="postcall",
        related_session_id="sess_002",
        related_qa_id="qa_001",
        priority=priority,
        title="Low QA score",
        description="Overall QA score 0.25",
    )


# ══════════════════════════════════════════════════════════
# ReviewItem
# ══════════════════════════════════════════════════════════

class TestReviewItem:
    def test_identity_item_created(self):
        item = _identity_item()
        assert item.source == "intake"
        assert item.item_type == ReviewItemType.IDENTITY_CONFLICT
        assert item.status == ReviewStatus.PENDING
        assert item.item_id.startswith("rev_")

    def test_postcall_item_created(self):
        item = _postcall_item()
        assert item.source == "postcall"
        assert item.item_type == ReviewItemType.QA_LOW_SCORE

    def test_mark_in_review(self):
        item = _identity_item()
        item.mark_in_review("reviewer_1")
        assert item.status == ReviewStatus.IN_REVIEW
        assert item.resolved_by == "reviewer_1"

    def test_resolve(self):
        item = _postcall_item()
        item.resolve(ResolutionAction.FLAG_FOR_RETRY, notes="retry tomorrow")
        assert item.status == ReviewStatus.RESOLVED
        assert item.resolution_action == ResolutionAction.FLAG_FOR_RETRY
        assert item.resolved_at is not None

    def test_dismiss(self):
        item = _identity_item()
        item.dismiss("duplicate review item")
        assert item.status == ReviewStatus.DISMISSED

    def test_different_types_coexist(self):
        """Identity and post-call reviews share the same model."""
        id_item = _identity_item()
        pc_item = _postcall_item()
        assert id_item.item_type != pc_item.item_type
        assert isinstance(id_item, ReviewItem)
        assert isinstance(pc_item, ReviewItem)


# ══════════════════════════════════════════════════════════
# ReviewQueueGateway
# ══════════════════════════════════════════════════════════

class TestReviewQueueGateway:
    def test_enqueue_returns_id(self):
        gw = ReviewQueueGateway()
        item = _identity_item()
        item_id = gw.enqueue(item)
        assert item_id == item.item_id

    def test_dequeue_highest_priority(self):
        gw = ReviewQueueGateway()
        gw.enqueue(_postcall_item(priority="medium"))
        gw.enqueue(_identity_item(priority="critical"))
        gw.enqueue(_postcall_item(ReviewItemType.COMPLIANCE_VIOLATION, priority="high"))

        item = gw.dequeue()
        assert item.priority == "critical"

    def test_dequeue_from_empty_returns_none(self):
        gw = ReviewQueueGateway()
        assert gw.dequeue() is None

    def test_peek_does_not_remove(self):
        gw = ReviewQueueGateway()
        gw.enqueue(_identity_item())
        assert len(gw.peek()) == 1
        assert len(gw.list_pending()) == 1  # still in queue

    def test_resolve_updates_status(self):
        gw = ReviewQueueGateway()
        item_id = gw.enqueue(_postcall_item())
        resolved = gw.resolve(item_id, ResolutionAction.APPROVE_TASK)
        assert resolved.status == ReviewStatus.RESOLVED
        assert resolved.resolution_action == ResolutionAction.APPROVE_TASK

    def test_dismiss_updates_status(self):
        gw = ReviewQueueGateway()
        item_id = gw.enqueue(_identity_item())
        dismissed = gw.dismiss(item_id, "false alarm")
        assert dismissed.status == ReviewStatus.DISMISSED

    def test_resolve_missing_returns_none(self):
        gw = ReviewQueueGateway()
        assert gw.resolve("nonexistent", ResolutionAction.DISMISS) is None

    def test_list_by_session(self):
        gw = ReviewQueueGateway()
        gw.enqueue(_identity_item())
        gw.enqueue(_postcall_item())  # different session
        items = gw.list_by_session("sess_001")
        assert len(items) == 1
        assert items[0].item_type == ReviewItemType.IDENTITY_CONFLICT

    def test_duplicate_same_session_type(self):
        """Second enqueue with same session+type suppresses to avoid noise."""
        gw = ReviewQueueGateway()
        item1 = _identity_item()
        item2 = _identity_item()  # same session, same type
        id1 = gw.enqueue(item1)
        id2 = gw.enqueue(item2)
        assert id1 == id2  # deduplicated

    def test_different_type_not_duplicate(self):
        gw = ReviewQueueGateway()
        id1 = gw.enqueue(_identity_item(ReviewItemType.IDENTITY_CONFLICT))
        id2 = gw.enqueue(_identity_item(ReviewItemType.AMBIGUOUS_MATCH))
        assert id1 != id2  # different types = different items

    def test_stats(self):
        gw = ReviewQueueGateway()
        gw.enqueue(_identity_item())
        gw.enqueue(_postcall_item())
        item_id = gw.enqueue(_postcall_item(ReviewItemType.COMPLIANCE_VIOLATION))
        gw.resolve(item_id, ResolutionAction.DISMISS)

        stats = gw.stats()
        assert isinstance(stats, ReviewQueueStats)
        assert stats.pending == 2
        assert stats.resolved == 1
        assert stats.by_source.get("intake", 0) == 1
        assert stats.by_source.get("postcall", 0) == 2


# ══════════════════════════════════════════════════════════
# ReviewResolver
# ══════════════════════════════════════════════════════════

class TestReviewResolver:
    async def test_resolve_with_handler(self):
        gw = ReviewQueueGateway()
        resolver = ReviewResolver(gw)

        # Register a stub handler
        handler_results = []
        async def stub_handler(item: ReviewItem):
            handler_results.append(item.item_id)
            from byou.review.models import WritebackResult
            return WritebackResult(
                target="identity", action="merge_uid",
                success=True, message="merged"
            )

        resolver.register_handler("identity", stub_handler)

        item_id = gw.enqueue(_identity_item())
        results = await resolver.resolve(
            item_id, ResolutionAction.MERGE_UID,
            notes="manual merge", reviewer="admin",
        )

        assert len(results) >= 1
        assert handler_results == [item_id]

        identity_results = [r for r in results if r.target == "identity"]
        assert identity_results[0].success

    async def test_resolve_missing_item(self):
        gw = ReviewQueueGateway()
        resolver = ReviewResolver(gw)
        results = await resolver.resolve(
            "nonexistent", ResolutionAction.DISMISS
        )
        assert results[0].success is False

    async def test_no_handler_returns_error(self):
        gw = ReviewQueueGateway()
        resolver = ReviewResolver(gw)
        item_id = gw.enqueue(_identity_item())

        # No identity handler registered
        results = await resolver.resolve(
            item_id, ResolutionAction.MERGE_UID
        )
        identity_results = [r for r in results if r.target == "identity"]
        assert not identity_results[0].success

    async def test_writeback_targets_determined(self):
        """Verify writeback targets are correctly mapped."""
        targets = ReviewResolver._writeback_targets(
            _identity_item(), ResolutionAction.MERGE_UID
        )
        assert "identity" in targets
        assert "crm" in targets
        assert "audit" in targets  # always

        targets_dismiss = ReviewResolver._writeback_targets(
            _identity_item(), ResolutionAction.DISMISS
        )
        assert targets_dismiss == ["audit"]  # only audit

    def test_max_dequeue_options(self):
        """Test full dequeue + resolve lifecycle."""
        gw = ReviewQueueGateway()
        item_id = gw.enqueue(_identity_item(priority="high"))
        assert gw.list_pending()
        item = gw.dequeue()
        assert item
        assert item.status == ReviewStatus.IN_REVIEW
        resolved = gw.resolve(item_id, ResolutionAction.DISMISS)
        assert resolved.status == ReviewStatus.RESOLVED
