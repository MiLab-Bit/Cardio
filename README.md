# Byou (Business You) — BD 智能客户管理 Multi-Agent 系统

> **Business You** — 你的 AI 商务分身，让客户管理从体力活变成自动化。

## 📋 概述

Byou 是一个面向商务拓展（BD/销售）场景的 **Multi-Agent 智能客户管理系统**。

**核心能力**：
- 📇 自动处理名片、会议录音等非结构化信息
- 🔍 多 Agent 协作完成客户背调、画像建模、BD 策略制定
- 📊 输出可直接用于 CRM 的结构化客户情报
- 🧠 基于 CUA (Computer-Use Agent) 实现自动化操作
- 🔄 持续学习和自我优化（Learning Loop）

## 🏗️ 系统架构

### Multi-Agent 协作层

```
输入(名片/录音) → Extractor → Researcher → Synthesizer → BD Strategist → Critic → 输出(CRM/话术)
```

| Agent | 职责 | 输入 | 输出 |
|-------|------|------|------|
| **Extractor** | 信息提取 | 名片图片、录音文件 | 结构化字段（姓名/公司/职位/电话等） |
| **Researcher** | 背调研究 | 公司名、人名 | 公司背景、行业地位、人物履历 |
| **Synthesizer** | 客户画像建模 | 提取+研究结果 | 客户等级、意向评分、关键需求 |
| **BD Strategist** | 策略顾问 | 客户画像 | 跟进策略、话术建议、切入角度 |
| **Critic** | 质检审核 | 全部中间结果 | 可信度评分、风险提醒、修正建议 |

### CUA (Computer-Use Agent) 运行时

6 层架构：感知层 → 语义对齐 → 状态建模 → 规划层 → 执行层 → 校验层

### Adaptive Harness Runtime

- **Thinking Plane** — 多 Agent 协作编排
- **Execution Plane** — CUA 任务执行
- **Learning Loop** — 结果反馈与策略优化

## 🚀 快速开始

### 安装

```bash
# 克隆项目
git clone <repo-url> Byou
cd Byou

# 安装依赖
pip install -e .

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key
```

### 使用

```bash
# CLI 模式
byou process --card ./business_card.jpg
byou process --audio ./meeting.mp3
byou process --card card.jpg --audio meeting.mp3

# 交互模式
byou interactive

# 启动 API 服务
byou serve --port 8000
```

## 📁 目录结构

```
Byou/
├── byou/                   # 主包
│   ├── core/               # 运行时核心
│   │   ├── orchestrator.py  # Adaptive Harness Runtime
│   │   ├── runtime.py       # CUA Runtime
│   │   ├── learning_loop.py # 持续学习
│   │   └── message_bus.py   # 消息总线
│   ├── agents/             # Multi-Agent 实现
│   ├── models/             # 数据模型
│   ├── tools/              # 工具集成
│   ├── infrastructure/     # 基础设施
│   ├── cua/                # Computer-Use Agent
│   └── cli.py              # CLI 入口
├── config/                 # 配置文件
├── prompts/                # Agent Prompt 模板
├── tests/                  # 测试
└── docs/                   # 文档
```

## 🔧 技术栈

- **语言**: Python 3.10+
- **LLM**: OpenAI API (兼容)
- **向量数据库**: ChromaDB
- **关系图谱**: NetworkX
- **OCR**: Tesseract
- **ASR**: OpenAI Whisper

## 📄 License

MIT
