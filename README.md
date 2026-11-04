# Cardio — BD / Sales Intelligence

Cardio 将客户与商机材料转化为五阶段商务研判：

**Extraction → Research → Synthesis → Strategy → Critique**

项目入口：https://cardio.sy-realm.ltd

## 当前实际架构（以代码为准）

| 层 | 实际执行路径 |
|---|---|
| Frontend | React 19 / Vite 8 / pnpm（固定 lockfile） |
| API | FastAPI / JWT / SQLite；受保护的 Chat、Analyze、Contacts、History |
| Analyze | 目前由 FastAPI 进程内调用 `cardio.pipeline.run_pipeline`，通过 SSE 推送阶段结果 |
| LLM | `cardio.gateway`：OpenAI-compatible、BYOK、按用户配额、隔离缓存、可重试请求 |
| Temporal | 仓库包含原生 Temporal SDK Worker 和五阶段 Workflow；**当前 HTTP Analyze 未提交 Temporal Workflow** |
| Encryption | `cardio.crypto` 使用 Fernet；生产环境必须采用受控密钥管理 |

### 明确的产品边界

- `Research` 阶段目前是模型对输入的分析推断，**不执行实时联网搜索**；需要进一步核实的事实必须标注。
- `Critique` 是实际第五阶段，但“能够减少事实错误”的效果仍待对照评测。
- API 分析目前不是 Temporal 承载的持久任务；进程中断后可能丢失尚未完成的运行。
- 平台模型调用受每日配额限制；超限返回明确错误，**不会静默切换成假结果或无成本本地模型**。
- BYOK 优先使用用户保存的模型配置，平台调用与 BYOK 的计费语义分开。
- `/health` 是检查点，不代表外部模型和 Temporal 全链路业务已通过。

## 本地开发

Python 3.12、Node 22、pnpm 9：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# 配置 CARDIO_JWT_SECRET 和所需模型凭据；不要将密钥提交到仓库
bash scripts/preflight.sh
python run.py
```

前端：

```bash
cd cardio-web
pnpm install --frozen-lockfile
pnpm dev
```

### Temporal Worker（可选，当前不由 HTTP API 派发）

```bash
export TEMPORAL_ADDRESS=127.0.0.1:7233
export TEMPORAL_NAMESPACE=cardio
export TEMPORAL_TASK_QUEUE=cardio-task-queue
python -m cardio.temporal.worker
```

需要事先提供可访问的 Temporal 服务与对应 namespace。Worker 能独立启动，不等于 HTTP API 已使用它；未来接入需要任务提交、结果查询和 BYOK 凭据引用设计，不能将明文 API Key 放进工作流历史。

## 验证

```bash
bash scripts/preflight.sh
```

门禁包含语法编译、pytest 离线契约、FastAPI 核心路由与鉴权冒烟、pnpm 锁文件构建。**不依赖外部 LLM、邮箱服务或 Temporal Server 才能通过。**

相关工程说明见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 运营与安全

- 任何部署、数据库迁移、用户凭据轮换均由授权运营人员执行；AI 不自动部署。
- BYOK 数据位于 `model_providers.api_key_enc`；不得将 Fernet 密钥、数据库备份、真实 API Key 写入仓库或 CI。
- 未经独立线上验证的可用性、持续运行时间、模型效果不在本 README 中承诺。
