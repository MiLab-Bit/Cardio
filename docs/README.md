# Byou (Business You) — 产品设计文档

> **版本**: v0.1.0 | **最后更新**: 2026-06-27 | **状态**: 初始开发阶段

## 产品定位

**Byou = Business You** — BD（商务拓展）智能客户管理 Multi-Agent 系统。

面向销售、BD、客户成功团队，将名片识别、客户背调、画像建模、策略生成、质量审核整合为端到端自动化 Pipeline。

## 核心价值

| 痛点 | Byou 解决方式 |
|------|--------------|
| 会后信息散落 | OCR + ASR 自动结构化录入 |
| 客户背调耗时 | 多源搜索 + 知识图谱自动聚合 |
| 策略靠经验 | Multi-Agent 协作生成 BD 策略 |
| 质量无保障 | Critic Agent 内置质检 |

## 文档导航

### 架构设计
- [系统总览](architecture/overview.md)
- [Pipeline 流程](architecture/pipeline.md)
- [CUA 6 层架构](cua/overview.md)
- [编排器设计](architecture/orchestrator.md)

### Agent 体系
- [Agent 总览](agents/overview.md)
- [Extractor — 信息提取](agents/extractor.md)
- [Researcher — 客户背调](agents/researcher.md)
- [Synthesizer — 画像合成](agents/synthesizer.md)
- [Strategist — BD 策略](agents/strategist.md)
- [Critic — 质检审核](agents/critic.md)

### 数据模型
- [数据模型设计](models/data-model.md)

### 基础设施
- [基础设施总览](infrastructure/overview.md)
- [LLM 客户端 & 解析器](infrastructure/llm-client.md)
- [浏览器自动化 (Playwright)](infrastructure/browser.md)
- [配置系统](infrastructure/config.md)
- [消息总线](infrastructure/message-bus.md)
- [学习循环](infrastructure/learning-loop.md)

### 工具层
- [工具层总览](tools/overview.md)

### CUA 层
- [CUA 6 层详解](cua/overview.md)

### API / CLI
- [CLI & API 参考](api/cli-api-reference.md)

### 开发指南
- [环境搭建](development/setup.md)
- [测试指南](development/testing.md)
- [开发路线图](development/roadmap.md)
