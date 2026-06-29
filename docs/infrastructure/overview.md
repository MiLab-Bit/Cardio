# 基础设施总览

## 组件

| 组件 | 文件 | 技术选型 | 职责 |
|------|------|----------|------|
| LLM Client | `core/llm_client.py` | OpenAI SDK (shared pool) | 全局共享 AsyncOpenAI 连接池 |
| LLM Parser | `core/llm_parser.py` | JSON + regex | 从 LLM 输出中提取 JSON（fenced/raw/nested） |
| Config | `config/settings.py` | pydantic-settings | 统一配置（.env 加载 + 别名映射） |
| Browser | `infrastructure/browser.py` | **Playwright (Edge 通道)** | 页面池、DOM 感知、截图、自动化操作 |
| Vector Store | `infrastructure/vector_store.py` | ChromaDB | 语义检索（客户画像、历史案例） |
| Graph Store | `infrastructure/graph_store.py` | NetworkX | 客户关系图谱 |
| Cache Layer | `infrastructure/cache.py` | 内存 LRU + 文件 | 多层缓存减少 LLM 调用 |

## LLM Client (共享连接池)

**文件**: `byou/core/llm_client.py`

```python
from byou.core.llm_client import get_client, reset_client

client = get_client()  # 全局单例 AsyncOpenAI，复用 HTTP 连接
```

所有 Agent 和 Tool 通过 `get_client()` 获取共享客户端，避免重复创建连接。

## LLM Parser (统一 JSON 提取)

**文件**: `byou/core/llm_parser.py`

```python
from byou.core.llm_parser import parse_llm_json

parse_llm_json(output: str, *, strict: bool = False) -> dict
```

支持格式：
- 纯 JSON 字符串
- `` ```json ... ``` `` fenced block
- `` ``` ... ``` `` untyped block  
- 大括号匹配（best-effort）
- `strict=True` 时解析失败抛异常

## Config (统一配置)

**文件**: `byou/config/settings.py` → `Settings`

所有配置集中在 `Settings` pydantic-settings 类，通过 `.env` 文件和环境变量加载。支持字段别名（如 `OPENAI_API_KEY` → `openai_api_key`）。

```python
from byou.config import get_settings

s = get_settings()
print(s.openai_api_key, s.log_level, s.max_concurrent_pipelines)
```

## Browser (Playwright)

**文件**: `byou/infrastructure/browser.py` → `BrowserManager`

使用系统 Edge 浏览器（`channel="msedge"`），无需额外下载 Chromium。

```python
from byou.infrastructure.browser import BrowserManager

bm = BrowserManager(channel="msedge", headless=True)
await bm.start()
await bm.navigate(task_id, "https://example.com")
elements = await bm.extract_elements(task_id)
text = await bm.extract_text(task_id)
screenshot = await bm.screenshot(task_id)
await bm.click(task_id, "#button")
await bm.type_text(task_id, "#input", "hello")
await bm.stop()
```

## Vector Store（向量存储）

**文件**: `byou/infrastructure/vector_store.py` → `VectorStore`

### 核心接口

```python
class VectorStore:
    async def initialize()
    async def add(collection: str, documents: list[str], ids: list[str], metadatas: list[dict] | None = None)
    async def search(collection: str, query: str, top_k: int = 5) -> list[dict]
    async def get_stats() -> dict
```

## Graph Store（图谱存储）

**文件**: `byou/infrastructure/graph_store.py` → `GraphStore`

```python
class GraphStore:
    async def initialize()
    async def add_person(node_id: str, name: str, properties: dict | None = None) -> bool
    async def add_company(node_id: str, name: str, properties: dict | None = None) -> bool
    async def add_relationship(from_id: str, to_id: str, rel_type: str) -> bool
    async def get_neighbors(node_id: str, depth: int = 1) -> dict
    async def search_nodes(query: str) -> list
    async def get_stats() -> dict
```

## Cache Layer（缓存层）

**文件**: `byou/infrastructure/cache.py` → `CacheLayer`

### 缓存策略

| 数据类型 | 缓存时长 | 存储 |
|---------|---------|------|
| LLM 响应 | 1 小时 (可配) | 内存 LRU |
| 公司搜索结果 | 24 小时 | 磁盘 JSON |
| 客户画像 | 7 天 | 磁盘 JSON |
| 知识库查询 | 永久 | 磁盘 JSON |

### 核心接口

```python
class CacheLayer:
    def get(key: str) -> Optional[Any]
    def set(key: str, value: Any) -> None
    def delete(key: str) -> None
    def clear() -> None
    def get_stats() -> dict
```
