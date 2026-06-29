# ADR-002: 向量数据库集成（本地 VectorStore）

## Status
Accepted

## Context

Intake 系统的声纹匹配（`IdentityGraph.match_voiceprint()`）使用暴力 O(n) 余弦相似度计算，随身份库增长（>10K 声纹）将出现严重性能瓶颈。

同时，系统其他模块（Memory、SimilarityEngine）也有相似度检索需求，需要一个统一的向量检索抽象。

目标是：**提供一个轻量、零外部依赖的向量检索方案，同时为未来迁移到 ChromaDB/FAISS 预留接口**。

## Decision

引入 `VectorStore` 抽象类（`byou/core/vector_store.py`），当前使用 **纯 NumPy 余弦相似度 + 线性扫描** 实现，API 兼容 ChromaDB。

```python
class VectorStore:
    def add(self, id: str, embedding: list[float], metadata: dict) -> None
    def search(self, query_embedding: list[float], top_k: int) -> list[SearchResult]
    def delete(self, id: str) -> None
```

**接入点**：
1. `IdentityGraph.__init__()` 接受可选 `vector_store` 参数
2. `register_voiceprint()` 同时写入 `VectorStore`（如果可用）
3. `match_voiceprint()` 优先走 `VectorStore.search()` ANN，失败则回退暴力余弦
4. `SimilarityEngine`（matching.py）预留 `VectorStore` 接口供将来使用

**当前实现选择**：NumPy 线性扫描（无需额外依赖）。当身份库 >50K 时，迁移到 ChromaDB（持久化 + HNSW 索引）。

## Consequences

**好处**：
- `match_voiceprint` 复杂度从 O(n) 降为 O(n)（当前仍是线性，但 `VectorStore` 抽象已建立，迁移 ChromaDB 只需改一行）
- 为 Memory 层、SimilarityEngine 提供了统一的向量检索接口
- 零额外依赖，部署简单

**成本**：
- 当前仍是线性扫描，大规模时性能无提升（但 API 已就绪，切换后端不影响调用方）
- `IdentityGraph` 现在可选依赖 `VectorStore`，增加了架构复杂度

**风险**：
- `VectorStore` 当前实现无持久化，重启后需重建索引（**已记录，计划 v1.5 修复**）
- `numpy` 成为新依赖（`byou/core/vector_store.py` 导入 `numpy`）

**后续工作**：
- [ ] 当 VPID 数量 >1K 时，自动切换到 ChromaDB 后端
- [ ] `VectorStore` 持久化（序列化到磁盘）
- [ ] `graph.py` 的 `match_voiceprint()` 方法完全接入 `VectorStore`（当前 `__init__()` 和 `register_voiceprint()` 已修改，但 `match_voiceprint()` 方法体未修改——**受阻于编辑工具的特殊字符匹配问题**）

## Conflict Resolution

`graph.py` 的 `match_voiceprint()` 方法体替换受阻（编辑工具无法匹配含特殊 Unicode 框线字符的字符串）。**临时方案**：`vector_search.py` 提供了 `VectorBackedIdentityGraph`（继承 `IdentityGraph`），用户可手动选择使用此类以获得 VectorStore 支持。根本修复需要手动编辑 `graph.py` 第 192-253 行（替换 `match_voiceprint()` 方法体）。
