# tests/test_identity_graph.py
"""Identity Graph & Merger tests — v2 minimal identity management."""

from __future__ import annotations

import pytest

from byou.intake.identity.graph import (
    BindingType,
    IdentityBinding,
    IdentityGraph,
    IdentityNode,
    MatchDecisionType,
    NodeType,
)
from byou.intake.identity.merger import IdentityMerger


# ══════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════

def _uid_node(uid: str, label: str = "", aliases: list | None = None):
    return IdentityNode(
        node_id=uid, node_type=NodeType.UID,
        label=label or uid, aliases=aliases or [],
    )


def _vpid_node(vpid: str):
    return IdentityNode(node_id=vpid, node_type=NodeType.VPID, label=vpid)


# ══════════════════════════════════════════════════════════
# IdentityGraph
# ══════════════════════════════════════════════════════════

class TestIdentityGraph:
    def test_add_and_get_node(self):
        graph = IdentityGraph()
        node = _uid_node("uid_001", "张三")
        graph.add_node(node)
        assert graph.get_node("uid_001") is node

    def test_node_count(self):
        graph = IdentityGraph()
        graph.add_node(_uid_node("uid_001"))
        graph.add_node(_uid_node("uid_002"))
        assert graph.node_count == 2

    def test_find_by_alias(self):
        graph = IdentityGraph()
        graph.add_node(_uid_node("uid_001", "张三", ["三哥", "zhangsan"]))
        results = graph.find_by_alias("三哥")
        assert len(results) == 1
        assert results[0].node_id == "uid_001"

    def test_find_by_type(self):
        graph = IdentityGraph()
        graph.add_node(_uid_node("uid_001"))
        graph.add_node(_uid_node("uid_002"))
        graph.add_node(_vpid_node("vpid_001"))
        uids = graph.find_by_type(NodeType.UID)
        assert len(uids) == 2
        vpids = graph.find_by_type(NodeType.VPID)
        assert len(vpids) == 1

    def test_add_binding(self):
        graph = IdentityGraph()
        graph.add_node(_uid_node("uid_001"))
        graph.add_node(_vpid_node("vpid_001"))
        binding = IdentityBinding(
            source_id="vpid_001", target_id="uid_001",
            binding_type=BindingType.VOICEPRINT_MATCH,
            confidence=0.95,
        )
        graph.add_binding(binding)
        bindings = graph.get_bindings_for("uid_001")
        assert len(bindings) == 1
        assert bindings[0].binding_type == BindingType.VOICEPRINT_MATCH

    def test_get_bindings_by_type(self):
        graph = IdentityGraph()
        graph.add_node(_uid_node("uid_001"))
        graph.add_node(_vpid_node("vpid_001"))
        graph.add_binding(IdentityBinding(
            source_id="vpid_001", target_id="uid_001",
            binding_type=BindingType.VOICEPRINT_MATCH, confidence=0.95,
        ))
        graph.add_binding(IdentityBinding(
            source_id="vpid_001", target_id="uid_001",
            binding_type=BindingType.MANUAL, confidence=1.0,
        ))
        voiceprint_bindings = graph.get_bindings_by_type("uid_001", BindingType.VOICEPRINT_MATCH)
        assert len(voiceprint_bindings) == 1
        manual_bindings = graph.get_bindings_by_type("uid_001", BindingType.MANUAL)
        assert len(manual_bindings) == 1

    def test_deactivate_binding(self):
        graph = IdentityGraph()
        graph.add_node(_uid_node("uid_001"))
        graph.add_node(_vpid_node("vpid_001"))
        binding = IdentityBinding(
            source_id="vpid_001", target_id="uid_001",
            binding_type=BindingType.VOICEPRINT_MATCH, confidence=0.95,
        )
        graph.add_binding(binding)
        graph.deactivate_binding(binding.binding_id)
        active = graph.get_bindings_by_type("uid_001", BindingType.VOICEPRINT_MATCH)
        assert len(active) == 0  # deactivated, not deleted

    def test_remove_node_cleans_bindings(self):
        graph = IdentityGraph()
        graph.add_node(_uid_node("uid_001"))
        graph.add_node(_vpid_node("vpid_001"))
        graph.add_binding(IdentityBinding(
            source_id="vpid_001", target_id="uid_001",
            binding_type=BindingType.VOICEPRINT_MATCH, confidence=0.95,
        ))
        graph.remove_node("uid_001")
        assert graph.get_node("uid_001") is None
        assert graph.binding_count == 0

    def test_register_and_match_voiceprint(self):
        graph = IdentityGraph()
        graph.register_voiceprint("uid_001", [0.1, 0.2, 0.3])
        graph.register_voiceprint("uid_002", [-0.7, 0.5, 0.3])  # near-orthogonal to uid_001

        # Query with embedding close to uid_001 — should auto_match because
        # uid_002 is too far away to be a candidate
        result = graph.match_voiceprint([0.1, 0.2, 0.3])
        assert result.decision == MatchDecisionType.AUTO_MATCH
        assert result.candidates[0]["uid"] == "uid_001"

    def test_voiceprint_no_match(self):
        graph = IdentityGraph()
        # No registered voiceprints
        result = graph.match_voiceprint([0.5, 0.5, 0.5])
        assert result.decision == MatchDecisionType.NO_MATCH

    def test_voiceprint_ambiguous(self):
        graph = IdentityGraph()
        graph.register_voiceprint("uid_001", [0.1, 0.2, 0.3])
        graph.register_voiceprint("uid_002", [0.12, 0.21, 0.32])  # very close to uid_001

        result = graph.match_voiceprint([0.11, 0.21, 0.31])
        # Both should score high
        assert result.requires_review
        assert result.decision == MatchDecisionType.AMBIGUOUS
        assert len(result.candidates) >= 2

    def test_stats(self):
        graph = IdentityGraph()
        graph.add_node(_uid_node("uid_001"))
        graph.add_node(_uid_node("uid_002"))
        graph.add_node(_vpid_node("vpid_001"))
        stats = graph.stats()
        assert stats["nodes"] == 3
        assert stats["by_type"]["uid"] == 2
        assert stats["by_type"]["vpid"] == 1


