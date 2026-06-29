"""Tests for distillation / memory writeback — Phase 3 v3.

Covers:
  - WritebackPolicy & WritebackPolicyRegistry
  - DistillationWriteback
  - MemoryWriteback
  - KnowledgeWriteback (transcript blocking)
  - Writeback mode routing
"""

from __future__ import annotations

import pytest

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


# ══════════════════════════════════════════════════════════
# Fake dependencies
# ══════════════════════════════════════════════════════════

class FakeMemoryGateway:
    def __init__(self):
        self.summaries = {}
        self.distilled = []
        self.conversion_patterns = []
        self.talking_points = []

    async def update_memory_summary(self, uid, updates):
        self.summaries.setdefault(uid, {}).update(updates)
        return True

    async def append_to_summary(self, uid, field, value):
        s = self.summaries.setdefault(uid, {})
        s.setdefault(field, []).append(value)
        return True

    async def ingest_distilled_entry(self, data, entry_id=""):
        self.distilled.append((data, entry_id))
        return True

    async def ingest_conversion_pattern(self, cp, entry_id=""):
        self.conversion_patterns.append((cp, entry_id))
        return True

    async def ingest_talking_point_effect(self, tp, entry_id=""):
        self.talking_points.append((tp, entry_id))
        return True

    async def ingest_signals(self, seed):
        return True

    async def merge_summaries(self, source, target):
        if source in self.summaries:
            self.summaries[target] = {**self.summaries.get(target, {}),
                                      **self.summaries.pop(source, {})}
        return True

    async def query_by_session(self, session_id):
        return []


class FakeKnowledgeStore:
    def __init__(self):
        self.entries = {}

    async def upsert(self, data, entry_id=""):
        self.entries[entry_id] = data
        return True

    async def query_by_session(self, session_id):
        return []


class FakeAuditStore:
    def __init__(self):
        self.entries = []

    async def append(self, entry):
        self.entries.append(entry)

    async def query_by_session(self, session_id):
        return []


class FakeCRMGateway:
    def __init__(self):
        self.leads = {}
        self.notes = {}
        self.merges = []

    async def upsert_lead(self, data):
        self.leads[data.get("uid", "unknown")] = data
        return {"status": "ok"}

    async def add_note(self, uid, note):
        self.notes.setdefault(uid, []).append(note)
        return {"status": "ok"}

    async def merge_contacts(self, source, target):
        self.merges.append((source, target))
        return {"status": "ok"}


# ══════════════════════════════════════════════════════════
# Fake DistilledKnowledge
# ══════════════════════════════════════════════════════════

class FakePlaybookEntry:
    def __init__(self, topic, overcome_rate=0.7):
        self.objection_topic = topic
        self.overcome_rate = overcome_rate


class FakePlaybook:
    def __init__(self, playbook_id, entries):
        self.playbook_id = playbook_id
        self.entries = entries
        self.version = 1


class FakeConversionPattern:
    def __init__(self, pattern_id, industry, conversion_rate=0.4):
        self.pattern_id = pattern_id
        self.industry = industry
        self.conversion_rate = conversion_rate


class FakeTalkingPointEffect:
    def __init__(self, talking_point, effectiveness_score=0.6, sample_count=10):
        self.talking_point = talking_point
        self.effectiveness_score = effectiveness_score
        self.sample_count = sample_count


class FakeDistilledKnowledge:
    def __init__(self):
        self.job_id = "job_001"
        self.playbooks = [
            FakePlaybook("pb_001", [
                FakePlaybookEntry("价格太高", 0.35),
                FakePlaybookEntry("已有供应商", 0.55),
            ]),
        ]
        self.conversion_patterns = [
            FakeConversionPattern("cp_001", "电商", 0.42),
        ]
        self.talking_point_effects = [
            FakeTalkingPointEffect("强调ROI", 0.72, 15),
            FakeTalkingPointEffect("提及竞品劣势", 0.23, 8),
        ]


# ══════════════════════════════════════════════════════════
# WritebackPolicy & PolicyRegistry
# ══════════════════════════════════════════════════════════

