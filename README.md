<p align="center"><img src="cardio-web/public/logo-cardio.jpg" width="340" alt="Cardio 数字商册" /></p>

# Cardio · 数字商册

> 把每一次认识、每一张名片和每一场商务会面，整理成下一次有依据的行动。

**Cardio — BD / Sales Intelligence**：一套面向商务拓展（BD）与销售研究的数字商册。它让零散的客户材料成为可追溯的客户档案，并通过五阶段研判生成跟进建议。

**▶ [体验 Cardio](https://cardio.sy-realm.ltd)**

---

## 如何使用

1. **商枢对话**：随时整理客户、会面和商机线索，提出商务问题。
2. **数字商册分析**：输入文字或名片图片，获得五阶段研判及阶段进度。
3. **商册名录**：保存联系人资料，将分析结果关联到具体联系人。
4. **历史研判**：回顾已保存的分析，而不是让成果消失在聊天记录里。
5. **模型配置**：使用平台模型或绑定自己的 BYOK 模型提供方。

**五阶段工作流：** Extraction 信息提取 → Research 背景研判 → Synthesis 画像合成 → Strategy 商务策略 → Critique 风险复核。

> 当前 Research 阶段基于输入和模型知识进行**有标注的推断**，不进行真实联网核查；Critique 能提示问题，但尚无独立对照实验可证明其降低事实错误的效果。

## 品牌与视觉

Cardio 的视觉语言是 **羊皮纸 × 金墨 × 东方商旅**：纸底（parchment）、墨字（ink）、铜金（brass）、玉绿（jade）、朱红（cinnabar）。扉页、侧栏、商册与研判卡片采用克制的书卷式界面，用现代交互承载传统商业往来中的记录与信任。

设计 Token 在 [cardio-web/src/index.css](cardio-web/src/index.css)；前端使用 React 19、Vite 8、Tailwind CSS 4，提供商枢对话、数字商册分析、联系人、历史与模型配置视图。

---

## 为什么业务被建模为代码

Cardio 不以“一段聊天回复”作为全部业务对象。目前已落地的模型包括：

| 业务对象 / 过程 | 软件表达 | 对用户的价值 |
| --- | --- | --- |
| 联系人 Contact | SQLite `contacts`，按 owner 隔离 | 名片与会面资料能长期积累、检索和编辑 |
| 分析 Analysis | `analyses`，关联 `contact_id` | 一次研判可关联联系人，并可在历史记录中复查 |
| 五阶段研判 | Extraction / Research / Synthesis / Strategy / Critique | 将事实提取、推断、策略和审核分开，避免混成不可复核的答案 |
| 工作流执行 | `CardioAnalyzeWorkflow` + 五个 Temporal Activity | 每一步可观测、可按策略重试；客户端中断不应丢失已提交工作流 |
| 结果持久化 | `persist_analysis` Activity + 工作流 ID 幂等键 | 避免 SSE 断连后最终分析无法落库，以及 Activity 重试重复写入 |

**架构判断：** Contact 是长期保有的业务资产；Analysis 是可重复执行的研究产物；Workflow 是执行生命周期。这三者不是一个概念，也不应由一次 HTTP 请求的生命周期统一决定。完整的商务机会（Opportunity / Engagement）生命周期尚待后续产品建模，不冒充现有实现。

**源码入口：** [API](cardio/server.py) · [分析协议](cardio/temporal/common.py) · [Temporal Workflow](cardio/temporal/workflows/analyze.py) · [Activity](cardio/temporal/activities.py) · [数据库模型](cardio/store.py)。

## 关键工程边界：Temporal 与 BYOK 安全

**本分支的 `POST /api/analyze` 必须通过 Temporal 执行五阶段分析，不再回退到 FastAPI 进程内 `run_pipeline`。** Temporal 不可用时返回 `503 TEMPORAL_UNAVAILABLE`；这要求部署时实际提供 Temporal Server、namespace 与 Worker，不能把“代码已接入”理解为“线上已接通”。

- **不传明文凭据**：Workflow 的 `AnalyzeInput` 只包含 `owner`、`provider_id`、分析文本及联系人引用。解密后的 `api_key` 不进入 Workflow 输入、Activity 参数、返回结果或进度事件。
- **Activity 内按权限解析**：Worker 在调用模型前，从数据库按 owner + Provider ID + active + text 槽位解析并解密 BYOK。删除、撤销或越权的引用会拒绝执行，不静默改走平台计费。
- **独立配额语义**：平台调用继续走受限配额和隔离缓存；BYOK 通过其提供方配置执行。重试和真实供应商成本仍须在部署验收时核对。
- **持久化完成结果**：Temporal Workflow 使用独立 Activity 写入分析记录，工作流 ID 作为幂等键。API 通过查询进度并转发 SSE；断开 SSE 不等于取消 Temporal 工作流。
- **图像输入边界**：名片图像识别当前仍在 API 内预处理，识别文本随后进入 Temporal；多模态 BYOK 在 API 调用本地解密，**不写入 Temporal History**。这不代表视觉预处理本身已实现 Temporal 恢复能力。

> 安全边界仍要求：加密主密钥由受控运维管理；Worker 能访问相同受保护数据库与密钥配置；Temporal 历史与日志按敏感业务数据保护。绝不将用户 API Key、数据库备份或解密日志提交 Git。

---

## 工程完成度与验证

| 子系统 | 仓库现状 | 验证范围 |
| --- | --- | --- |
| Web / API | React / Vite / FastAPI / JWT / SQLite | 接口和鉴权离线冒烟 |
| 五阶段分析 | 独立阶段提示词与输出对象 | `tests/test_pipeline_e2e.py` 使用合成响应回归 |
| Temporal | Workflow、Worker、五阶段 Activity、结果持久化 Activity；HTTP 已改为提交 Workflow | `tests/test_temporal_byok_boundary.py` 针对凭据边界、幂等与模拟 HTTP 提交 |
| LLM Gateway | 并发控制、超额拒绝、隔离缓存、重试与 BYOK | `tests/test_llm_quota.py`、`tests/test_runtime_boundaries.py` |
| 密钥存储 | Fernet 加密、独立 Provider 配置 | `tests/test_crypto_rotation.py`；真实密钥轮换需独立运维操作 |

**本 README 只描述仓库已有代码与测试用例，不能代替实际执行结果。** 模拟 Temporal 客户端的离线测试不等于真实 Temporal Server、Worker 重启恢复、真实 LLM、生产密钥轮换或业务效果的端到端验证。合并和部署前应以对应 SHA 的 CI 记录及实际集成环境验收为准。

### 本地开发与必需的 Temporal 服务

Python 3.12 / Node 22 / pnpm 9：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# 配置 CARDIO_JWT_SECRET、CARDIO_ENC_KEY 和授权的模型凭据
# 启动或连接有效的 Temporal Server，并事先建立 cardio namespace
export TEMPORAL_ADDRESS=127.0.0.1:7233
export TEMPORAL_NAMESPACE=cardio
export TEMPORAL_TASK_QUEUE=cardio-task-queue
python -m cardio.temporal.worker
```

在另一个终端启动 API：

```bash
python run.py
```

前端：

```bash
cd cardio-web
pnpm install --frozen-lockfile
pnpm dev
```

离线门禁：

```bash
bash scripts/preflight.sh
```

门禁涵盖语法编译、pytest、API 鉴权冒烟及前端冻结锁文件构建；**它不会自动启动 Temporal Server，也不会对真实模型提供方发请求**。完整依赖、部署与密钥旋转见 [架构说明](docs/ARCHITECTURE.md)、[部署说明](docs/DEPLOY.md) 和 [密钥轮换](docs/SECURITY_KEY_ROTATION.md)。

---

© Cardio · MiLab-Bit
