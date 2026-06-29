# Orchestrator 编排器设计

## 文件

`byou/core/orchestrator.py` → `Orchestrator`

## 职责

1. **Agent 注册与管理** — 维护 Agent 名册，按需加载
2. **Pipeline 编排** — 按序调用 5 个 Agent，传递上下文
3. **进度通知** — 通过 `on_progress` 回调暴露执行进度
4. **错误隔离** — 单 Agent 失败不阻断整体流程

## 核心接口

```python
class Orchestrator:
    max_concurrent_agents: int = 5
    message_bus: MessageBus
    cua_runtime: CuaRuntime
    learning_loop: LearningLoop

    def register_agent(name: str, agent: BaseAgent) -> None
    def get_agent(name: str) -> Optional[BaseAgent]
    async def process_pipeline(
        card_image_path: Optional[str],
        audio_file_path: Optional[str],
        context: Optional[dict],
        on_progress: Optional[Callable],
    ) -> PipelineContext
    async def shutdown() -> None
```

## Pipeline 执行流程（伪代码）

```python
async def process_pipeline(self, **kwargs):
    ctx = PipelineContext(**kwargs)
    on_progress("pipeline_start", {})

    # 阶段 1: 提取
    try:
        on_progress("extraction", {})
        extractor = self.get_agent("extractor")
        if extractor:
            result = await extractor.execute({"card": ctx.card_image_path, "audio": ctx.audio_file_path})
            ctx.raw_extraction = result
            ctx.profile = result.get("profile")
            ctx.raw_text = result.get("raw_text", "")
            on_progress("extraction_done", result)
    except Exception as e:
        ctx.errors.append(f"Extraction failed: {e}")
        on_progress("pipeline_error", {"error": str(e)})
        return ctx  # 关键阶段失败 → 终止

    # 阶段 2-5 同理...
    # researcher → synthesizer → strategist → critic

    on_progress("pipeline_complete", ctx.get_summary())

    # 记录到 Learning Loop
    self.learning_loop.record_execution(ctx)

    return ctx
```

## Agent 注册方式

```python
orch = Orchestrator()
orch.register_agent("extractor", ExtractorAgent())
orch.register_agent("researcher", ResearcherAgent())
orch.register_agent("synthesizer", SynthesizerAgent())
orch.register_agent("strategist", StrategistAgent())
orch.register_agent("critic", CriticAgent())
```

**设计约束**: Agent 注册在 Orchestrator 初始化时完成，运行时不可动态卸载（但可替换）。

## 错误处理策略

| 阶段 | 失败时行为 |
|------|-----------|
| Extractor | 终止 Pipeline（无基础数据无法继续） |
| Researcher | 记录错误，继续画像（可降级） |
| Synthesizer | 记录错误，继续策略（需画像） |
| Strategist | 记录错误，仍可质检 |
| Critic | 记录错误，输出不通过质检标记 |

## 与 CUA Runtime 的关系

Orchestrator 持有 `CuaRuntime` 实例。Agent 在执行时通过 Orchestrator 访问 CUA：

```python
# Agent 内部
cua_result = await self.orchestrator.cua_runtime.execute_task(task)
```

当前实现中 Agent 不直接发送 CUA 任务（待集成），但架构上已预留该通道。
