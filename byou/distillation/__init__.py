# byou/distillation/__init__.py
"""Batch Distillation — L2 structured signals → L3 distilled knowledge.

Phase 3 v3: distillation writeback layer.
  - DistillationWriteback: distilled knowledge → Memory / Knowledge Store / CRM
  - MemoryWriteback: MemorySummary field-level updates with audit trail
  - KnowledgeWriteback: knowledge upsert to durable store (no transcript)
  - WritebackPolicy: per-target auto/review/dry-run/disabled modes

NEVER reads raw transcripts.
"""

from byou.distillation.models import (
    ConversionPattern,
    DistillationJob,
    DistillationJobStatus,
    DistillationJobType,
    DistilledKnowledge,
    ObjectionPlaybook,
    ObjectionPlaybookEntry,
    TalkingPointEffect,
)
from byou.distillation.runner import DistillationJobTrigger, DistillationRunner
from byou.distillation.writeback import (
    DistillationWriteback,
    DistillationWritebackEntry,
    KnowledgeWriteback,
    KnowledgeWritebackEntry,
    MemoryWriteback,
    MemoryWritebackEntry,
    WritebackMode,
    WritebackPolicy,
    WritebackPolicyRegistry,
    WritebackTarget,
)

__all__ = [
    "ConversionPattern",
    "DistillationJob",
    "DistillationJobStatus",
    "DistillationJobTrigger",
    "DistillationJobType",
    "DistilledKnowledge",
    "DistillationRunner",
    "DistillationWriteback",
    "DistillationWritebackEntry",
    "KnowledgeWriteback",
    "KnowledgeWritebackEntry",
    "MemoryWriteback",
    "MemoryWritebackEntry",
    "ObjectionPlaybook",
    "ObjectionPlaybookEntry",
    "TalkingPointEffect",
    "WritebackMode",
    "WritebackPolicy",
    "WritebackPolicyRegistry",
    "WritebackTarget",
]
