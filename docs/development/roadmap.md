# 开发路线图

## 当前版本: v0.1.0（基础框架）

✅ 已完成：

- [x] Multi-Agent 架构（5 Agent + Orchestrator）
- [x] CUA 6 层架构
- [x] 消息总线（Memory 实现）
- [x] 学习循环（权重调节 + 持久化）
- [x] 基础设施（Vector Store / Graph Store / Cache）
- [x] 工具层骨架（OCR / ASR / Search / CRM / Knowledge）
- [x] 数据模型（Pydantic v2）
- [x] CLI（click + rich）
- [x] API（FastAPI）
- [x] 77 个测试全部通过
- [x] 完整产品文档

## v0.2.0 — 基础设施增强

- [ ] OCR 真实 Tesseract 集成测试（已编码，待验证）
- [ ] ASR 真实 Whisper 集成测试（已编码，待验证）
- [ ] Search 真实搜索引擎 API 集成
- [ ] Pipeline 端到端集成测试（真实 LLM）

## v0.3.0 — 策略闭环

- [ ] Synthesizer 评分模型校准
- [ ] Strategist 话术模板库
- [ ] Knowledge Base 批量导入
- [ ] CRM 集成对接（已编码 HTTP 客户端，待真实 API）
- [ ] 交互记录追踪生命周期

## v0.4.0 — CUA + Playwright 联调（框架已完成）

- [x] BrowserManager（Playwright + MS Edge 通道）
- [x] CUA Perception 真实 DOM 感知（browser 模式）
- [x] CUA Execution 真实浏览器操作（browser 模式）
- [ ] CUA+Playwright 端到端集成测试
- [ ] 元素定位策略优化（CSS / XPath / ARIA / 视觉）

## v0.5.0 — 生产就绪

目标：可部署

- [ ] Docker 容器化
- [ ] 配置文件（YAML/TOML 统一配置）
- [ ] 日志系统（结构化日志 + 级别控制）
- [ ] 监控埋点（Pipeline 耗时 / Agent 成功率）
- [ ] API 鉴权（API Key / JWT）
- [ ] 异步任务队列（Celery / 自研）

## v1.0.0 — 产品化

目标：面向最终用户可用

- [ ] Web UI（管理后台）
- [ ] 企业微信/钉钉/飞书 Bot 接入
- [ ] 数据导出（Excel / PDF 报表）
- [ ] 多租户支持
- [ ] 国际化（多语言名片识别）
- [ ] 压力测试 & 性能优化

---

## 待确定的技术决策

### 1. 技术栈结论

**已确定：纯 Python 后端**。浏览器自动化通过 Playwright + 系统 Edge 浏览器实现（MS Edge 通道），无需额外 Chromium 下载。

前端 UI / 移动端另起项目（不在本仓库范围内）。

### 2. LLM Provider

当前使用 DeepSeek API（兼容 OpenAI SDK），通过 `OPENAI_BASE_URL` 可切换任意兼容 provider。

### 3. 数据库

当前使用：文件系统（JSON / ChromaDB）+ 配置化 CRM。生产环境按需引入 SQLite / PostgreSQL。
