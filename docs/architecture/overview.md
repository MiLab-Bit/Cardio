# 系统总览

## 一、整体架构

```
┌─────────────────────────────────────────────────────────┐
│                      CLI / API                          │
│                   (click / FastAPI)                      │
├─────────────────────────────────────────────────────────┤
│                    Orchestrator                          │
│              (Pipeline 编排 + CUA 运行时)                │
├──────────┬──────────┬──────────┬──────────┬─────────────┤
│Extractor │Researcher│Synthesizer│Strategist│   Critic    │
│   Agent   │  Agent   │   Agent   │   Agent   │   Agent    │
├──────────┴──────────┴──────────┴──────────┴─────────────┤
│                    Message Bus                           │
│              (P2P / PubSub / Broadcast)                  │
├─────────────────────────────────────────────────────────┤
│                   Learning Loop                          │
│           (权重调节 + 滑动窗口 + 持久化)                  │
├─────────────────────────────────────────────────────────┤
│                    CUA Runtime                           │
│  Perception → Semantic → State → Planning → Exec → Valid │
├─────────────────────────────────────────────────────────┤
│                  Infrastructure                          │
>│   LLM Client  │  Browser (Playwright)  │  Config         │
│   Vector Store (ChromaDB)  │  Graph Store (NetworkX)    │
│          Cache Layer        │     Tool Registry          │
├─────────────────────────────────────────────────────────┤
│                     Data Models                          │
│   CustomerProfile / PipelineContext / BDStrategy 等      │
└─────────────────────────────────────────────────────────┘
```

## 二、模块职责

| 模块 | 路径 | 职责 |
|------|------|------|
| `byou.core.orchestrator` | 核心编排 | 管理 Pipeline 生命周期，调度 Agent 执行 |
| `byou.core.runtime` | CUA 运行时 | 包装 6 层 CUA，交付统一执行接口 |
| `byou.core.learning_loop` | 学习循环 | 采集执行指标，调节 Agent 权重，持久化 |
| `byou.core.message_bus` | 消息总线 | Agent 间通信基础设施 |
| `byou.agents.*` | Agent 层 | 5 个专职 Agent，各自负责 Pipeline 一个阶段 |
| `byou.cua.*` | CUA 层 | 6 层架构：感知→语义→状态→规划→执行→校验 |
| `byou.models.*` | 数据模型 | Pydantic v2 定义的业务实体 |
>| `byou.tools.*` | 工具层 | OCR/ASR/搜索/CRM/知识库 |
| `byou.infrastructure.*` | 基础设施 | LLM 客户端/浏览器/向量存储/图谱/缓存 |
| `byou.config` | 配置层 | pydantic-settings 统一配置加载 |

## 三、运行模式

### 模式 1：CLI 一次性执行

```bash
python main.py pipeline --card card.jpg --audio meeting.mp3
```

适用场景：单次 BD 任务，全自动 Pipeline。

### 模式 2：API 服务

```bash
python main.py serve --port 8000
```

适用场景：对接 CRM / 前端 UI，提供 RESTful 接口。

### 模式 3：分步执行

```bash
python main.py extract --card card.jpg     # 仅提取
python main.py research --company "华为"    # 仅背调
python main.py status                       # 查看系统状态
```

适用场景：人机协作，逐阶段确认。

## 四、关键设计决策

1. **Agent 非黑盒** — 每个 Agent 通过 `execute(input) → output` 接口解耦，可独立替换
2. **Pipeline 非硬编码** — Orchestrator 通过注册表动态组合 Agent
3. **CUA 可插拔** — CUA 6 层通过 `is_ready()` 检查，可按需跳过某层
4. **学习即记忆** — Learning Loop 不训练模型，通过权重调节影响策略选择
5. **消息总线** — Agent 不直接引用彼此，通过总线通信，便于扩展
