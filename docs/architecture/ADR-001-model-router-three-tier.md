# ADR-001: 三层模型路由架构

## Status
Accepted

## Context

Byou 此前所有 Agent 统一调用单一 LLM（`gpt-4o` 或等效模型），导致：
- 简单任务（名片字段提取）消耗与复杂任务（BD 策略生成）相同的算力成本
- 高峰期 API 费用不可控
- 无自动降级机制，模型服务异常时整个 Pipeline 失败

目标是：**在不降低输出质量的前提下，将 LLM 成本降低 50-70%**。

## Decision

引入 `ModelRouter`（`byou/core/model_router.py`），实现三层推理架构：

| Tier | 定位 | 典型模型 | 适用 Agent |
|------|------|------------|-------------|
| CHEAP | 轻量结构化提取 | gpt-3.5-turbo / 本地小模型 | extractor |
| MEDIUM | 中等推理 | gpt-4o-mini | researcher, synthesizer |
| DEEP | 复杂策略/审计 | gpt-4o / claude-3 | strategist, critic |

**路由逻辑**：
1. 每个 Agent 声明 `preferred_tier`（见 `agents/configs.py`）
2. `TaskComplexity` 评估输入复杂度（prompt 长度、是否有上下文、领域专业度）
3. `ModelRouter.route()` 综合考虑偏好 + 复杂度 → 输出 `selected_tier`
4. 执行时若响应置信度低（`< 0.6`），自动 escalate 到下一层重试

**接入方式**：修改 `Agent.call_llm()`（`byou/agents/base.py`），在每次 LLM 调用前执行路由，使用 `get_client_for_tier()` / `get_model_for_tier()` 获取对应客户端与模型名。

## Consequences

**变容易**：
- 5 个 Agent 无需逐个修改，`base.py` 一处改动全局生效
- `preferred_tier` 通过 `configs.py` 声明式配置，调整无需改代码

**成本影响**：
- extractor 切到 CHEAP 层：单次调用成本预计降低 ~70%
- strategist/critic 保留 DEEP 层：质量敏感任务不降级

**风险**：
- escalate 逻辑依赖 `_quick_confidence()` 启发式评估，可能误判（假阳性 escalate 增加成本，假阴性降低质量）
- 需要配置 `model_cheap` / `model_medium` / `model_deep` 三个配置项（见 `config.py`）

**后续工作**：
- 采集真实 token 用量数据，校准 `TaskComplexity` 各字段权重
- 考虑引入「用户反馈 → 路由策略」学习循环
