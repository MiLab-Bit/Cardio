"""Distillation & Memory Writeback — Phase 3 v3.

Writeback from distillation results to Memory, Knowledge Store, CRM, Audit.
Includes transcript blocking enforcement at all layers.

Key constraints:
  - transcript 不进 Memory / Knowledge Store
  - raw_transcript, full_text, conversation_text, dialog_text, speech_text, utterances = blocked
  - writeback mode routing: AUTO | REVIEW_REQUIRED | DRY_RUN | DISABLED
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
from uuid import uuid4

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# Transcript blocking
# ══════════════════════════════════════════════════════════

FORBIDDEN_TRANSCRIPT_KEYS: tuple[str, ...] = (
    "transcript",
    "raw_transcript",
    "full_text",
    "conversation_text",
    "dialog_text",
    "speech_text",
    "utterances",
)


def contains_transcript(data: dict[str, Any], depth: int = 0) -> bool:
    """Check if any key in the dict (or nested dicts) contains transcript data.

    depth: max recursion depth (guard against circular refs).
    """
    if depth > 5:
        return False

    for key in data:
        if key.lower() in FORBIDDEN_TRANSCRIPT_KEYS:
            return True
        if isinstance(data[key], dict):
            if contains_transcript(data[key], depth + 1):
                return True
        elif isinstance(data[key], list):
            for item in data[key]:
                if isinstance(item, dict) and contains_transcript(item, depth + 1):
                    return True
    return False


# ══════════════════════════════════════════════════════════
# Enums
# ══════════════════════════════════════════════════════════

class WritebackTarget(str, Enum):
    MEMORY = "memory"
    CRM = "crm"
    KNOWLEDGE_STORE = "knowledge_store"
    AUDIT = "audit"
    DISTILLATION = "distillation"


class WritebackMode(str, Enum):
    AUTO = "auto"                     # write back immediately
    REVIEW_REQUIRED = "review_required" # needs review approval
    DRY_RUN = "dry_run"               # simulate but don't commit
    DISABLED = "disabled"             # don't write back


# ══════════════════════════════════════════════════════════
# Writeback Policy
# ══════════════════════════════════════════════════════════

class WritebackPolicy(BaseModel):
    """Per-target writeback policy controlling mode, confidence threshold, and type overrides."""
    target: WritebackTarget
    mode: WritebackMode = WritebackMode.AUTO
    min_confidence: float = 0.6
    type_overrides: dict[str, WritebackMode] = Field(default_factory=dict)

    def effective_mode(self, signal_type: str) -> WritebackMode:
        """Resolve mode for a signal type, respecting overrides."""
        return self.type_overrides.get(signal_type, self.mode)


class WritebackPolicyRegistry(BaseModel):
    """Collection of per-target writeback policies."""
    policies: dict[str, WritebackPolicy] = Field(default_factory=dict)

    def get(self, target: WritebackTarget) -> WritebackPolicy:
        key = target.value
        return self.policies.get(key, WritebackPolicy(target=target))

    @classmethod
    def defaults(cls) -> "WritebackPolicyRegistry":
        """Production defaults: Memory auto with review for unresolved objections,
        CRM always review_required, Knowledge Store review_required, Audit always auto."""
        return cls(policies={
            "memory": WritebackPolicy(
                target=WritebackTarget.MEMORY,
                mode=WritebackMode.AUTO,
                min_confidence=0.6,
                type_overrides={
                    "objection_unresolved": WritebackMode.REVIEW_REQUIRED,
                    "sentiment_shift_negative": WritebackMode.REVIEW_REQUIRED,
                },
            ),
            "crm": WritebackPolicy(
                target=WritebackTarget.CRM,
                mode=WritebackMode.REVIEW_REQUIRED,
                min_confidence=0.8,
            ),
            "knowledge_store": WritebackPolicy(
                target=WritebackTarget.KNOWLEDGE_STORE,
                mode=WritebackMode.REVIEW_REQUIRED,
                min_confidence=0.7,
            ),
            "audit": WritebackPolicy(
                target=WritebackTarget.AUDIT,
                mode=WritebackMode.AUTO,
                min_confidence=0.0,
            ),
            "distillation": WritebackPolicy(
                target=WritebackTarget.DISTILLATION,
                mode=WritebackMode.AUTO,
                min_confidence=0.5,
            ),
        })


# ══════════════════════════════════════════════════════════
# Writeback Entry models
# ══════════════════════════════════════════════════════════

class WritebackEntryBase(BaseModel):
    entry_id: str = Field(default_factory=lambda: f"wbe_{uuid4().hex[:8]}")
    target: WritebackTarget
    status: str = "pending"    # pending | committed | review_required | rejected | skipped
    error: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DistillationWritebackEntry(WritebackEntryBase):
    signal_type: str = ""     # objection_playbook | conversion_pattern | talking_point_effect
    source_key: str = ""       # playbook_id / pattern_id / talking_point
    content: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    sample_count: int = 0


class MemoryWritebackEntry(WritebackEntryBase):
    lead_id: str = ""
    field: str = ""
    old_value: Any = None
    new_value: Any = None
    contains_transcript: bool = False


class KnowledgeWritebackEntry(WritebackEntryBase):
    knowledge_type: str = ""
    knowledge_id: str = ""
    content: dict[str, Any] = Field(default_factory=dict)
    contains_transcript: bool = False
    source_job_id: str = ""
    sample_count: int = 0
    confidence: float = 0.0


# ══════════════════════════════════════════════════════════
# DistillationWriteback
# ══════════════════════════════════════════════════════════

class DistillationWriteback:
    """Write distilled knowledge back to Memory, Knowledge Store, and Audit.

    Usage:
        dwb = DistillationWriteback(memory_gateway=mem, knowledge_store=ks, audit_store=audit)
        entries = await dwb.write_back(knowledge)
    """

    def __init__(
        self,
        memory_gateway: Any = None,
        knowledge_store: Any = None,
        audit_store: Any = None,
        policy: WritebackPolicyRegistry | None = None,
    ):
        self._memory = memory_gateway
        self._ks = knowledge_store
        self._audit = audit_store
        self._policy = policy or WritebackPolicyRegistry.defaults()

    async def write_back(
        self, knowledge: Any, dry_run: bool = False,
    ) -> list[DistillationWritebackEntry]:
        """Write back all distilled knowledge."""
        entries: list[DistillationWritebackEntry] = []

        # Playbooks → objection entries
        for pb in getattr(knowledge, "playbooks", []):
            for entry in getattr(pb, "entries", []):
                topic = getattr(entry, "objection_topic", "")
                overcome_rate = getattr(entry, "overcome_rate", 0.0)

                mem_policy = self._policy.get(WritebackTarget.MEMORY)
                ks_policy = self._policy.get(WritebackTarget.KNOWLEDGE_STORE)

                # Memory entry
                if mem_policy.effective_mode("objection_playbook") == WritebackMode.AUTO and not dry_run:
                    wbe = await self._ingest_objection(topic, overcome_rate, knowledge)
                elif mem_policy.effective_mode("objection_playbook") == WritebackMode.REVIEW_REQUIRED:
                    wbe = DistillationWritebackEntry(
                        target=WritebackTarget.MEMORY,
                        signal_type="objection_playbook",
                        source_key=topic,
                        content={"objection_topic": topic, "overcome_rate": overcome_rate},
                        confidence=overcome_rate,
                        status="review_required",
                        error="Policy requires review",
                    )
                else:
                    wbe = DistillationWritebackEntry(
                        target=WritebackTarget.MEMORY,
                        signal_type="objection_playbook",
                        source_key=topic,
                        status="skipped" if mem_policy.mode == WritebackMode.DISABLED else "pending",
                    )
                entries.append(wbe)

            # Knowledge store entry for the whole playbook
            if ks_policy.effective_mode("objection_playbook") != WritebackMode.DISABLED and not dry_run:
                ks_entries = await self._ingest_playbook_knowledge(pb, knowledge)
                entries.extend(ks_entries)

        # Conversion patterns
        for cp in getattr(knowledge, "conversion_patterns", []):
            pid = getattr(cp, "pattern_id", "")
            rate = getattr(cp, "conversion_rate", 0.0)
            industry = getattr(cp, "industry", "")
            wbe = await self._ingest_conversion_pattern(pid, industry, rate, knowledge, dry_run)
            entries.append(wbe)

        # Talking point effects
        for tp in getattr(knowledge, "talking_point_effects", []):
            point = getattr(tp, "talking_point", "")
            score = getattr(tp, "effectiveness_score", 0.0)
            count = getattr(tp, "sample_count", 0)
            wbe = await self._ingest_talking_point(point, score, count, knowledge, dry_run)
            entries.append(wbe)

        return entries

    async def _ingest_objection(
        self, topic: str, overcome_rate: float, knowledge: Any,
    ) -> DistillationWritebackEntry:
        entry = DistillationWritebackEntry(
            target=WritebackTarget.MEMORY,
            signal_type="objection_playbook",
            source_key=topic,
            content={"objection_topic": topic, "overcome_rate": overcome_rate},
            confidence=overcome_rate,
        )

        mem_policy = self._policy.get(WritebackTarget.MEMORY)
        if overcome_rate < mem_policy.min_confidence:
            entry.status = "review_required"
            entry.error = f"Confidence {overcome_rate} < min {mem_policy.min_confidence}"
            return entry

        if self._memory:
            try:
                if hasattr(self._memory, "ingest_distilled_entry"):
                    await self._memory.ingest_distilled_entry(
                        {"type": "objection_playbook", "topic": topic, "overcome_rate": overcome_rate},
                        entry_id=entry.entry_id,
                    )
                entry.status = "committed"
            except Exception as e:
                entry.status = "review_required"
                entry.error = str(e)
        else:
            entry.status = "review_required"
            entry.error = "No memory gateway"

        # Audit
        if self._audit:
            try:
                obj_entry = {
                    "event_type": "writeback_objection",
                    "entry_id": entry.entry_id,
                    "topic": topic,
                    "overcome_rate": overcome_rate,
                    "status": entry.status,
                }
                await self._audit.append(obj_entry)
            except Exception:
                pass

        return entry

    async def _ingest_playbook_knowledge(
        self, pb: Any, knowledge: Any,
    ) -> list[DistillationWritebackEntry]:
        entries: list[DistillationWritebackEntry] = []

        pb_id = getattr(pb, "playbook_id", "")
        content = {"playbook_id": pb_id, "version": getattr(pb, "version", 1)}

        # Check for transcript in entries
        for ent in getattr(pb, "entries", []):
            if contains_transcript({"topic": getattr(ent, "objection_topic", "")}):
                wbe = DistillationWritebackEntry(
                    target=WritebackTarget.KNOWLEDGE_STORE,
                    signal_type="objection_playbook",
                    source_key=pb_id,
                    status="rejected",
                    error="Transcript content blocked",
                )
                entries.append(wbe)
                return entries

        if self._ks:
            try:
                await self._ks.upsert(content, entry_id=pb_id)
                wbe = DistillationWritebackEntry(
                    target=WritebackTarget.KNOWLEDGE_STORE,
                    signal_type="objection_playbook",
                    source_key=pb_id,
                    content=content,
                    status="committed",
                )
            except Exception as e:
                wbe = DistillationWritebackEntry(
                    target=WritebackTarget.KNOWLEDGE_STORE,
                    signal_type="objection_playbook",
                    source_key=pb_id,
                    status="review_required",
                    error=str(e),
                )
        else:
            wbe = DistillationWritebackEntry(
                target=WritebackTarget.KNOWLEDGE_STORE,
                signal_type="objection_playbook",
                source_key=pb_id,
                status="review_required",
                error="No knowledge store",
            )
        entries.append(wbe)
        return entries

    async def _ingest_conversion_pattern(
        self, pid: str, industry: str, rate: float,
        knowledge: Any, dry_run: bool,
    ) -> DistillationWritebackEntry:
        entry = DistillationWritebackEntry(
            target=WritebackTarget.MEMORY,
            signal_type="conversion_pattern",
            source_key=pid,
            content={"pattern_id": pid, "industry": industry, "conversion_rate": rate},
            confidence=rate,
        )

        mem_policy = self._policy.get(WritebackTarget.MEMORY)
        if rate < mem_policy.min_confidence:
            entry.status = "review_required"
            entry.error = f"Confidence {rate} < min {mem_policy.min_confidence}"
            return entry

        if self._memory and not dry_run:
            try:
                if hasattr(self._memory, "ingest_conversion_pattern"):
                    await self._memory.ingest_conversion_pattern(
                        {"pattern_id": pid, "industry": industry,
                         "conversion_rate": rate},
                        entry_id=entry.entry_id,
                    )
                entry.status = "committed"
            except Exception as e:
                entry.status = "review_required"
                entry.error = str(e)
        else:
            entry.status = "pending" if dry_run else "review_required"

        # Audit
        if self._audit:
            try:
                await self._audit.append({
                    "event_type": "writeback_conversion_pattern",
                    "entry_id": entry.entry_id,
                    "pattern_id": pid,
                    "industry": industry,
                    "status": entry.status,
                })
            except Exception:
                pass

        return entry

    async def _ingest_talking_point(
        self, point: str, score: float, count: int,
        knowledge: Any, dry_run: bool,
    ) -> DistillationWritebackEntry:
        entry = DistillationWritebackEntry(
            target=WritebackTarget.MEMORY,
            signal_type="talking_point_effect",
            source_key=point,
            content={
                "talking_point": point,
                "effectiveness_score": score,
                "sample_count": count,
            },
            confidence=score,
            sample_count=count,
        )

        mem_policy = self._policy.get(WritebackTarget.MEMORY)
        if score < mem_policy.min_confidence:
            entry.status = "review_required"
            entry.error = f"Confidence {score} < min {mem_policy.min_confidence}"
            return entry

        if self._memory and not dry_run:
            try:
                if hasattr(self._memory, "ingest_talking_point_effect"):
                    await self._memory.ingest_talking_point_effect(
                        {"talking_point": point, "effectiveness_score": score,
                         "sample_count": count},
                        entry_id=entry.entry_id,
                    )
                entry.status = "committed"
            except Exception as e:
                entry.status = "review_required"
                entry.error = str(e)
        else:
            entry.status = "pending" if dry_run else "review_required"

        # Audit
        if self._audit:
            try:
                await self._audit.append({
                    "event_type": "writeback_talking_point",
                    "entry_id": entry.entry_id,
                    "talking_point": point,
                    "score": score,
                    "status": entry.status,
                })
            except Exception:
                pass

        return entry


# ══════════════════════════════════════════════════════════
# MemoryWriteback
# ══════════════════════════════════════════════════════════

class MemoryWriteback:
    """Direct memory field updates with transcript blocking.

    Usage:
        mwb = MemoryWriteback(memory_gateway=mem)
        entry = await mwb.update_memory_summary("lead_001", "intent_score", 0.85, old_value=0.5)
    """

    def __init__(
        self,
        memory_gateway: Any = None,
        policy: WritebackPolicyRegistry | None = None,
    ):
        self._memory = memory_gateway
        self._policy = policy or WritebackPolicyRegistry.defaults()

    async def update_memory_summary(
        self, lead_id: str, field: str, new_value: Any,
        old_value: Any = None, session_id: str = "",
    ) -> MemoryWritebackEntry:
        """Update a field in memory summary. Blocks transcript fields."""
        entry = MemoryWritebackEntry(
            target=WritebackTarget.MEMORY,
            lead_id=lead_id,
            field=field,
            old_value=old_value,
            new_value=new_value,
        )

        # Block transcript
        if field.lower() in FORBIDDEN_TRANSCRIPT_KEYS or \
           (isinstance(new_value, str) and len(new_value) > 1000 and "说" in new_value and "答" in new_value):
            entry.status = "rejected"
            entry.error = "Transcript content blocked by policy"
            entry.contains_transcript = True
            return entry

        mem_policy = self._policy.get(WritebackTarget.MEMORY)
        if mem_policy.mode == WritebackMode.DISABLED:
            entry.status = "skipped"
            entry.error = "Memory writeback disabled"
            return entry

        if not self._memory:
            entry.status = "review_required"
            entry.error = "No memory gateway"
            return entry

        try:
            if hasattr(self._memory, "update_memory_summary"):
                await self._memory.update_memory_summary(lead_id, {field: new_value})
            elif hasattr(self._memory, "ingest_signals"):
                await self._memory.ingest_signals(
                    {"lead_id": lead_id, "field": field,
                     "value": new_value, "session_id": session_id},
                )
            entry.status = "committed"
        except Exception as e:
            entry.status = "review_required"
            entry.error = str(e)

        return entry

    async def update_bant(
        self, lead_id: str,
        budget: str | None = None,
        authority: str | None = None,
        need: str | None = None,
        timeline: str | None = None,
    ) -> list[MemoryWritebackEntry]:
        """Batch update BANT dimensions."""
        entries: list[MemoryWritebackEntry] = []
        for field, val in [
            ("bant_budget", budget),
            ("bant_authority", authority),
            ("bant_need", need),
            ("bant_timeline", timeline),
        ]:
            if val is not None:
                entries.append(
                    await self.update_memory_summary(lead_id, field, val),
                )
        return entries

    async def update_intent(
        self, lead_id: str, score: float, trend: str = "",
    ) -> list[MemoryWritebackEntry]:
        """Update intent score and trend."""
        entries = [
            await self.update_memory_summary(lead_id, "overall_intent_score", score),
        ]
        if trend:
            entries.append(
                await self.update_memory_summary(lead_id, "intent_trend", trend),
            )
        return entries

    async def add_objection(
        self, lead_id: str, topic: str, pattern_id: str = "",
    ) -> MemoryWritebackEntry:
        """Add an objection topic to memory summary."""
        return await self.update_memory_summary(
            lead_id, "common_objections", topic,
        )


# ══════════════════════════════════════════════════════════
# KnowledgeWriteback
# ══════════════════════════════════════════════════════════

class KnowledgeWriteback:
    """Write knowledge to Knowledge Store with transcript blocking.

    Usage:
        kwb = KnowledgeWriteback(knowledge_store=ks)
        entry = await kwb.upsert("objection_playbook", "pb_001", content, confidence=0.7)
    """

    def __init__(
        self,
        knowledge_store: Any = None,
        policy: WritebackPolicyRegistry | None = None,
    ):
        self._ks = knowledge_store
        self._policy = policy or WritebackPolicyRegistry.defaults()

    async def upsert(
        self,
        knowledge_type: str,
        knowledge_id: str,
        content: dict[str, Any],
        confidence: float = 0.5,
        source_job_id: str = "",
        sample_count: int = 0,
    ) -> KnowledgeWritebackEntry:
        """Upsert knowledge entry. Blocks transcript-containing content."""
        entry = KnowledgeWritebackEntry(
            target=WritebackTarget.KNOWLEDGE_STORE,
            knowledge_type=knowledge_type,
            knowledge_id=knowledge_id,
            content=content,
            confidence=confidence,
            source_job_id=source_job_id,
            sample_count=sample_count,
        )

        # Block transcript
        if contains_transcript(content):
            entry.status = "rejected"
            entry.error = "Transcript content blocked by policy"
            entry.contains_transcript = True
            return entry

        ks_policy = self._policy.get(WritebackTarget.KNOWLEDGE_STORE)
        if ks_policy.mode == WritebackMode.DISABLED:
            entry.status = "skipped"
            entry.error = "Knowledge writeback disabled"
            return entry

        if not self._ks:
            entry.status = "review_required"
            entry.error = "No knowledge store"
            return entry

        if confidence < ks_policy.min_confidence:
            entry.status = "review_required"
            entry.error = f"Confidence {confidence} < min {ks_policy.min_confidence}"
            return entry

        try:
            await self._ks.upsert(content, entry_id=knowledge_id)
            entry.status = "committed"
        except Exception as e:
            entry.status = "review_required"
            entry.error = str(e)

        return entry
