# ADR-003: Intake Matching 模块补齐

## Status
Accepted

## Context

图 3（Intake 系统架构图）展示了完整的 6 阶段流水线：
Collection → Extraction → Matching → Resolution → Assembly → Publish

代码审计发现：`Matching`、`Resolution`、`Assembly`、`Publish` 四个阶段严重缺失或极度简化：
- `Matching`：只有 `VoiceprintMatcher`，无名片字段 fuzzy matching、无跨会话去重
- `Resolution`：只有基础的 `IdentityGraph`，无冲突消解机制
- `Assembly`：文件存在但逻辑不完整
- `Publish`：无发布机制，结果直接返回 caller

目标是：**补齐 Matching 核心能力，使 Intake 流水线在跨会话身份合并场景下可用**。

## Decision

### 1. 新建 `byou/intake/matching.py`

提供两个核心类：

**`SimilarityEngine`** — 字段级相似度：
- `fuzzy_name_similarity()`：拼音 + 编辑距离混合（基于 `pypinyin` + `Levenshtein`）
- `normalize_phone()`：去国际区号、去分隔符，数字归一化
- `company_similarity()`：jieba 分词 + 核心词匹配
- `email_similarity()`：local-part 相似度 + domain 精确匹配

**`CrossSessionMatcher`** — 跨会话匹配 + 合并：
- `match_card_to_known_identities()`：名字/电话/邮箱/公司四维度联合匹配
- `match_and_merge()`：自动合并或标记需人工审核
- `find_potential_duplicates()`：扫描整个 IdentityGraph 发现重复

### 2. 修改 `byou/intake/extraction.py`

`IdentityMatcher` 接入 `CrossSessionMatcher`：
- `match_all()` 现在使用 `CrossSessionMatcher.match_and_merge()` 替代原有简单逻辑
- 支持 fuzzy matching（之前只有精确匹配）
- 返回结果包含 `requires_review` 标志

### 3. `IdentityGraph` 持久化

`byou/intake/identity/graph.py` 新增：
- `save(path)`：序列化为 JSON（节点、绑定、vpids）
- `load(path)`：从 JSON 恢复
- `merge_node_into()`：将一个 UID 的所有绑定合并到另一个 UID

## Consequences

**好处**：
- Intake Matching 从「概念」变成「可用」：跨会话身份合并现在能工作
- `SimilarityEngine` 可独立测试，不依赖完整 Pipeline
- `IdentityGraph` 持久化 → 重启后不丢失身份绑定关系

**成本**：
- 新增 `pypinyin` 和 `Levenshtein` 依赖（`matching.py` 导入）
- `CrossSessionMatcher` 是纯 Python 实现，大规模（>10K 身份）时性能需关注

**风险**：
- fuzzy matching 的阈值（`name_threshold=0.8` 等）可能需要根据实际数据校准
- `save()` / `load()` 未做版本管理，格式变更时不兼容

**后续工作**：
- [ ] `Resolution` 阶段：添加冲突消解 UI（人工审核队列）
- [ ] `Assembly` 阶段：完善 `assembly.py` 逻辑
- [ ] `Publish` 阶段：接入 CRM / 消息总线
- [ ] 大规模性能测试：>10K 身份时的 `CrossSessionMatcher` 性能
