# 开发环境搭建

## 前置要求

- Python 3.12+
- pip 24+

## 步骤

### 1. 克隆项目

```bash
cd Z:\Dev\Byou
```

### 2. 创建虚拟环境

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
source .venv/bin/activate # Mac/Linux
```

### 3. 安装依赖

```bash
# 基础依赖
pip install pydantic openai httpx click rich python-dotenv pydantic-settings

# 基础设施
pip install chromadb networkx

# 浏览器自动化（使用系统 Edge，无需额外 Chromium）
pip install playwright
playwright install --no-shell

# API 服务（可选）
pip install uvicorn fastapi python-multipart

# 开发依赖
pip install pytest pytest-asyncio pytest-cov
```

或一键安装：

```bash
pip install -e ".[dev]"
```

### 4. 配置环境变量

```bash
copy .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY
```

### 5. 验证安装

```bash
python main.py status
pytest tests/ -v
```

## 项目结构

```
byou/
├── core/           # 核心（Orchestrator, CUA, Bus, Learning）
├── agents/         # 5 个 Agent
├── cua/            # CUA 6 层
├── models/         # 数据模型
├── tools/          # 工具层
├── infrastructure/ # 基础设施
├── cli.py          # CLI入口
└── api.py          # API入口

tests/              # 测试
docs/               # 文档
data/               # 运行时数据（ChromaDB, Cache, Learning）
```

## 开发流程

1. **修改 Agent**: 编辑 `byou/agents/*.py`，遵循 `BaseAgent` 接口
2. **添加工具**: 在 `byou/tools/` 下新建文件
3. **修改模型**: 编辑 `byou/models/*.py`（Pydantic v2）
4. **运行测试**: `pytest tests/ -v`
5. **查看文档**: 参考 `docs/` 目录

## 常用命令

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定测试
pytest tests/test_orchestrator.py -v

# 带覆盖率
pytest tests/ --cov=byou --cov-report=term-missing

# 代码质量
pytest tests/ -v --tb=short -q
```
