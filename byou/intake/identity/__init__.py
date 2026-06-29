# byou/intake/identity/__init__.py
"""Intake Identity Graph — UID management, binding, merge, writeback, replay snapshot.

Phase 3 v3: identity ↔ review ↔ replay closed loop.
  - IdentityGraph: in-memory graph of UID/BID/VPID/PersonCandidate nodes
  - IdentityBinding: typed edges between nodes
  - IdentityMerger: merge two UIDs, resolve conflicts
  - IdentityWriteback: review resolution → graph update
  - IdentityMergeResult: full merge outcome with snapshots
  - IdentityReplaySnapshot: point-in-time graph snapshot for replay
  - IdentityParticipantBinder: bind resolved identities to session participants
  - IdentityCascade: downstream updates after identity merge
"""

from byou.intake.identity.graph import (
    BindingType,
    IdentityBinding,
    IdentityGraph,
    MatchDecisionType,
    MatchResult,
    MergeResult,
    NodeType,
)
from byou.intake.identity.merger import IdentityMerger
from byou.intake.identity.writeback import (
    IdentityBindingUpdate,
    IdentityCascade,
    IdentityMergeResult,
    IdentityParticipantBinder,
    IdentityReplaySnapshot,
    IdentityWriteback,
)

__all__ = [
    "BindingType",
    "IdentityBinding",
    "IdentityBindingUpdate",
    "IdentityCascade",
    "IdentityGraph",
    "IdentityMergeResult",
    "IdentityMerger",
    "IdentityParticipantBinder",
    "IdentityReplaySnapshot",
    "IdentityWriteback",
    "MatchDecisionType",
    "MatchResult",
    "MergeResult",
    "NodeType",
]
