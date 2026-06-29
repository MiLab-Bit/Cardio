# byou/core/vector_store.py
"""Lightweight vector store — embedding storage + cosine similarity search.

Design:
  - No external vector DB required (uses numpy).
  - Compatible with ChromaDB/FAISS API (easy to migrate later).
  - Stores (id, embedding, metadata) tuples.
  - Supports: add, get, search (cosine), delete.

Usage:
    store = VectorStore(dim=1536)
    store.add("uid_001", embedding, metadata={"name": "Zhang Wei"})
    results = store.search(query_embedding, top_k=5)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class VectorStore:
    """In-memory vector store with optional disk persistence.

    Uses numpy for fast cosine similarity search.
    For production use, migrate to ChromaDB or FAISS.
    """

    def __init__(self, dim: int = 1536, persist_path: str | None = None):
        """
        Args:
            dim:          embedding dimension (1536 for text-embedding-3-small)
            persist_path: optional path to save/load index
        """
        self.dim = dim
        self._persist_path = Path(persist_path) if persist_path else None
        self._ids: list[str] = []
        self._embeddings: np.ndarray | None = None  # shape: (n, dim)
        self._metadata: list[dict] = []

        if self._persist_path and self._persist_path.exists():
            self.load()

    # ── CRUD ─────────────────────────────────────────────

    def add(self, id_: str, embedding: list[float], metadata: dict | None = None) -> None:
        """Add or update a vector."""
        if id_ in self._ids:
            idx = self._ids.index(id_)
            self._embeddings[idx] = np.array(embedding, dtype=np.float32)
            self._metadata[idx] = metadata or {}
            return

        self._ids.append(id_)
        emb = np.array(embedding, dtype=np.float32)
        if self._embeddings is None:
            self._embeddings = emb.reshape(1, -1)
        else:
            self._embeddings = np.vstack([self._embeddings, emb])
        self._metadata.append(metadata or {})

    def get(self, id_: str) -> tuple[list[float], dict] | None:
        """Get a vector by ID."""
        if id_ not in self._ids:
            return None
        idx = self._ids.index(id_)
        return self._embeddings[idx].tolist(), self._metadata[idx]

    def delete(self, id_: str) -> bool:
        """Delete a vector by ID."""
        if id_ not in self._ids:
            return False
        idx = self._ids.index(id_)
        self._ids.pop(idx)
        self._metadata.pop(idx)
        self._embeddings = np.delete(self._embeddings, idx, axis=0)
        return True

    def clear(self) -> None:
        """Clear all vectors."""
        self._ids.clear()
        self._embeddings = None
        self._metadata.clear()

    # ── Search ─────────────────────────────────────────────

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        filter_fn: callable | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar vectors (cosine similarity).

        Args:
            query_embedding: the query vector
            top_k:            number of results to return
            filter_fn:        optional lambda(metadata) → bool

        Returns:
            list of {id, score, metadata} dicts, sorted by score desc.
        """
        if self._embeddings is None or len(self._ids) == 0:
            return []

        q = np.array(query_embedding, dtype=np.float32).reshape(1, -1)

        # Cosine similarity: (A·B) / (||A|| * ||B||)
        norms = np.linalg.norm(self._embeddings, axis=1, keepdims=True)
        q_norm = np.linalg.norm(q)

        # Avoid division by zero
        norms = np.where(norms == 0, 1e-8, norms)
        q_norm = q_norm if q_norm > 0 else 1e-8

        similarities = (self._embeddings @ q.T).flatten() / (norms.flatten() * q_norm)
        # Handle numerical errors
        similarities = np.clip(similarities, -1.0, 1.0)

        # Build results
        results: list[dict[str, Any]] = []
        for idx, score in enumerate(similarities):
            meta = self._metadata[idx]
            if filter_fn and not filter_fn(meta):
                continue
            results.append({
                "id": self._ids[idx],
                "score": float(score),
                "metadata": meta,
            })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def search_by_id(
        self,
        id_: str,
        top_k: int = 5,
        filter_fn: callable | None = None,
    ) -> list[dict[str, Any]]:
        """Search for vectors similar to an existing ID."""
        result = self.get(id_)
        if result is None:
            return []
        embedding, _ = result
        return self.search(embedding, top_k=top_k, filter_fn=filter_fn)

    # ── Persistence ─────────────────────────────────────────

    def save(self) -> None:
        """Save the index to disk (NPZ format)."""
        if not self._persist_path:
            logger.warning("No persist_path set, skipping save")
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "ids": self._ids,
            "dim": self.dim,
            "metadata": self._metadata,
        }
        np.savez(
            self._persist_path,
            embeddings=self._embeddings,
            id=np.array(self._ids, dtype=object),
            meta=np.array([json.dumps(m, ensure_ascii=False) for m in self._metadata], dtype=object),
            dim=np.array([self.dim]),
        )
        logger.info("VectorStore saved: %d vectors → %s", len(self._ids), self._persist_path)

    def load(self) -> None:
        """Load the index from disk."""
        if not self._persist_path or not self._persist_path.exists():
            return
        data = np.load(self._persist_path, allow_pickle=True)
        self._embeddings = data["embeddings"]
        self._ids = [str(x) for x in data["id"]]
        self.dim = int(data["dim"][0])
        meta_raw = data["meta"]
        self._metadata = [json.loads(str(m)) for m in meta_raw]
        logger.info("VectorStore loaded: %d vectors from %s", len(self._ids), self._persist_path)

    # ── Stats ───────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "count": len(self._ids),
            "dim": self.dim,
            "persist_path": str(self._persist_path) if self._persist_path else None,
        }

    def __len__(self) -> int:
        return len(self._ids)


# ── Embedding helper ─────────────────────────────────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a = np.array(a, dtype=np.float32)
    b = np.array(b, dtype=np.float32)
    dot = float(a @ b)
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
