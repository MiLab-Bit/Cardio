# 测试指南

## 测试概览

**77 个测试，全部通过，零警告。**

## 测试文件

| 文件 | 测试数 | 覆盖范围 |
|------|--------|----------|
| `test_agents.py` | 8 | BaseAgent 抽象类、LLM 调用、重试、校验 |
| `test_orchestrator.py` | 8 | 编排器注册、Pipeline 流程、错误处理 |
| `test_runtime.py` | 7 | CUA Runtime、任务执行、状态查询 |
| `test_learning_loop.py` | 8 | 学习循环、权重调节、持久化 |
| `test_message_bus.py` | 8 | P2P/PubSub/Broadcast、历史裁剪 |
| `test_models.py` | 12 | 数据模型创建、序列化、扩展字段 |
| `test_infrastructure.py` | 26 | LLM 解析器(9) + 缓存层(7) + 知识库(4) + 图谱(2) + 向量存储(1) + 配置(1) |

## 运行测试

```bash
# 全部
pytest tests/ -v

# 单个文件
pytest tests/test_orchestrator.py -v

# 带覆盖率
pytest tests/ --cov=byou --cov-report=html

# 快速模式（仅失败和摘要）
pytest tests/ -q --tb=short
```

## 编写新测试

### Agent 测试模式

```python
import pytest
from unittest.mock import AsyncMock, patch

class MockAgent(BaseAgent):
    def __init__(self):
        self.name = "mock"
    def _default_prompt(self):
        return "mock prompt"
    async def execute(self, input_data):
        return {"status": "ok"}

@pytest.mark.asyncio
async def test_my_agent():
    agent = MockAgent()
    # 如果需要 mock LLM
    with patch.object(agent.client.chat.completions, "create", new_callable=AsyncMock):
        result = await agent.execute({"test": True})
    assert result["status"] == "ok"
```

### Pydantic 模型测试模式

```python
def test_create_model():
    profile = CustomerProfile(name="张三", company="阿里")
    assert profile.name == "张三"

def test_serialization():
    data = CustomerProfile(name="李四").model_dump()
    assert data["name"] == "李四"

def test_extra_fields():
    profile = CustomerProfile(custom="value")
    assert profile.custom == "value"
```

## Mock 指南

| 要 Mock 什么 | 如何 Mock |
|-------------|-----------|
| LLM API 调用 | `patch.object(agent.client.chat.completions, "create")` |
| HTTP 请求 | `patch("httpx.AsyncClient.get")` |
| 文件 I/O | `tmp_path` fixture |
| 时间 | `patch("datetime.now")` |

## 已知限制

1. 当前测试不覆盖真实 API 调用（LLM/搜索/OCR）
2. CUA 执行层使用 `asyncio.sleep` 模拟，集成浏览器时需要重写测试
3. ChromaDB 在 CI 环境可能需要额外配置
