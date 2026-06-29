"""Byou Memory — VectorStore (ChromaDB).

Phase 1 MVP 核心: 企业语义档案的向量存储与检索。

设计:
- 底层 ChromaDB (已在项目中引用)
- 每个 collection 对应一种 MemoryTier
- 支持 add / search / update / delete / count
- embedding 函数可插拔 (默认 OpenAI text-embedding-3-small)
- 内嵌 fallback: 无 embedding 模型时用 TF-IDF
"""

from __future__ import annotations

import logging
import time
from typing import Any

from byou.memory.types import (
    MemoryTier, MemoryEntry, MemoryQuery, MemoryQueryResult, LongTermMemory,
)

logger = logging.getLogger(__name__)

# 尝试导入 ChromaDB (Windows 兼容性保护)
import os as _os
import subprocess as _subprocess
import sys as _sys

_CHROMA_AVAILABLE = False
_CHROMA_FORCE_OFF = _os.environ.get("CHROMA_FORCE_OFF", "").lower() in ("1", "true", "yes")


def _chroma_safe_import() -> bool:
    """子进程探测 ChromaDB 可用性 (segfault 无法在进程内捕获)."""
    probe_code = """
import chromadb
from chromadb.config import Settings
import tempfile, os
tmp = tempfile.mkdtemp(prefix='_byou_chroma_')
try:
    c = chromadb.PersistentClient(path=tmp, settings=Settings(anonymized_telemetry=False))
    c.heartbeat()
    c.reset()
finally:
    import shutil; shutil.rmtree(tmp, ignore_errors=True)
print('OK')
"""
    try:
        r = _subprocess.run(
            [_sys.executable, "-c", probe_code],
            capture_output=True, text=True, timeout=15,
        )
        return r.returncode == 0 and "OK" in r.stdout
    except Exception:
        return False


def _try_import_chromadb() -> None:
    global _CHROMA_AVAILABLE
    if _CHROMA_FORCE_OFF:
        logger.info("ChromaDB disabled via CHROMA_FORCE_OFF, using in-memory fallback")
        return

    # Step 1: 检查包是否安装
    try:
        import chromadb  # noqa: F401
    except ImportError:
        logger.warning("ChromaDB not installed, using in-memory fallback")
        return

    # Step 2: Windows 上做子进程安全探测 (segfault 不可进程内捕获)
    if _os.name == "nt" and not _chroma_safe_import():
        logger.warning("ChromaDB segfault on Windows detected, using in-memory fallback")
        return

    _CHROMA_AVAILABLE = True
    logger.info("ChromaDB available (persist=%s)", _os.environ.get("CHROMA_PERSIST_DIR", "./byou_memory_db"))


_try_import_chromadb()

if _CHROMA_AVAILABLE:
    import chromadb  # noqa: F811
    from chromadb.config import Settings as ChromaSettings  # noqa: F811


