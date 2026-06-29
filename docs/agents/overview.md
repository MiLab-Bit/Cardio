# Agent 体系总览

## 设计哲学

每个 Agent 遵循**单一职责 + 统一接口**原则：

```python
class BaseAgent(ABC):
    name: str          # Agent 标识
    model: str         # LLM 模型
    temperature: float # 创造性
    max_retries: int   # 最大重试次数

    @abstractmethod
    def _default_prompt() -> str               # 系统提示词
    @abstractmethod
    async def execute(input_data: dict) -> dict # 执行业务逻辑

    async def call_llm(messages: list) -> str   # LLM 调用（含重试）
    def validate_result(result: dict, required_fields: list) -> bool
```

## 5 Agent 全景

```
┌───────────────────────────────────────────────────────────┐
│                       Agent 体系                           │
├────────────┬──────────┬─────────────┬──────────┬─────────┤
│  Extractor │Researcher│ Synthesizer │Strategist│  Critic  │
│ 信息提取   │ 客户背调  │ 画像合成    │ BD策略   │ 质检审核 │
├────────────┼──────────┼─────────────┼──────────┼─────────┤
│   OCR      │ 多源搜索  │ 意向评分    │ TalkingPt│ 可信评分  │
│   ASR      │ 知识图谱  │ 等级评定    │ FollowUp │ 风险审查  │
│   结构化    │ 行业分析  │ 洞察生成    │ 方案推荐  │ 建议反馈  │
└────────────┴──────────┴─────────────┴──────────┴─────────┘
```

## 统一输入输出

| Agent | execute(input) | output |
|-------|---------------|--------|
| Extractor | `{card_image_path, audio_file_path}` | `{profile, raw_text, key_points, confidence}` |
| Researcher | `{company_name, person_name}` | `{company_info, industry_analysis, competitors}` |
| Synthesizer | `{profile, research_result}` | `{customer_level, intent_score, persona, insights}` |
| Strategist | `{profile, persona, research_result}` | `{talking_points, follow_up_plan, risks, recommended_actions}` |
| Critic | `{all_stage_outputs}` | `{trust_score, quality_passed, checks, suggestions}` |

## LLM 调用模式

所有 Agent 通过 `call_llm()` 调用 LLM：

```python
async def call_llm(self, messages: list[dict]) -> str:
    for attempt in range(self.max_retries):
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    *messages,
                ],
                temperature=self.temperature,
            )
            return response.choices[0].message.content
        except Exception as e:
            if attempt == self.max_retries - 1:
                raise RuntimeError(f"LLM 调用全部失败: {e}")
            await asyncio.sleep(2 ** attempt)
```

**当前状态**: 调用 OpenAI SDK，预留了模型切换接口。

## Agent 间通信

Agent 不直接引用彼此。通过 Message Bus 在 Pipeline 阶段间传递数据：

```
Extractor ──bus──→ Researcher ──bus──→ Synthesizer ──bus──→ ...
```

但在当前 Pipeline 实现中，数据主要通过 `PipelineContext` 传递（更直接）。Message Bus 预留给未来的异步/并行场景。