class TestWritebackPolicy:

    def test_default_mode(self):
        policy = WritebackPolicy(target=WritebackTarget.MEMORY)
        assert policy.mode == WritebackMode.AUTO
        assert policy.min_confidence == 0.6

    def test_type_override(self):
        policy = WritebackPolicy(
            target=WritebackTarget.MEMORY,
            mode=WritebackMode.AUTO,
            type_overrides={"objection_unresolved": WritebackMode.REVIEW_REQUIRED},
        )
        assert policy.effective_mode("objection_unresolved") == WritebackMode.REVIEW_REQUIRED
        assert policy.effective_mode("objection_overcome") == WritebackMode.AUTO

    def test_effective_mode_no_override(self):
        policy = WritebackPolicy(target=WritebackTarget.MEMORY, mode=WritebackMode.DRY_RUN)
        assert policy.effective_mode("") == WritebackMode.DRY_RUN
        assert policy.effective_mode("unknown_type") == WritebackMode.DRY_RUN

    def test_disabled_mode(self):
        policy = WritebackPolicy(target=WritebackTarget.CRM, mode=WritebackMode.DISABLED)
        assert policy.effective_mode("") == WritebackMode.DISABLED


class TestWritebackPolicyRegistry:

    def test_defaults_exist(self):
        registry = WritebackPolicyRegistry.defaults()
        assert len(registry.policies) >= 5

    def test_memory_auto_with_review_exceptions(self):
        registry = WritebackPolicyRegistry.defaults()
        policy = registry.get(WritebackTarget.MEMORY)
        assert policy.mode == WritebackMode.AUTO
        assert policy.effective_mode("objection_unresolved") == WritebackMode.REVIEW_REQUIRED

    def test_crm_review_required(self):
        registry = WritebackPolicyRegistry.defaults()
        policy = registry.get(WritebackTarget.CRM)
        assert policy.mode == WritebackMode.REVIEW_REQUIRED

    def test_audit_always_auto(self):
        registry = WritebackPolicyRegistry.defaults()
        policy = registry.get(WritebackTarget.AUDIT)
        assert policy.mode == WritebackMode.AUTO
        assert policy.min_confidence == 0.0

    def test_unknown_target(self):
        registry = WritebackPolicyRegistry.defaults()
        policy = registry.get(WritebackTarget.KNOWLEDGE_STORE)
        assert policy.mode == WritebackMode.REVIEW_REQUIRED


# ══════════════════════════════════════════════════════════
# DistillationWriteback
# ══════════════════════════════════════════════════════════