class VectorStore:
    """企业档案向量存储。

    每个 tier 一个 collection:
    - "memory_long_term"  — 企业档案
    - "memory_strategy"   — 策略记忆
    """

    def __init__(self, persist_path: str = "./byou_memory_db", embedding_fn: Any = None):
        self._persist_path = persist_path

        if _CHROMA_AVAILABLE:
            self._client = chromadb.PersistentClient(
                path=persist_path,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        else:
            self._client = None
            self._fallback_store: dict[str, list[tuple[MemoryEntry, list[float]]]] = {}

        self._embedding_fn = embedding_fn or self._default_embedding
        self._collections: dict[str, Any] = {}

    # ── 公开 API ────────────────────────────────────

    def add(self, entry: MemoryEntry, embedding: list[float] | None = None) -> str:
        """添加一条记忆条目"""
        emb = embedding or self._embed_text(entry.key)
        entry.embedding = emb

        coll = self._get_collection(entry.tier.value)
        if coll is not None:
            try:
                coll.add(
                    ids=[entry.id],
                    embeddings=[emb],
                    metadatas=[{
                        "key": entry.key,
                        "tier": entry.tier.value,
                        "category": entry.category.value,
                        "confidence": entry.confidence,
                        "source": entry.source,
                        "created_at": entry.created_at.isoformat(),
                        "access_count": entry.access_count,
                    }],
                    documents=[self._entry_to_document(entry)],
                )
            except Exception as e:
                logger.warning("ChromaDB add failed: %s", e)
        else:
            # 降级
            if entry.tier.value not in self._fallback_store:
                self._fallback_store[entry.tier.value] = []
            self._fallback_store[entry.tier.value].append((entry, emb))

        return entry.id

    def search(self, query: MemoryQuery) -> MemoryQueryResult:
        """语义搜索"""
        t0 = time.monotonic()

        query_emb = query.query_embedding or self._embed_text(query.query_text)
        tier_key = query.tier.value if query.tier else "memory_long_term"

        results: list[MemoryEntry] = []
        scores: list[float] = []

        coll = self._get_collection(tier_key)
        if coll is not None:
            try:
                raw = coll.query(
                    query_embeddings=[query_emb],
                    n_results=query.top_k,
                )
                if raw and raw.get("ids") and raw["ids"][0]:
                    for i, item_id in enumerate(raw["ids"][0]):
                        meta = raw["metadatas"][0][i] if raw.get("metadatas") else {}
                        doc = raw["documents"][0][i] if raw.get("documents") else ""
                        dist = raw["distances"][0][i] if raw.get("distances") else 0.0

                        entry = MemoryEntry(
                            id=item_id,
                            tier=MemoryTier(meta.get("tier", "long_term")),
                            key=meta.get("key", ""),
                            content={},
                            confidence=float(meta.get("confidence", 0.8)),
                            source=meta.get("source", ""),
                            access_count=int(meta.get("access_count", 0)),
                        )
                        results.append(entry)
                        scores.append(1.0 - min(dist / 2.0, 1.0))  # cosine dist → similarity
            except Exception as e:
                logger.warning("ChromaDB search failed: %s", e)
        else:
            # 降级: 暴力余弦相似度
            items = self._fallback_store.get(tier_key, [])
            for entry, emb in items:
                if query.exclude_archived and entry.is_archived:
                    continue
                if entry.confidence < query.min_confidence:
                    continue
                sim = self._cosine_sim(query_emb, emb)
                scores.append(sim)
                results.append(entry)

            # 排序取 top_k
            paired = sorted(zip(scores, results), key=lambda x: x[0], reverse=True)
            scores = [p[0] for p in paired[:query.top_k]]
            results = [p[1] for p in paired[:query.top_k]]

        total_hits = len(results)
        query_time_ms = (time.monotonic() - t0) * 1000

        return MemoryQueryResult(
            entries=results,
            scores=scores,
            query_time_ms=round(query_time_ms, 2),
            total_hits=total_hits,
        )

    def update(self, entry: MemoryEntry) -> str:
        """更新 (删除旧+插入新)"""
        self.delete(entry.id)
        return self.add(entry)

    def delete(self, entry_id: str) -> bool:
        """删除"""
        for coll_name in list(self._collections.keys()):
            coll = self._collections[coll_name]
            if coll is not None:
                try:
                    coll.delete(ids=[entry_id])
                except Exception:
                    pass
            else:
                for tier_key in self._fallback_store:
                    self._fallback_store[tier_key] = [
                        (e, emb) for e, emb in self._fallback_store[tier_key]
                        if e.id != entry_id
                    ]
        return True

    def count(self, tier: MemoryTier | None = None) -> int:
        """计数"""
        total = 0
        tiers = [tier.value] if tier else list(self._collections.keys())
        for t in tiers:
            coll = self._get_collection(t)
            if coll is not None:
                try:
                    total += coll.count()
                except Exception:
                    pass
            else:
                total += len(self._fallback_store.get(t, []))
        return total

    # ── 内部 ──────────────────────────────────────

    def _get_collection(self, name: str):
        if name in self._collections:
            return self._collections[name]
        if self._client is None:
            self._collections[name] = None
            return None
        try:
            coll = self._client.get_or_create_collection(name=name)
            self._collections[name] = coll
            return coll
        except Exception as e:
            logger.warning("Failed to get/create collection '%s': %s", name, e)
            self._collections[name] = None
            return None

    def _embed_text(self, text: str) -> list[float]:
        """文本 → 向量"""
        if self._embedding_fn and callable(self._embedding_fn):
            try:
                result = self._embedding_fn(text)
                if isinstance(result, list) and result and isinstance(result[0], (int, float)):
                    return result
            except Exception as e:
                logger.warning("Embedding function failed: %s", e)

        # 降级: 简单哈希向量 (无 embedding 模型时)
        return self._hash_embedding(text)

    @staticmethod
    def _hash_embedding(text: str, dim: int = 256) -> list[float]:
        """简单哈希向量 (降级用)"""
        import hashlib
        h = hashlib.sha256(text.encode()).digest()
        vec = []
        for i in range(dim):
            # 用 4 个字节做伪随机浮点数
            seed = int.from_bytes(h[i % len(h):i % len(h) + 4] or b'\x00' * 4, 'big')
            vec.append((seed % 1000) / 1000.0 * 2 - 1)
        return vec

    @staticmethod
    def _cosine_sim(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    @staticmethod
    def _entry_to_document(entry: MemoryEntry) -> str:
        """将 MemoryEntry 转为可索引文本"""
        content = entry.content
        if isinstance(content, dict):
            # LongTermMemory 等
            summary = content.get("profile_summary", "") or content.get("strategy_json", {})
            if isinstance(summary, dict):
                summary = str(summary)
            name = content.get("company_name", "") or content.get("name", "")
            return f"{name}\n{summary}"
        return str(content)

    @staticmethod
    def _default_embedding(text: str) -> list[float]:
        """默认嵌入函数 — 尝试 OpenAI API"""
        try:
            import os
            from openai import OpenAI
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
            resp = client.embeddings.create(
                model="text-embedding-3-small",
                input=text[:8191],
            )
            return resp.data[0].embedding
        except Exception:
            return VectorStore._hash_embedding(text)