# ══════════════════════════════════════════════════════════
# IdentityMerger
# ══════════════════════════════════════════════════════════

class TestIdentityMerger:
    def test_merge_two_uids(self):
        graph = IdentityGraph()
        graph.add_node(_uid_node("uid_alpha", "张三", ["三哥"]))
        graph.add_node(_uid_node("uid_beta", "张工", ["zhang"]))
        graph.add_node(_vpid_node("vpid_001"))
        graph.add_binding(IdentityBinding(
            source_id="vpid_001", target_id="uid_alpha",
            binding_type=BindingType.VOICEPRINT_MATCH, confidence=0.95,
        ))

        merger = IdentityMerger(graph)
        result = merger.merge(source_uid="uid_alpha", target_uid="uid_beta")

        assert result.success
        assert result.bindings_migrated == 1

        # Source is gone
        assert graph.get_node("uid_alpha") is None

        # Target gained aliases
        target = graph.get_node("uid_beta")
        assert "张三" in target.aliases or "三哥" in target.aliases

        # Binding migrated to target
        bindings = graph.get_bindings_for("uid_beta")
        vp_bindings = graph.get_bindings_by_type("uid_beta", BindingType.VOICEPRINT_MATCH)
        assert len(vp_bindings) >= 1
        assert vp_bindings[0].target_id == "uid_beta" or vp_bindings[0].source_id == "uid_beta"

        # Merge event binding created — preserved as audit record even after source removal
        merge_bindings = [b for b in graph._bindings.values() if b.binding_type == BindingType.MERGED_INTO]
        assert len(merge_bindings) >= 1, f"Expected at least 1 MERGED_INTO binding, got {len(merge_bindings)}"

    def test_merge_missing_source(self):
        graph = IdentityGraph()
        graph.add_node(_uid_node("uid_beta"))
        merger = IdentityMerger(graph)
        result = merger.merge(source_uid="nonexistent", target_uid="uid_beta")
        assert not result.success

    def test_merge_missing_target(self):
        graph = IdentityGraph()
        graph.add_node(_uid_node("uid_alpha"))
        merger = IdentityMerger(graph)
        result = merger.merge(source_uid="uid_alpha", target_uid="nonexistent")
        assert not result.success

    def test_suggest_merge_shared_aliases(self):
        graph = IdentityGraph()
        graph.add_node(_uid_node("uid_alpha", "张三", ["zhangsan", "13800138000"]))
        graph.add_node(_uid_node("uid_beta", "张三", ["san.zhang"]))
        merger = IdentityMerger(graph)

        result = merger.suggest_merge("uid_alpha", "uid_beta")
        assert result.requires_review
        assert result.decision == MatchDecisionType.AUTO_MATCH

    def test_suggest_merge_no_shared_aliases(self):
        graph = IdentityGraph()
        graph.add_node(_uid_node("uid_alpha", "张三"))
        graph.add_node(_uid_node("uid_beta", "李四"))
        merger = IdentityMerger(graph)

        result = merger.suggest_merge("uid_alpha", "uid_beta")
        assert not result.requires_review
        assert result.decision == MatchDecisionType.NO_MATCH
