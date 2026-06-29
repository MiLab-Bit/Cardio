# ADR-005: 关系图谱模块引入

## Status
Accepted

## Context

Intake 系统的 Identity Graph（`identity/graph.py`）是纯内存图结构：
- 节点 = `IdentityNode`（人/公司/会话）
- 边 = `IdentityBinding`（属于/参与/来自）
- 查询 = 线性扫描（`find_by_alias`、`get_bindings`）

图3宣传图包含「关系图谱关联」作为 Assembly 阶段的核心能力，当前实现差距较大：
1. 无图遍历能力（最短路径、邻居查询）
2. 无社区检测（"哪些人属于同一公司网络？"）
3. 无重要性排序（PageRank → 关键决策人识别）
4. 无图持久化（重启丢失）

需要引入图计算能力，但权衡工程量与收益。

## Decision

采用 **两阶段方案**：

### Phase 1（当前）：NetworkX 内存图
- `graph_nx.py`: `NetworkXGraph` 封装，适配 `IdentityGraph` 数据
- 支持：最短路径、邻居查询、社区检测（Louvain）、PageRank
- 依赖：`pip install networkx`（可选，import失败时降级为普通查询）
- 触发：Intake Assembly 阶段调用 `enrich_with_graph(identity_graph)`

### Phase 2（v2.0）：持久化图数据库
- 选项A：Neo4j（功能最强，运维成本最高）
- 选项B：嵌入式图引擎（KuzuDB / DuckDB+递归CTE）
- 选项C：继续 NetworkX + JSON 快照（当前方案演进）
- **结论**：Phase 1 验证价值后，Phase 2 选 **KuzuDB**（嵌入式，零运维，Cypher兼容）

## Consequences

**变得更容易：**
- 社区检测 → 自动发现"决策圈"（同一公司的关键人物网络）
- PageRank → 客户重要性排序（不仅看公司规模，看关系连接数）
- 最短路径 → "通过谁介绍认识X？"（社交路径推荐）

**变得更困难：**
- NetworkX 内存图 O(n) 遍历 → 节点 >10K 时慢（但 BD 场景 <1K，可接受）
- 图一致性：`IdentityGraph`（业务状态）vs `NetworkXGraph`（计算视图）需要同步
- 社区检测结果需要解释（"为什么把A和B分在同一社区？"）

**风险：**
- 图数据质量差（别名匹配不准）→ 图谱有噪声 → 社区检测失效
- 循环引用（`A→B→C→A`）→ PageRank 偏置

## Architecture

```
IdentityGraph (业务状态)
    ↓ sync()
NetworkXGraph (计算视图)
    ↓ analyze()
GraphInsights
    ↓ writeback()
IdentityGraph ( enrichment)
```

### 数据同步

`NetworkXGraph.from_identity_graph(graph)` 类方法：
- `IdentityNode` → NetworkX node（属性：`node_type`、`create_time`）
- `IdentityBinding` → NetworkX edge（属性：`binding_type`、`confidence`）
- 增量更新：监听 `IdentityGraph` 的 `add_node` / `add_binding` 事件

### 查询 API

```python
# 最短路径
nxg = NetworkXGraph.from_identity_graph(identity_graph)
path = nxg.shortest_path("uid_alice", "uid_bob")
# → ["uid_alice", "cid_acme_corp", "uid_bob"]  (Alice -[works_at]-> ACME <-[works_at]- Bob)

# 社区检测
communities = nxg.detect_communities()  # Louvain
# → [{"cid_acme", "uid_alice", "uid_bob"}, {"cid_competitor", ...}]

# 关键人物
key_people = nxg.pagerank_top_k(k=10)
# → [("uid_alice", 0.15), ("uid_bob", 0.12), ...]
```

## Alternatives Considered

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 纯内存字典查询（原方案） | 简单，0依赖 | 无图计算能力 | 拒绝 |
| NetworkX（当前选择） | 功能全，Python生态好 | 内存受限，非持久化 | 接受（Phase 1） |
| Neo4j | 工业级，Cypher标准 | 需部署服务器，学习成本 | Phase 2 候选 |
| KuzuDB | 嵌入式，零运维 | 较新，生态小 | Phase 2 首选 |
| 自写图引擎 | 完全可控 | 工程量巨大，易有bug | 拒绝 |

## Implementation Notes

- `graph_nx.py`: 已创建，包含 `NetworkXGraph` 封装
- `vector_search.py`: 已创建，可选导入 `NetworkXGraph`（当 networkx 可用时）
- `intake/assembly.py`: 可选调用 `NetworkXGraph.enrich()` 做图谱增强
- 依赖声明：`pyproject.toml` 的 `optional-dependencies` 加 `graph: ["networkx>=3.0"]`

## Follow-up ADRs

- **ADR-006**（待写）：图数据库选型（KuzuDB vs Neo4j），当节点数 >10K 时触发
- **ADR-007**（待写）：图数据质量保障（别名归一化、冲突消解对图谱的影响）

---
*Date: 2025-01-XX | Author: Software Architect*