class TestDistillationWriteback:

    @pytest.fixture
    def memory(self):
        return FakeMemoryGateway()

    @pytest.fixture
    def ks(self):
        return FakeKnowledgeStore()

    @pytest.fixture
    def audit(self):
        return FakeAuditStore()

    @pytest.fixture
    def dwb(self, memory, ks, audit):
        policy = WritebackPolicyRegistry.defaults()
        # Lower memory threshold so test data passes
        policy.policies["memory"] = WritebackPolicy(
            target=WritebackTarget.MEMORY,
            mode=WritebackMode.AUTO,
            min_confidence=0.2,
        )
        # Override KNOWLEDGE_STORE to auto for testing
        policy.policies["knowledge_store"] = WritebackPolicy(
            target=WritebackTarget.KNOWLEDGE_STORE,
            mode=WritebackMode.AUTO,
            min_confidence=0.5,
        )
        return DistillationWriteback(
            memory_gateway=memory,
            knowledge_store=ks,
            audit_store=audit,
            policy=policy,
        )

    async def test_write_back_full(self, dwb, memory, ks, audit):
        knowledge = FakeDistilledKnowledge()
        entries = await dwb.write_back(knowledge)

        # Should produce entries for 2 playbook entries + 1 cp + 2 tp (KB entry skips in dry_run)
        assert len(entries) >= 5

        # Check types
        memory_entries = [e for e in entries if e.target == WritebackTarget.MEMORY]
        assert len(memory_entries) >= 4  # 2 pb entries + 1 cp + 2 tp

        ks_entries = [e for e in entries if e.target == WritebackTarget.KNOWLEDGE_STORE]
        assert len(ks_entries) >= 1

        # Memory should have ingested
        assert len(memory.distilled) > 0

        # Knowledge store should have entries
        assert len(ks.entries) > 0

        # Audit should have entries
        assert len(audit.entries) > 0

    async def test_dry_run(self, dwb, memory, ks, audit):
        knowledge = FakeDistilledKnowledge()
        entries = await dwb.write_back(knowledge, dry_run=True)

        # Entries produced but nothing committed
        assert len(entries) >= 5
        # Memory not updated (dry run)
        assert len(memory.distilled) == 0
        assert len(ks.entries) == 0

    async def test_confidence_below_threshold_requires_review(self, memory, ks, audit):
        """Entries with low confidence should get review_required."""
        strict_policy = WritebackPolicyRegistry(policies={
            "memory": WritebackPolicy(
                target=WritebackTarget.MEMORY,
                mode=WritebackMode.AUTO,
                min_confidence=0.8,  # Very high bar
            ),
            "knowledge_store": WritebackPolicy(
                target=WritebackTarget.KNOWLEDGE_STORE,
                mode=WritebackMode.DISABLED,
            ),
            "audit": WritebackPolicy(
                target=WritebackTarget.AUDIT,
                mode=WritebackMode.AUTO,
                min_confidence=0.0,
            ),
        })
        dwb = DistillationWriteback(
            memory_gateway=memory,
            knowledge_store=ks,
            audit_store=audit,
            policy=strict_policy,
        )

        knowledge = FakeDistilledKnowledge()
        entries = await dwb.write_back(knowledge)

        # Low-confidence objection (0.35) should be review_required
        price_entries = [e for e in entries
                         if e.signal_type == "objection_playbook"
                         and "价格" in (e.source_key or "")]
        # They're all review_required because min_confidence is 0.8
        memory_entries = [e for e in entries if e.target == WritebackTarget.MEMORY]
        for e in memory_entries:
            assert e.status in ("review_required", "skipped")

    async def test_no_gateways(self):
        """Writeback without any gateways should produce entries with review_required."""
        dwb = DistillationWriteback(
            memory_gateway=None,
            knowledge_store=None,
            audit_store=None,
        )
        knowledge = FakeDistilledKnowledge()
        entries = await dwb.write_back(knowledge)

        # Entries still produced, but all stuck
        assert len(entries) >= 6
        pending = [e for e in entries if e.status in ("review_required", "skipped")]
        assert len(pending) > 0


# ══════════════════════════════════════════════════════════
# MemoryWriteback
# ══════════════════════════════════════════════════════════

class TestMemoryWriteback:

    @pytest.fixture
    def mwb(self):
        memory = FakeMemoryGateway()
        return MemoryWriteback(memory_gateway=memory)

    async def test_update_field(self, mwb):
        entry = await mwb.update_memory_summary(
            "lead_001", "overall_intent_score", 0.85, old_value=0.5,
        )
        assert entry.status == "committed"
        assert entry.lead_id == "lead_001"
        assert entry.field == "overall_intent_score"
        assert entry.new_value == 0.85

    async def test_rejects_transcript_field(self, mwb):
        """Transcript field MUST be blocked."""
        entry = await mwb.update_memory_summary(
            "lead_001", "transcript", "actual conversation text",
        )
        assert entry.status == "rejected"
        assert "blocked" in entry.error.lower()

    async def test_rejects_raw_transcript(self, mwb):
        entry = await mwb.update_memory_summary(
            "lead_001", "raw_transcript", "...",
        )
        assert entry.status == "rejected"

    async def test_rejects_full_text(self, mwb):
        entry = await mwb.update_memory_summary(
            "lead_001", "full_text", "...",
        )
        assert entry.status == "rejected"

    async def test_update_bant(self, mwb):
        entries = await mwb.update_bant(
            "lead_001",
            budget="qualified_budget",
            authority="no_authority",
            need="qualified_need",
            timeline=None,  # not set
        )
        assert len(entries) == 3
        assert all(e.status == "committed" for e in entries)

    async def test_update_intent(self, mwb):
        entries = await mwb.update_intent("lead_001", 0.9, trend="up")
        assert len(entries) == 2
        assert entries[0].field == "overall_intent_score"
        assert entries[1].field == "intent_trend"

    async def test_add_objection(self, mwb):
        entry = await mwb.add_objection("lead_001", "价格太高", "pattern_001")
        assert entry.status == "committed"
        assert entry.new_value == "价格太高"

    async def test_no_memory_gateway(self):
        mwb = MemoryWriteback(memory_gateway=None)
        entry = await mwb.update_memory_summary("lead_001", "intent_score", 0.5)
        assert entry.status == "review_required"

    async def test_disabled_policy(self):
        policy = WritebackPolicyRegistry(policies={
            "memory": WritebackPolicy(
                target=WritebackTarget.MEMORY,
                mode=WritebackMode.DISABLED,
            ),
        })
        mwb = MemoryWriteback(memory_gateway=FakeMemoryGateway(), policy=policy)
        entry = await mwb.update_memory_summary("lead_001", "intent_score", 0.5)
        assert entry.status == "skipped"


