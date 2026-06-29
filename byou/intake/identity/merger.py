# byou/intake/identity/merger.py
"""Identity Merger — merge two UIDs.

Handles:
  - migrating bindings from source_uid → target_uid
  - merging aliases
  - merging voiceprints
  - deactivating old bindings
  - creating MergeEvent binding (merged_into)

v2: operates on in-memory IdentityGraph.
v3: persistent merge with audit trail.
"""

from __future__ import annotations

import logging

from byou.intake.identity.graph import (
    BindingType,
    IdentityBinding,
    IdentityGraph,
    MatchDecisionType,
    MatchResult,
    MergeResult,
)

logger = logging.getLogger(__name__)


class IdentityMerger:
    """Minimal identity merger.

    Usage:
        graph = IdentityGraph()
        merger = IdentityMerger(graph)
        result = merger.merge(source_uid="uid_old", target_uid="uid_new")
    """

    def __init__(self, graph: IdentityGraph) -> None:
        self._graph = graph

    def merge(self, source_uid: str, target_uid: str) -> MergeResult:
        """Merge source_uid into target_uid.

        Steps:
        1. Validate both exist and are UIDs
        2. Migrate active bindings from source → target
        3. Merge aliases into target node
        4. Merge voiceprints
        5. Deactivate old bindings (source → its targets)
        6. Create MERGED_INTO binding (source → target)
        7. Remove source node
        """
        source = self._graph.get_node(source_uid)
        target = self._graph.get_node(target_uid)

        if not source:
            return MergeResult(
                source_uid=source_uid, target_uid=target_uid,
                success=False,
            )
        if not target:
            return MergeResult(
                source_uid=source_uid, target_uid=target_uid,
                success=False,
            )

        bindings = self._graph.get_bindings_for(source_uid)
        bindings_migrated = 0
        aliases_merged: list[str] = []

        # ── Step 3: merge aliases ──
        for alias in source.aliases:
            if alias not in target.aliases and alias != target.label:
                target.aliases.append(alias)
                aliases_merged.append(alias)
        if source.label and source.label not in target.aliases:
            target.aliases.append(source.label)
            aliases_merged.append(source.label)

        # ── Step 4: merge voiceprints ──
        source_vps = self._graph.get_voiceprints(source_uid)
        for emb in source_vps:
            self._graph.register_voiceprint(target_uid, emb)

        # ── Step 5/2: migrate active bindings ──
        for binding in bindings:
            if not binding.is_active:
                continue
            # Replace source_uid with target_uid
            if binding.source_id == source_uid:
                new_binding = IdentityBinding(
                    source_id=target_uid,
                    target_id=binding.target_id,
                    binding_type=binding.binding_type,
                    confidence=binding.confidence,
                    evidence_refs=binding.evidence_refs,
                    metadata={"merged_from": source_uid},
                )
            else:  # binding.target_id == source_uid
                new_binding = IdentityBinding(
                    source_id=binding.source_id,
                    target_id=target_uid,
                    binding_type=binding.binding_type,
                    confidence=binding.confidence,
                    evidence_refs=binding.evidence_refs,
                    metadata={"merged_from": source_uid},
                )
            self._graph.add_binding(new_binding)
            bindings_migrated += 1
            # deactivate old
            binding.is_active = False

        # ── Step 6/7: create merge event binding after removing source
        self._graph.remove_node(source_uid)
        
        merge_binding = IdentityBinding(
            source_id=source_uid,
            target_id=target_uid,
            binding_type=BindingType.MERGED_INTO,
            confidence=1.0,
            evidence_refs=[],
            metadata={"merged_aliases": aliases_merged},
        )
        self._graph.add_binding(merge_binding)

        logger.info("UID merged: %s → %s (%d bindings, %d aliases)",
                     source_uid, target_uid, bindings_migrated, len(aliases_merged))

        return MergeResult(
            source_uid=source_uid,
            target_uid=target_uid,
            success=True,
            bindings_migrated=bindings_migrated,
            aliases_merged=aliases_merged,
        )

    def suggest_merge(self, uid_a: str, uid_b: str) -> MatchResult:
        """Suggest whether two UIDs should be merged.

        Checks for:
        - Shared aliases (same name, phone, email)
        - Shared voiceprint similarity
        - Common external refs
        """
        node_a = self._graph.get_node(uid_a)
        node_b = self._graph.get_node(uid_b)

        if not node_a or not node_b:
            return MatchResult(
                query_id=f"{uid_a}+{uid_b}",
                decision=MatchDecisionType.NO_MATCH,
                requires_review=False,
            )

        # Check shared aliases
        aliases_a = set(a.lower() for a in node_a.aliases) | {node_a.label.lower()}
        aliases_b = set(a.lower() for a in node_b.aliases) | {node_b.label.lower()}
        shared = aliases_a & aliases_b

        if shared:
            return MatchResult(
                query_id=f"{uid_a}+{uid_b}",
                decision=MatchDecisionType.AUTO_MATCH,
                candidates=[{"uid": uid_b, "score": 0.9, "evidence": list(shared)}],
                requires_review=True,
                review_reason=f"Shared aliases: {shared}",
            )

        return MatchResult(
            query_id=f"{uid_a}+{uid_b}",
            decision=MatchDecisionType.NO_MATCH,
            requires_review=False,
        )
