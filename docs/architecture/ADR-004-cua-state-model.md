# ADR-004: CUA State Model 层引入

## Status
Accepted

## Context

CUA（Computer-Use Agent）原 `planning.py` 仅有 prompt-based 简易规划：
- 页面状态检测 = 字符串比较
- 异常检测 = 连续3步无变化
- 无状态聚类、无可用动作识别、无状态转移图

图2宣传图展示了6层精密架构（Perception → Grounding → State Modeling → Planning → Execution → Verification），实际差距约50%。
需要引入真正的 State Model，让 CUA 能理解"当前页面状态"并做结构化规划。

## Decision

引入 `CUAState` 数据模型 + 四步流水线：

### 1. StateModel（页面状态结构化）

将 `PerceptionResult`（DOM + 截图）转化为结构化 `CUAState`：
- `visible_elements`: 可交互元素列表（文本、类型、位置、可用状态）
- `page_type`: 登录页/列表页/详情页/表单页/未知
- `form_state`: 已填字段、必填字段、校验错误
- `navigation_state`: 当前URL、标题、面包屑
- `similarity_hash`: 页面状态指纹（MD5 of sorted element texts）

### 2. StateClusterer（状态聚类）

- 首次见某状态 → 存为 `StateCluster` 原型
- 后续状态 → 计算相似度（元素重合度 + URL模式），归入最相似集群
- 目的：让 CUA 认出"这个表单页我见过"，复用历史操作经验

### 3. ActionAvailabilityDetector（可用操作识别）

基于 `CUAState` 推断当前可执行操作：
- 有输入框且未填 → `input_text`
- 有按钮且可用 → `click`
- 有下拉且未展开 → `select_option`
- URL变化 → `wait_for_navigation`
- 表单可提交 → `submit_form`

### 4. StateGraph（状态转移图）

记录 `(state_A) --[action]--> (state_B)` 转移：
- 每次执行后自动更新
- 支持最短路径查询（"如何从列表页到详情页？"）
- 循环检测（防止死循环）

## Consequences

**变得更容易：**
- CUA 规划从"黑盒prompt"变为"白盒状态机"
- 页面状态可持久化、可复现、可调试
- 支持"跳过已见过页面"的优化（StateClusterer）

**变得更困难：**
- `perception.py` 需要输出更结构化的DOM摘要（当前只有原始HTML）
- `planning.py` 需要维护 `StateGraph`（内存增长，需定期清理）
- 相似度计算有误差 → 可能把"相似但不同"的页面归为同一状态

**风险：**
- `similarity_hash` 对动态内容（时间戳、随机数）敏感 → 需引入忽略规则
- `StateGraph` 边数量 O(n²) → 限制最大状态数（1000），LRU淘汰

## Alternatives Considered

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 纯prompt规划（原方案） | 简单，0代码改动 | 不可解释，无法复用经验 | 拒绝 |
| 引入Playwright的AXTree | 标准，结构化 | 依赖Playwright版本，信息有限 | 作为Perception补充 |
| 自建CV模型做页面理解 | 最精确 | 工程量巨大，需标注数据 | v3规划 |

## Implementation Notes

- `state_model.py`: 新文件，包含 `CUAState`、`StateCluster`、`ActionAvailabilityDetector`、`StateGraph`
- `planning.py`: 重写 `PlanningLayer.process()`，先调 `StateModel.from_perception()` 再规划
- `perception.py`: 可选增强，输出 `element_list`（当前已有 `PerceptionResult.elements`）

---
*Date: 2025-01-XX | Author: Software Architect*
