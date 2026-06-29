# 工具层总览

## 组件

| 工具 | 文件 | 类名 | 职责 |
|------|------|------|------|
| OCR | `tools/ocr.py` | `OCRTool` | 名片图像文字识别（Tesseract / LLM Vision fallback） |
| ASR | `tools/asr.py` | `ASRTool` | 会议录音语音转录（本地 Whisper / API fallback） |
| Search | `tools/search.py` | `SearchTool` | LLM 驱动的网页搜索 |
| CRM | `tools/crm.py` | `CRMTool` | CRM 系统集成（HTTP API） |
| Knowledge | `tools/knowledge.py` | `KnowledgeBase` | 本地 JSON 文件知识库管理 |

## OCR Tool

**文件**: `byou/tools/ocr.py` → `OCRTool`

```python
class OCRTool:
    def __init__(self, language: str = "chi_sim+eng")

    async def extract_text(image_path: str) -> str:
        """提取图像文本，优先 Tesseract，fallback LLM Vision"""
```

- 支持 Tesseract OCR（本地）和 OpenAI Vision API（fallback）
- 自动检测可用引擎

## ASR Tool

**文件**: `byou/tools/asr.py` → `ASRTool`

```python
class ASRTool:
    def __init__(self, model_size: str = "base")

    async def transcribe(audio_path: str, language: str | None = None) -> str:
        """转录音频为文本，优先本地 Whisper，fallback Whisper API"""
```

- 支持本地 openai-whisper 模型和 OpenAI Whisper API
- 自动检测可用引擎

## Search Tool

**文件**: `byou/tools/search.py` → `SearchTool`

```python
class SearchTool:
    async def search(query: str, max_results: int = 5, source: str = "web") -> list[dict]:
        """LLM 驱动的网页搜索"""

    async def search_company(company_name: str) -> dict:
        """企业信息搜索"""

    async def search_person(person_name: str, company: str = "") -> dict:
        """人物背景搜索"""
```

- 当前通过 LLM 模拟搜索结果
- 共享 `byou.core.llm_client` 客户端连接池

## CRM Tool

**文件**: `byou/tools/crm.py` → `CRMTool`

```python
class CRMTool:
    def __init__(self):
        """从 settings 读取 crm_api_url 和 crm_api_key"""

    async def connect() -> bool
    async def create_or_update_contact(contact_data: dict) -> dict
    async def add_note(contact_id: str, note: str) -> dict
    async def create_task(task_data: dict) -> dict
    async def close()
```

- 通过 `httpx.AsyncClient` 连接外部 CRM
- 配置来自 `.env` 中的 `CRM_API_URL` / `CRM_API_KEY`

## Knowledge Base

**文件**: `byou/tools/knowledge.py` → `KnowledgeBase`

```python
class KnowledgeBase:
    def __init__(self, base_path: str = "./data/knowledge")

    async def store(category: str, key: str, data: dict) -> bool
    async def retrieve(category: str, key: str) -> Optional[dict]
    async def search(query: str, category: Optional[str] = None) -> list[dict]
    async def list_categories() -> list[str]
```

- 分类存储（6 类：industry_insights, competitor_intel, bd_scripts, objection_handling, success_cases, failed_cases）
- 每类一个目录，每条知识一个 JSON 文件

## 工具使用原则

1. 所有工具返回 `dict` 或 `str`，统一数据格式
2. 工具不持有全局状态（除 KnowledgeBase/Cache 外）
3. 工具可在 Agent 内直接实例化，也可通过依赖注入
4. OCR/ASR 支持双引擎：本地优先，API fallback，优雅降级