# ══════════════════════════════════════════════════════════
# KnowledgeWriteback
# ══════════════════════════════════════════════════════════

class TestKnowledgeWriteback:

    @pytest.fixture
    def kwb(self):
        ks = FakeKnowledgeStore()
        return KnowledgeWriteback(knowledge_store=ks)

    async def test_upsert_knowledge(self, kwb):
        content = {
            "objection_topic": "价格太高",
            "best_responses": ["强调总拥有成本", "对比竞品性价比"],
            "overcome_rate": 0.45,
        }
        entry = await kwb.upsert(
            knowledge_type="objection_playbook",
            knowledge_id="pb_price_001",
            content=content,
            confidence=0.7,
            source_job_id="job_001",
            sample_count=25,
        )
        assert entry.status == "committed"
        assert entry.contains_transcript is False

    async def test_blocks_transcript_content(self, kwb):
        """Knowledge writeback MUST reject transcript-containing content."""
        content = {
            "objection_topic": "价格",
            "transcript": "客户说太贵了，我们解释了定价策略后客户表示理解",
            "overcome_rate": 0.5,
        }
        entry = await kwb.upsert(
            knowledge_type="objection_playbook",
            knowledge_id="pb_001",
            content=content,
        )
        assert entry.status == "rejected"
        assert entry.contains_transcript is True
        assert "blocked" in entry.error.lower()

    async def test_blocks_nested_transcript(self, kwb):
        """Transcript in nested dicts should also be blocked."""
        content = {
            "playbook": {
                "entries": [
                    {"topic": "价格", "raw_transcript": "客户的原话..."},
                ],
            },
        }
        entry = await kwb.upsert(
            knowledge_type="objection_playbook",
            knowledge_id="pb_001",
            content=content,
        )
        assert entry.status == "rejected"
        assert entry.contains_transcript is True

    async def test_blocks_conversation_text(self, kwb):
        content = {"topic": "价格", "conversation_text": "B: 太贵了\nA: 我们可以..."}
        entry = await kwb.upsert("objection_playbook", "pb_001", content)
        assert entry.status == "rejected"

    async def test_no_knowledge_store(self):
        kwb = KnowledgeWriteback(knowledge_store=None)
        entry = await kwb.upsert("obj", "id_001", {"topic": "价格"})
        assert entry.status == "review_required"


# ══════════════════════════════════════════════════════════
# Transcript blocking — cross-layer
# ══════════════════════════════════════════════════════════

class TestTranscriptBlocking:

    async def test_memory_writeback_blocks_all_transcript_fields(self):
        mwb = MemoryWriteback(memory_gateway=FakeMemoryGateway())
        forbidden = ["transcript", "raw_transcript", "full_text", "conversation_text"]
        for field in forbidden:
            entry = await mwb.update_memory_summary("lead_001", field, "test")
            assert entry.status == "rejected", f"Field '{field}' should be blocked"

    async def test_knowledge_writeback_blocks_all_transcript_keys(self, kwb=None):
        if kwb is None:
            kwb = KnowledgeWriteback(knowledge_store=FakeKnowledgeStore())
        forbidden_keys = ["transcript", "raw_transcript", "full_text",
                          "conversation_text", "dialog_text", "speech_text", "utterances"]
        for key in forbidden_keys:
            content = {"topic": "价格", key: "some text"}
            entry = await kwb.upsert("obj", "id_001", content)
            assert entry.status == "rejected", f"Key '{key}' should be blocked"

    async def test_allowed_fields_pass(self):
        mwb = MemoryWriteback(memory_gateway=FakeMemoryGateway())
        allowed = ["intent_score", "bant_budget", "common_objections",
                   "best_talking_points", "company_name"]
        for field in allowed:
            entry = await mwb.update_memory_summary("lead_001", field, "value")
            assert entry.status == "committed", f"Field '{field}' should pass"
