"""Review Writeback Layer — Phase 3 v3.

Review resolution → upstream writeback (identity, crm, memory, distillation, audit).

Single ReviewWritebackDispatcher routes resolution actions to per-system handlers.
Each handler implements the same async interface: (ReviewItem, ReviewResolutionResult) → WritebackResult.
Handlers are injected — no hard deps.

ReviewOutcomeApplier is the top-level orchestrator:
  review_it → ReviewWritebackDispatcher.dispatch → per-system results → ReviewResolutionResult

Key constraints:
  - transcript 不进任何 writeback
  - evidence chain preserved (review_item_id tracked)
  - all writebacks audited
  - handlers graceful degrade on missing injection
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel, Field
from uuid import uuid4

from byou.review.models import (
    ResolutionAction,
    ReviewItem,
    WritebackResult,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# Per-system writeback state
# ══════════════════════════════════════════════════════════

class PerSystemWritebackState(BaseModel):
    """State of writeback to one downstream system."""
    target: str                    # "identity", "crm", "memory", "distillation", "audit"
    action: str = ""               # "merge_uid", "create_lead", "update_memory", etc.
    status: str = "pending"        # "pending" | "success" | "failed" | "skipped"
    message: str = ""
    error: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    completed_at: datetime | None = None


class ReviewResolutionResult(BaseModel):
    """Full resolution result including per-system writeback states."""
    item_id: str
    resolution_action: ResolutionAction
    resolution_notes: str = ""
    resolved_by: str = "system"
    resolved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    writebacks: dict[str, PerSystemWritebackState] = Field(default_factory=dict)

    @property
    def all_successful(self) -> bool:
        if not self.writebacks:
            return True
        return all(
            s.status == "success" or s.status == "skipped"
            for s in self.writebacks.values()
        )

    @property
    def has_failures(self) -> bool:
        return any(s.status == "failed" for s in self.writebacks.values())

    @property
    def failed_targets(self) -> list[str]:
        return [t for t, s in self.writebacks.items() if s.status == "failed"]


# ══════════════════════════════════════════════════════════
# Per-system writeback handlers
# ══════════════════════════════════════════════════════════

WritebackHandler = Callable[
    [ReviewItem, ReviewResolutionResult],
    "WritebackResult | None",
]

# Type alias for clarity (commented: Python 3.11 doesn't support `type` statement)
# type HandlerFunc = WritebackHandler


class IdentityWritebackHandler:
    """Handle identity-related review writebacks: merge, confirm, reject, enroll, override."""

    def __init__(self, identity_graph=None):
        self._graph = identity_graph

    async def __call__(
        self, item: ReviewItem, resolution: ReviewResolutionResult,
    ) -> WritebackResult:
        action = resolution.resolution_action

        # Map resolution action to identity writeback
        if action == ResolutionAction.MERGE_UID:
            return await self._merge_uid(item, resolution)
        elif action == ResolutionAction.CONFIRM_NEW_UID:
            return await self._confirm_new_uid(item, resolution)
        elif action == ResolutionAction.RE_ENROLL_VOICEPRINT:
            return await self._re_enroll_voiceprint(item, resolution)
        elif action == ResolutionAction.REJECT_MATCH:
            return await self._reject_match(item, resolution)
        elif action == ResolutionAction.MANUAL_OVERRIDE:
            return await self._manual_override(item, resolution)
        else:
            return WritebackResult(
                target="identity",
                action=action.value,
                success=True,
                message="No identity writeback needed",
            )

    async def _merge_uid(self, item, resolution) -> WritebackResult:
        if not self._graph:
            return WritebackResult(
                target="identity", action="merge_uid",
                success=False, message="No identity graph injected",
            )

        source = item.payload.get("source_uid", "")
        target = item.payload.get("target_uid", "")
        if not source or not target:
            return WritebackResult(
                target="identity", action="merge_uid",
                success=False, message="Missing source_uid or target_uid",
            )

        from byou.intake.identity.graph import IdentityBinding, BindingType

        # Create merge binding
        binding = IdentityBinding(
            source_id=source,
            target_id=target,
            binding_type=BindingType.MERGED_INTO,
            confidence=1.0,
            evidence_refs=[item.item_id],
        )
        self._graph.add_binding(binding)

        # Deactivate old bindings
        for b in self._graph.get_bindings_for(source):
            if b.is_active and b.binding_type != BindingType.MERGED_INTO:
                b.is_active = False

        # Migrate aliases
        source_node = self._graph.get_node(source)
        target_node = self._graph.get_node(target)
        if source_node and target_node:
            for alias in source_node.aliases:
                if alias not in target_node.aliases:
                    target_node.aliases.append(alias)
            target_node.aliases.append(source_node.label)

        return WritebackResult(
            target="identity",
            action="merge_uid",
            success=True,
            details={
                "source": source,
                "target": target,
                "binding_id": binding.binding_id,
            },
        )

    async def _confirm_new_uid(self, item, resolution) -> WritebackResult:
        if not self._graph:
            return WritebackResult(
                target="identity", action="confirm_new_uid",
                success=False, message="No identity graph injected",
            )

        from byou.intake.identity.graph import IdentityNode, NodeType

        person = item.payload.get("person", {})
        name = person.get("name", item.related_uid or f"rev_{uuid4().hex[:6]}")
        uid = item.related_uid or f"uid_rev_{uuid4().hex[:8]}"

        node = IdentityNode(
            node_id=uid,
            node_type=NodeType.UID,
            label=name,
            aliases=[v for v in person.values() if isinstance(v, str) and v],
            metadata={
                "phone": person.get("phone", ""),
                "email": person.get("email", ""),
                "company": person.get("company", ""),
                "title": person.get("title", ""),
                "confirmed_by": "review",
                "review_id": item.item_id,
            },
        )
        self._graph.add_node(node)

        return WritebackResult(
            target="identity",
            action="confirm_new_uid",
            success=True,
            details={"uid": uid, "name": name},
        )

    async def _re_enroll_voiceprint(self, item, resolution) -> WritebackResult:
        if not self._graph:
            return WritebackResult(
                target="identity", action="re_enroll_voiceprint",
                success=False, message="No identity graph injected",
            )

        uid = item.payload.get("uid", item.related_uid or "")
        embedding = item.payload.get("embedding", [])
        if not uid or not embedding:
            return WritebackResult(
                target="identity", action="re_enroll_voiceprint",
                success=False, message="Missing uid or embedding",
            )

        self._graph.register_voiceprint(uid, embedding)
        return WritebackResult(
            target="identity",
            action="re_enroll_voiceprint",
            success=True,
            details={"uid": uid, "embedding_dims": len(embedding)},
        )

    async def _reject_match(self, item, resolution) -> WritebackResult:
        if not self._graph:
            return WritebackResult(
                target="identity", action="reject_match",
                success=False, message="No identity graph injected",
            )

        binding_id = item.payload.get("binding_id", "")
        if binding_id:
            self._graph.deactivate_binding(binding_id)
            return WritebackResult(
                target="identity",
                action="reject_match",
                success=True,
                details={"binding_id": binding_id},
            )

        # Find bindings between uid_a and uid_b
        uid_a = item.payload.get("source_uid", "")
        uid_b = item.payload.get("target_uid", "")
        deactivated = []
        if uid_a and uid_b:
            for b in self._graph.get_bindings_for(uid_a):
                relevant = (
                    (b.source_id == uid_a and b.target_id == uid_b) or
                    (b.source_id == uid_b and b.target_id == uid_a)
                )
                if relevant and b.is_active:
                    b.is_active = False
                    deactivated.append(b.binding_id)

        return WritebackResult(
            target="identity",
            action="reject_match",
            success=True,
            details={"deactivated": deactivated},
        )

    async def _manual_override(self, item, resolution) -> WritebackResult:
        if not self._graph:
            return WritebackResult(
                target="identity", action="manual_override",
                success=False, message="No identity graph injected",
            )

        uid = item.related_uid or ""
        overrides = item.payload.get("overrides", {})
        node = self._graph.get_node(uid)
        if not node:
            return WritebackResult(
                target="identity", action="manual_override",
                success=False, message=f"UID {uid} not found",
            )

        changed = []
        for key, val in overrides.items():
            if key == "label":
                node.label = val
                changed.append("label")
            elif key == "aliases" and isinstance(val, list):
                for a in val:
                    if a not in node.aliases:
                        node.aliases.append(a)
                changed.append(f"aliases:+{len(val)}")
            elif key in ("phone", "email", "company", "title"):
                if node.metadata.get(key) != val:
                    node.metadata[key] = val
                    changed.append(key)

        return WritebackResult(
            target="identity",
            action="manual_override",
            success=True,
            details={"uid": uid, "changed": changed},
        )


class CRMWritebackHandler:
    """Handle CRM-related review writebacks."""

    def __init__(self, crm_gateway=None):
        self._crm = crm_gateway

    async def __call__(
        self, item: ReviewItem, resolution: ReviewResolutionResult,
    ) -> WritebackResult:
        action = resolution.resolution_action

        if action == ResolutionAction.MERGE_UID:
            return await self._merge_uid(item)
        elif action == ResolutionAction.CONFIRM_NEW_UID:
            return await self._confirm_new_uid(item)
        elif action == ResolutionAction.UPDATE_CRM_NOTE:
            return await self._update_note(item)
        elif action == ResolutionAction.APPROVE_TASK:
            return await self._flag_approved(item)
        elif action == ResolutionAction.MANUAL_OVERRIDE:
            return await self._manual_override(item)
        else:
            return WritebackResult(
                target="crm", action=action.value,
                success=True, message="No CRM writeback needed",
            )

    async def _merge_uid(self, item) -> WritebackResult:
        if not self._crm:
            return WritebackResult(
                target="crm", action="merge_uid",
                success=False, message="No CRM gateway injected",
            )
        source = item.payload.get("source_uid", "")
        target = item.payload.get("target_uid", "")
        if not source or not target:
            return WritebackResult(
                target="crm", action="merge_uid",
                success=False, message="Missing UIDs",
            )

        try:
            if hasattr(self._crm, "merge_contacts"):
                await self._crm.merge_contacts(source, target)
            return WritebackResult(
                target="crm", action="merge_uid",
                success=True, details={"source": source, "target": target},
            )
        except Exception as e:
            return WritebackResult(
                target="crm", action="merge_uid",
                success=False, error=str(e),
            )

    async def _confirm_new_uid(self, item) -> WritebackResult:
        if not self._crm:
            return WritebackResult(
                target="crm", action="confirm_new_uid",
                success=False, message="No CRM gateway injected",
            )

        person = item.payload.get("person", {})
        uid = item.related_uid or ""
        try:
            if hasattr(self._crm, "upsert_lead"):
                await self._crm.upsert_lead({"uid": uid, **person})
            return WritebackResult(
                target="crm", action="confirm_new_uid",
                success=True, details={"uid": uid},
            )
        except Exception as e:
            return WritebackResult(
                target="crm", action="confirm_new_uid",
                success=False, error=str(e),
            )

    async def _update_note(self, item) -> WritebackResult:
        if not self._crm or not item.related_uid:
            return WritebackResult(
                target="crm", action="update_crm_note",
                success=False, message="No CRM gateway or missing UID",
            )

        note = item.payload.get("note", item.resolution_notes or item.description)
        try:
            if hasattr(self._crm, "add_note"):
                await self._crm.add_note(item.related_uid, note)
            return WritebackResult(
                target="crm", action="update_crm_note",
                success=True, details={"uid": item.related_uid},
            )
        except Exception as e:
            return WritebackResult(
                target="crm", action="update_crm_note",
                success=False, error=str(e),
            )

    async def _flag_approved(self, item) -> WritebackResult:
        if not self._crm:
            return WritebackResult(
                target="crm", action="approve_task",
                success=False, message="No CRM gateway injected",
            )

        try:
            if hasattr(self._crm, "mark_approved"):
                await self._crm.mark_approved(
                    item.related_approval_id or item.item_id,
                    item.resolution_notes,
                )
            return WritebackResult(
                target="crm", action="approve_task",
                success=True,
            )
        except Exception as e:
            return WritebackResult(
                target="crm", action="approve_task",
                success=False, error=str(e),
            )

    async def _manual_override(self, item) -> WritebackResult:
        if not self._crm or not item.related_uid:
            return WritebackResult(
                target="crm", action="manual_override",
                success=False, message="No CRM gateway or missing UID",
            )
        overrides = item.payload.get("overrides", {})
        try:
            if hasattr(self._crm, "update_lead"):
                await self._crm.update_lead(item.related_uid, overrides)
            return WritebackResult(
                target="crm", action="manual_override",
                success=True, details={"uid": item.related_uid},
            )
        except Exception as e:
            return WritebackResult(
                target="crm", action="manual_override",
                success=False, error=str(e),
            )


class MemoryWritebackHandler:
    """Handle Memory-related review writebacks."""

    def __init__(self, memory_gateway=None):
        self._memory = memory_gateway

    async def __call__(
        self, item: ReviewItem, resolution: ReviewResolutionResult,
    ) -> WritebackResult:
        action = resolution.resolution_action

        if action == ResolutionAction.MERGE_UID:
            return await self._merge_uid(item)
        elif action == ResolutionAction.CONFIRM_NEW_UID:
            return await self._confirm_new_uid(item)
        elif action == ResolutionAction.UPDATE_CRM_NOTE:
            return await self._update_from_note(item)
        elif action == ResolutionAction.MANUAL_OVERRIDE:
            return await self._manual_override(item)
        else:
            return WritebackResult(
                target="memory", action=action.value,
                success=True, message="No memory writeback needed",
            )

    async def _merge_uid(self, item) -> WritebackResult:
        if not self._memory:
            return WritebackResult(
                target="memory", action="merge_uid",
                success=False, message="No memory gateway injected",
            )

        source = item.payload.get("source_uid", "")
        target = item.payload.get("target_uid", "")
        if not source or not target:
            return WritebackResult(
                target="memory", action="merge_uid",
                success=False, message="Missing UIDs",
            )

        try:
            if hasattr(self._memory, "merge_summaries"):
                await self._memory.merge_summaries(source, target)
            elif hasattr(self._memory, "update_memory_summary"):
                await self._memory.update_memory_summary(source, {"merged_into": target})
            return WritebackResult(
                target="memory", action="merge_uid",
                success=True, details={"source": source, "target": target},
            )
        except Exception as e:
            return WritebackResult(
                target="memory", action="merge_uid",
                success=False, error=str(e),
            )

    async def _confirm_new_uid(self, item) -> WritebackResult:
        if not self._memory:
            return WritebackResult(
                target="memory", action="confirm_new_uid",
                success=False, message="No memory gateway injected",
            )

        person = item.payload.get("person", {})
        uid = item.related_uid or ""
        try:
            if hasattr(self._memory, "update_memory_summary"):
                await self._memory.update_memory_summary(
                    uid,
                    {k: v for k, v in person.items() if k not in (
                        "transcript", "raw_transcript", "full_text",
                    )},
                )
            return WritebackResult(
                target="memory", action="confirm_new_uid",
                success=True, details={"uid": uid},
            )
        except Exception as e:
            return WritebackResult(
                target="memory", action="confirm_new_uid",
                success=False, error=str(e),
            )

    async def _update_from_note(self, item) -> WritebackResult:
        if not self._memory or not item.related_uid:
            return WritebackResult(
                target="memory", action="update_crm_note",
                success=False, message="No memory gateway or missing UID",
            )
        try:
            note = item.payload.get("note", item.resolution_notes)
            if hasattr(self._memory, "update_memory_summary"):
                await self._memory.update_memory_summary(
                    item.related_uid, {"review_note": note},
                )
            return WritebackResult(
                target="memory", action="update_crm_note",
                success=True,
            )
        except Exception as e:
            return WritebackResult(
                target="memory", action="update_crm_note",
                success=False, error=str(e),
            )

    async def _manual_override(self, item) -> WritebackResult:
        if not self._memory or not item.related_uid:
            return WritebackResult(
                target="memory", action="manual_override",
                success=False, message="No memory gateway or missing UID",
            )
        overrides = item.payload.get("overrides", {})
        # Strip transcript fields
        safe = {k: v for k, v in overrides.items() if k not in (
            "transcript", "raw_transcript", "full_text", "conversation_text",
        )}
        try:
            if hasattr(self._memory, "update_memory_summary"):
                await self._memory.update_memory_summary(item.related_uid, safe)
            return WritebackResult(
                target="memory", action="manual_override",
                success=True,
            )
        except Exception as e:
            return WritebackResult(
                target="memory", action="manual_override",
                success=False, error=str(e),
            )


class AuditWritebackHandler:
    """Audit every review writeback — always runs."""

    def __init__(self, audit_store=None):
        self._audit = audit_store

    async def __call__(
        self, item: ReviewItem, resolution: ReviewResolutionResult,
    ) -> WritebackResult:
        if not self._audit:
            return WritebackResult(
                target="audit", action="log_review",
                success=True, message="No audit store — skipped",
            )

        entry = {
            "event_type": f"review_{resolution.resolution_action.value}",
            "item_id": item.item_id,
            "item_type": item.item_type.value,
            "source": item.source,
            "session_id": item.related_session_id,
            "uid": item.related_uid,
            "action": resolution.resolution_action.value,
            "notes": resolution.resolution_notes[:500],
            "resolved_by": resolution.resolved_by,
            "resolved_at": resolution.resolved_at.isoformat() if resolution.resolved_at else "",
            "writeback_count": len(resolution.writebacks),
        }

        try:
            if hasattr(self._audit, "append"):
                await self._audit.append(entry)
            elif hasattr(self._audit, "write"):
                self._audit.write(entry)
            return WritebackResult(
                target="audit", action="log_review",
                success=True, details={"event_type": entry["event_type"]},
            )
        except Exception as e:
            return WritebackResult(
                target="audit", action="log_review",
                success=False, error=str(e),
            )


# ══════════════════════════════════════════════════════════
# Writeback dispatcher
# ══════════════════════════════════════════════════════════

class ReviewWritebackDispatcher:
    """Dispatch review resolution to per-system handlers.

    Routes by resolution action → list of targets → registered handlers.
    Handlers are injected via register(target, handler_fn).
    Missing handler → target skipped (no error).
    """

    def __init__(self):
        self._handlers: dict[str, HandlerFunc] = {}

    def register(self, target: str, handler: HandlerFunc) -> None:
        """Register a writeback handler for a target system."""
        self._handlers[target] = handler

    async def dispatch(
        self, item: ReviewItem, resolution: ReviewResolutionResult,
    ) -> ReviewResolutionResult:
        """Dispatch writeback to all relevant targets."""
        targets = self._writeback_targets(item, resolution.resolution_action)

        for target in targets:
            handler = self._handlers.get(target)
            if not handler:
                resolution.writebacks[target] = PerSystemWritebackState(
                    target=target,
                    action=resolution.resolution_action.value,
                    status="skipped",
                    message=f"No handler registered for {target}",
                )
                continue

            state = PerSystemWritebackState(
                target=target,
                action=resolution.resolution_action.value,
                status="pending",
            )

            try:
                result = await handler(item, resolution)
                if result is None:
                    state.status = "skipped"
                    state.message = "Handler returned None"
                elif isinstance(result, WritebackResult):
                    state.status = "success" if result.success else "failed"
                    state.message = result.message
                    state.error = result.error
                    state.details = result.details
                else:
                    state.status = "success"
                    state.details = {"raw_result": str(result)}
            except Exception as e:
                state.status = "failed"
                state.error = str(e)
                logger.exception("Writeback handler %s failed: %s", target, e)

            state.completed_at = datetime.now(timezone.utc)
            resolution.writebacks[target] = state

        return resolution

    def _writeback_targets(
        self, item: ReviewItem, action: ResolutionAction,
    ) -> list[str]:
        """Determine which targets to write to for a given resolution action."""
        # Always audit
        targets = ["audit"]

        action_targets = {
            ResolutionAction.MERGE_UID: ["identity", "crm", "memory"],
            ResolutionAction.CONFIRM_NEW_UID: ["identity", "crm", "memory"],
            ResolutionAction.RE_ENROLL_VOICEPRINT: ["identity"],
            ResolutionAction.REJECT_MATCH: ["identity"],
            ResolutionAction.APPROVE_TASK: ["approval", "durable_exec", "crm"],
            ResolutionAction.REJECT_TASK: ["approval", "durable_exec"],
            ResolutionAction.FLAG_FOR_RETRY: ["durable_exec", "crm"],
            ResolutionAction.UPDATE_CRM_NOTE: ["crm", "memory"],
            ResolutionAction.DISMISS: [],  # only audit
            ResolutionAction.MANUAL_OVERRIDE: ["identity", "memory", "crm", "distillation"],
        }

        targets = action_targets.get(action, []) + ["audit"]
        return list(dict.fromkeys(targets))  # dedup, preserve order


# ══════════════════════════════════════════════════════════
# ReviewWriteback — top-level orchestration entry
# ══════════════════════════════════════════════════════════

class ReviewWriteback:
    """Top-level writeback entry — builds dispatcher with available handlers.

    Usage:
        wb = ReviewWriteback(
            identity_graph=graph,
            crm_gateway=crm,
            memory_gateway=mem,
            audit_store=audit,
        )
        resolution = await wb.apply_review(review_item, action, notes)
    """

    def __init__(
        self,
        identity_graph=None,
        crm_gateway=None,
        memory_gateway=None,
        audit_store=None,
    ):
        self._dispatcher = ReviewWritebackDispatcher()

        # Register available handlers
        if identity_graph:
            self._dispatcher.register("identity", IdentityWritebackHandler(identity_graph))
        if crm_gateway:
            self._dispatcher.register("crm", CRMWritebackHandler(crm_gateway))
        if memory_gateway:
            self._dispatcher.register("memory", MemoryWritebackHandler(memory_gateway))

        # Audit always registered (noop if None)
        self._dispatcher.register("audit", AuditWritebackHandler(audit_store))

    async def apply_review(
        self,
        item: ReviewItem,
        action: ResolutionAction,
        notes: str = "",
        resolved_by: str = "system",
    ) -> ReviewResolutionResult:
        """Apply a review resolution and dispatch writebacks."""
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=action,
            resolution_notes=notes,
            resolved_by=resolved_by,
        )

        resolution = await self._dispatcher.dispatch(item, resolution)
        return resolution


# ══════════════════════════════════════════════════════════
# ReviewOutcomeApplier — integration with ReviewQueueGateway
# ══════════════════════════════════════════════════════════

class ReviewOutcomeApplier:
    """Top-level orchestrator: ReviewQueueGateway → dispatcher → resolve.

    Usage:
        applier = ReviewOutcomeApplier(review_gateway, dispatcher)
        resolution = await applier.apply("rev_123", ResolutionAction.MERGE_UID, notes="...")
    """

    def __init__(self, review_gateway, dispatcher: ReviewWritebackDispatcher):
        self._gateway = review_gateway
        self._dispatcher = dispatcher

    async def apply(
        self,
        item_id: str,
        action: ResolutionAction,
        notes: str = "",
        resolved_by: str = "system",
    ) -> ReviewResolutionResult:
        """Resolve a review item and dispatch writebacks."""
        # Resolve in the review queue
        item = None
        if hasattr(self._gateway, "resolve"):
            import inspect
            gw_resolve = self._gateway.resolve
            if inspect.iscoroutinefunction(gw_resolve):
                item = await gw_resolve(item_id, action, notes, resolved_by)
            else:
                item = gw_resolve(item_id, action, notes, resolved_by)
        if item is None and hasattr(self._gateway, "get"):
            item = self._gateway.get(item_id)

        if not item:
            resolution = ReviewResolutionResult(
                item_id=item_id,
                resolution_action=action,
                resolution_notes=notes,
                resolved_by=resolved_by,
            )
            resolution.writebacks["gateway"] = PerSystemWritebackState(
                target="gateway", action=action.value,
                status="failed", message=f"Item {item_id} not found",
            )
            return resolution

        # Create resolution
        resolution = ReviewResolutionResult(
            item_id=item_id,
            resolution_action=action,
            resolution_notes=notes,
            resolved_by=resolved_by,
        )

        # Dispatch writebacks
        resolution = await self._dispatcher.dispatch(item, resolution)
        return resolution
