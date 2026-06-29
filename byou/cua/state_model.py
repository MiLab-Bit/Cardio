# byou/cua/state_model.py
"""CUA State Model — 页面状态建模 + 聚类 + 可用动作识别.

Replaces the prompt-based planning in planning.py with proper state modeling:

1. StateModel: structured representation of a page state
   - URL, title, DOM fingerprint, visible text, form fields, links
2. StateSimilarity: compute similarity between two states
3. StateClusterer: group similar states (avoids re-planning for seen states)
4. ActionAvailabilityDetector: infer available actions from state
5. StateGraph: build a graph of (state → action → next_state)
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════
# StateModel
# ════════════════════════════════════════════════════════

@dataclass
class StateModel:
    """Structured representation of a browser page state.

    Attributes:
        state_id:     hash-based ID for deduplication
        url:         current page URL
        title:        page title
        dom_hash:    fingerprint of DOM structure (fast change detection)
        text_hash:   fingerprint of visible text (content change detection)
        elements:    list of interactive elements {type, text, selector, enabled}
        forms:       list of form fields {name, type, required, value}
        links:       list of links {text, href}
        screenshot_hash:  optional screenshot perceptual hash
        metadata:    arbitrary extra data
    """

    url: str = ""
    title: str = ""
    dom_hash: str = ""
    text_hash: str = ""
    elements: list[dict[str, Any]] = field(default_factory=list)
    forms: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)
    screenshot_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def state_id(self) -> str:
        """Deterministic ID based on URL + DOM hash."""
        raw = f"{self.url}|{self.dom_hash}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @property
    def element_count(self) -> int:
        return len(self.elements)

    @property
    def form_count(self) -> int:
        return len(self.forms)

    def get_elements_by_type(self, element_type: str) -> list[dict[str, Any]]:
        return [e for e in self.elements if e.get("type") == element_type]

    def get_element_by_text(self, text: str, fuzzy: bool = True) -> dict[str, Any] | None:
        """Find an element by its visible text."""
        for e in self.elements:
            e_text = e.get("text", "")
            if not e_text:
                continue
            if text == e_text:
                return e
            if fuzzy and text in e_text:
                return e
        return None

    def summarize(self) -> dict[str, Any]:
        """Human-readable summary of the state."""
        return {
            "state_id": self.state_id,
            "url": self.url,
            "title": self.title,
            "element_count": self.element_count,
            "form_count": self.form_count,
            "link_count": len(self.links),
            "elements": [f"{e.get('type','?')}:{e.get('text','')}" for e in self.elements[:10]],
        }


# ════════════════════════════════════════════════════════
# StateBuilder — builds StateModel from Perception output
# ════════════════════════════════════════════════════════

class StateBuilder:
    """Build a StateModel from perception-layer output.

    Perception output format:
      {url, title, elements: [{type, text, selector, ...}], dom_text, ...}
    """

    @staticmethod
    def from_perception(perception: dict[str, Any]) -> StateModel:
        """Build StateModel from perception dict."""
        elements = perception.get("elements", [])
        forms = perception.get("forms", [])
        links = perception.get("links", [])

        # DOM fingerprint: hash of tag sequence
        dom_text = perception.get("dom_text", "")
        dom_hash = hashlib.md5(dom_text.encode()).hexdigest()[:12] if dom_text else ""

        # Text fingerprint: hash of visible text
        visible_text = perception.get("visible_text", "")
        text_hash = hashlib.md5(visible_text.encode()).hexdigest()[:12] if visible_text else ""

        return StateModel(
            url=perception.get("url", ""),
            title=perception.get("title", ""),
            dom_hash=dom_hash,
            text_hash=text_hash,
            elements=elements,
            forms=forms,
            links=links,
            screenshot_hash=perception.get("screenshot_hash", ""),
            metadata={
                "perception_raw_keys": list(perception.keys()),
            },
        )

    @staticmethod
    def from_playwright(page: Any) -> StateModel:
        """Build StateModel directly from a Playwright page object.

        NOTE: this requires an async context. Use from_playwright_async().
        """
        raise NotImplementedError("Use from_playwright_async()")


# ════════════════════════════════════════════════════════
# StateSimilarity
# ════════════════════════════════════════════════════════

def state_similarity(a: StateModel, b: StateModel) -> float:
    """Compute similarity between two states in [0, 1].

    Weighted combination:
      - URL match      (weight 0.3)
      - DOM hash match (weight 0.3)
      - Text similarity (weight 0.2)
      - Element overlap (weight 0.2)
    """
    if not a or not b:
        return 0.0

    # URL similarity
    url_score = 1.0 if a.url == b.url else _url_similarity(a.url, b.url)

    # DOM hash exact match
    dom_score = 1.0 if a.dom_hash and a.dom_hash == b.dom_hash else 0.0

    # Text similarity (via SequenceMatcher on text hashes, or raw text)
    if a.text_hash and b.text_hash:
        text_score = 1.0 if a.text_hash == b.text_hash else 0.3
    else:
        text_score = 0.0

    # Element overlap (Jaccard on element "signatures")
    elem_sig_a = {_elem_sig(e) for e in a.elements}
    elem_sig_b = {_elem_sig(e) for e in b.elements}
    if elem_sig_a and elem_sig_b:
        elem_score = len(elem_sig_a & elem_sig_b) / len(elem_sig_a | elem_sig_b)
    else:
        elem_score = 0.0

    # Weighted combination
    overall = url_score * 0.3 + dom_score * 0.3 + text_score * 0.2 + elem_score * 0.2
    return min(overall, 1.0)


def _url_similarity(u1: str, u2: str) -> float:
    """Compare two URLs, ignoring query params and fragments."""
    from urllib.parse import urlparse

    p1 = urlparse(u1)
    p2 = urlparse(u2)
    # Compare scheme + netloc + path
    base1 = f"{p1.scheme}://{p1.netloc}{p1.path}"
    base2 = f"{p2.scheme}://{p2.netloc}{p2.path}"
    if base1 == base2:
        return 0.9  # same page, different query params
    return SequenceMatcher(None, base1, base2).ratio() * 0.8


def _elem_sig(e: dict[str, Any]) -> str:
    """Create a comparable signature for an element."""
    return f"{e.get('type','?')}:{e.get('text','')}"


# ════════════════════════════════════════════════════════
# StateClusterer
# ════════════════════════════════════════════════════════

class StateClusterer:
    """Cluster similar states to avoid re-planning.

    Maintains a list of "canonical states".  When a new state arrives,
    check if it matches an existing cluster (similarity ≥ threshold).
    If yes → return the canonical state ID (reuse plan).
    If no  → create a new canonical state.
    """

    def __init__(self, similarity_threshold: float = 0.85):
        self._threshold = similarity_threshold
        self._canonical: list[tuple[str, StateModel]] = []  # [(state_id, StateModel)]
        self._cluster_sizes: dict[str, int] = defaultdict(int)

    def find_cluster(self, state: StateModel) -> str | None:
        """Find the canonical state ID for a given state.

        Returns the canonical state_id if match ≥ threshold, else None.
        """
        for cid, canonical_state in self._canonical:
            sim = state_similarity(state, canonical_state)
            if sim >= self._threshold:
                self._cluster_sizes[cid] += 1
                logger.debug("State matched cluster %s (sim=%.3f)", cid, sim)
                return cid
        return None

    def add_state(self, state: StateModel) -> str:
        """Add a new state and return its canonical ID."""
        cid = state.state_id
        self._canonical.append((cid, state))
        self._cluster_sizes[cid] = 1
        logger.info("New state cluster: %s (total=%d)", cid, len(self._canonical))
        return cid

    def get_or_add(self, state: StateModel) -> tuple[str, bool]:
        """Find or create a cluster for the state.

        Returns (canonical_id, is_new).
        """
        cid = self.find_cluster(state)
        if cid:
            return cid, False
        return self.add_state(state), True

    def get_canonical_state(self, cid: str) -> StateModel | None:
        for known_id, state in self._canonical:
            if known_id == cid:
                return state
        return None

    def stats(self) -> dict[str, Any]:
        return {
            "cluster_count": len(self._canonical),
            "total_states": sum(self._cluster_sizes.values()),
            "cluster_sizes": dict(self._cluster_sizes),
        }


# ════════════════════════════════════════════════════════
# ActionAvailabilityDetector
# ════════════════════════════════════════════════════════

@dataclass
class AvailableAction:
    """An action available in the current state."""

    action_type: str  # click | type | select | navigate | scroll | wait | submit
    target: str  # element selector or description
    target_text: str = ""  # visible text of target
    description: str = ""
    preconditions: list[str] = field(default_factory=list)
    is_enabled: bool = True


class ActionAvailabilityDetector:
    """Infer available actions from a StateModel.

    Rules:
      - Buttons with text → click actions
      - Input fields        → type actions
      - Select elements     → select actions
      - Links              → click or navigate actions
      - Forms              → submit action
      - Page has scrollbar → scroll action
      - Always available   → wait, screenshot
    """

    def detect(self, state: StateModel) -> list[AvailableAction]:
        """Return all actions available in the given state."""
        actions: list[AvailableAction] = []

        # Clickable elements (buttons, links)
        for elem in state.elements:
            elem_type = elem.get("type", "")
            text = elem.get("text", "")
            selector = elem.get("selector", "")

            if elem_type in ("button", "link", "a"):
                actions.append(AvailableAction(
                    action_type="click",
                    target=selector or text,
                    target_text=text,
                    description=f"点击 {text}" if text else f"点击 {elem_type}",
                    is_enabled=elem.get("enabled", True),
                ))

            elif elem_type in ("input", "textarea"):
                actions.append(AvailableAction(
                    action_type="type",
                    target=selector or text,
                    target_text=text,
                    description=f"输入文本到 {text}" if text else "输入文本",
                    preconditions=["element_is_visible", "element_is_enabled"],
                ))

            elif elem_type == "select":
                actions.append(AvailableAction(
                    action_type="select",
                    target=selector or text,
                    target_text=text,
                    description=f"选择下拉选项 {text}",
                ))

        # Form submit
        if state.forms:
            actions.append(AvailableAction(
                action_type="submit",
                target="form",
                description="提交表单",
            ))

        # Always-available actions
        actions.append(AvailableAction(
            action_type="wait", target="", description="等待页面加载",
        ))
        actions.append(AvailableAction(
            action_type="screenshot", target="", description="截图当前页面",
        ))
        if state.url:
            actions.append(AvailableAction(
                action_type="navigate", target=state.url, description=f"刷新 {state.url}",
            ))

        return actions

    def find_action_by_text(self, state: StateModel, text: str) -> AvailableAction | None:
        """Find an available action matching the given text."""
        for action in self.detect(state):
            if text in action.target_text or text in action.description:
                return action
        return None


# ════════════════════════════════════════════════════════
# StateGraph — state transition graph
# ════════════════════════════════════════════════════════

from dataclasses import dataclass as _dataclass


@_dataclass
class StateTransition:
    """A recorded transition: state A --[action]--> state B."""

    from_state_id: str
    action: dict[str, Any]
    to_state_id: str
    success: bool = True
    timestamp: str = ""
    task_id: str = ""


class StateGraph:
    """Graph of (state → action → next_state) transitions.

    Used for:
      - Learning: avoid retrying failed transitions
      - Planning: suggest next action based on seen transitions
      - Debugging: visualize page flow
    """

    def __init__(self):
        self._transitions: list[StateTransition] = []
        self._state_cache: dict[str, StateModel] = {}

    def record_transition(
        self,
        from_state: StateModel,
        action: dict[str, Any],
        to_state: StateModel,
        success: bool = True,
        task_id: str = "",
    ) -> None:
        """Record a state transition."""
        transition = StateTransition(
            from_state_id=from_state.state_id,
            action=action,
            to_state_id=to_state.state_id,
            success=success,
            task_id=task_id,
        )
        self._transitions.append(transition)
        self._state_cache[from_state.state_id] = from_state
        self._state_cache[to_state.state_id] = to_state

    def get_transitions_from(self, state_id: str) -> list[StateTransition]:
        """Get all transitions from a given state."""
        return [t for t in self._transitions if t.from_state_id == state_id]

    def get_successful_transitions_from(self, state_id: str) -> list[StateTransition]:
        """Get successful transitions from a state (for re-use)."""
        return [t for t in self._transitions if t.from_state_id == state_id and t.success]

    def find_path(self, from_state_id: str, to_state_id: str) -> list[StateTransition]:
        """Find a path between two states (BFS)."""
        from collections import deque

        queue = deque([(from_state_id, [])])
        visited = {from_state_id}

        while queue:
            current_id, path = queue.popleft()
            if current_id == to_state_id:
                return path

            for t in self.get_successful_transitions_from(current_id):
                if t.to_state_id not in visited:
                    visited.add(t.to_state_id)
                    queue.append((t.to_state_id, path + [t]))

        return []  # no path found

    def stats(self) -> dict[str, Any]:
        return {
            "transition_count": len(self._transitions),
            "unique_states": len(self._state_cache),
            "success_rate": (
                sum(1 for t in self._transitions if t.success) / len(self._transitions)
                if self._transitions
                else 0.0
            ),
        }
