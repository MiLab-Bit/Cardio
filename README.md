# Cardio · 心血管相关 Web 服务

> BD / 销售五段分析管线 Agent，接入 Temporal 编排。

## 简介

Cardio 是一个面向 BD（商务拓展）/ 销售场景的分析服务，通过五段管线对目标企业/机会进行结构化研判：

```
extraction → research → synthesis → strategy → critique
 提取关键信息   深度调研    综合研判     策略建议    批判性审视
```

## Temporal 编排接入（2026-10）

五段分析管线已接入 **Temporal Server v1.27**，实现工作流持久化、自动重试和状态查询。

### 代码结构

```
cardio/temporal/
├── __init__.py
├── common.py        # AnalyzeInput dataclass
├── activities.py    # 5 个 async Activity（共用 _llm_call）
├── worker.py        # Worker 启动器
└── workflows/
    └── analyze.py   # CardioAnalyzeWorkflow（五段顺序编排）
```

### 设计要点

- **async Activity**：五段 Activity 都是 `async def`（内部是异步 LLM HTTP 调用），不需要 ThreadPoolExecutor
- **共用 LLM 调用**：所有 Activity 共享 `_llm_call(message, system)` 辅助函数，统一超时和重试策略

### 配置

```bash
TEMPORAL_ADDRESS=127.0.0.1:7233
TEMPORAL_NAMESPACE=cardio
TEMPORAL_TASK_QUEUE=cardio-task-queue
```

### 运行

```bash
python -m cardio.temporal.worker
```

## 快速开始

```bash
# 安装依赖
python -m venv venv && source venv/bin/activate
pip install -e .

# 配置环境变量
cp .env.example .env  # 编辑 .env 填入 LLM API key

# 启动 Worker
python -m cardio.temporal.worker
```

---

## 在线部署 / Live Deployment

| 环境 | 地址 |
|---|---|
| API 服务 | http://cardio.sy-realm.ltd |
| 健康检查 | http://cardio.sy-realm.ltd/health |

> FastAPI 后端（五段 BD 分析管线），部署于阿里云 ECS，经 Nginx 反代，DNS 走 Cloudflare（DNS-only 直连）。
> 编排底座：Temporal（[temporal.sy-realm.ltd](http://temporal.sy-realm.ltd) 可视化 Workflow 执行）。



© Cardio · MiLab-Bit
