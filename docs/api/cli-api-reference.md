# CLI & API 参考

## CLI

**入口**: `python main.py` 或 `byou`（安装后）

### 全局选项

| 选项 | 说明 |
|------|------|
| `--version` | 显示版本号 |
| `--help` | 帮助信息 |

### 命令

#### `pipeline` — 执行完整 Pipeline

```bash
python main.py pipeline \
  --card /path/to/card.jpg \
  --audio /path/to/meeting.mp3 \
  --output result.json \
  --context '{"sales_rep": "李四"}' \
  --skip researcher,strategist
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--card`, `-c` | 否 | 名片图片路径 |
| `--audio`, `-a` | 否 | 录音文件路径 |
| `--output`, `-o` | 否 | 输出 JSON 路径（默认 `pipeline_result.json`） |
| `--context` | 否 | 额外上下文（JSON 字符串，默认 `{}`） |
| `--skip` | 否 | 跳过的 Agent 阶段（可多选，如 `researcher,synthesizer,strategist,critic`） |

#### `extract` — 仅信息提取

```bash
python main.py extract --card /path/to/card.jpg
```

#### `research` — 仅客户背调

```bash
python main.py research --company "华为技术有限公司" --person "张三"
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--company`, `-c` | 是 | 公司名称 |
| `--person`, `-p` | 否 | 联系人姓名 |

#### `status` — 查看系统状态

```bash
python main.py status
```

输出：版本、状态、执行统计、趋势、Agent 权重表。

#### `serve` — 启动 API 服务

```bash
python main.py serve --host 127.0.0.1 --port 8000
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--host` | `127.0.0.1` | 监听地址 |
| `--port` | `8000` | 监听端口 |

## REST API

**基础路径**: `http://localhost:8000`

### `GET /health`

健康检查。

```
→ 200 {"status": "ok", "version": "0.1.0"}
```

### `POST /pipeline`

执行完整 Pipeline（通过文件路径）。

**请求体**:
```json
{
    "card_image_path": "/path/to/card.jpg",
    "audio_file_path": "/path/to/meeting.mp3",
    "context": {}
}
```

**响应**: 完整 PipelineContext

### `POST /pipeline/upload`

上传文件并执行 Pipeline。

**请求**: `multipart/form-data`
- `card`: 图片文件（可选）
- `audio`: 音频文件（可选）

**安全校验**: 文件扩展名白名单、MIME 类型白名单、大小上限（均通过 Settings 配置）。

**响应**: Pipeline 执行摘要（通过 `context.get_summary()`）

### `POST /research`

执行客户背调。

**请求体**:
```json
{
    "company_name": "华为",
    "person_name": "张三"
}
```

### `GET /insights`

获取 Learning Loop 洞察。

```json
{
    "total_executions": 42,
    "recent_avg_trust_score": 0.82,
    "recent_quality_pass_rate": 0.85,
    "trend": "improving",
    "strategy_weights": { ... }
}
```

### `GET /knowledge/categories`

列出知识库分类。

```json
{"categories": ["bd_scripts (3)", "success_cases (1)", ...]}
```

## .env 配置

```env
# LLM
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat

# 向量数据库
BYOU_VECTOR_DB_PATH=./data/vector_store

# 数据目录
BYOU_DATA_DIR=./data

# CRM 集成（可选）
CRM_API_URL=
CRM_API_KEY=

# 日志级别: DEBUG, INFO, WARNING, ERROR
BYOU_LOG_LEVEL=INFO

# 最大并发 Agent 数
BYOU_MAX_CONCURRENT_AGENTS=5

# 知识库配置
BYOU_KNOWLEDGE_BASE_PATH=./data/knowledge
```

所有环境变量通过 `byou.config.Settings`（pydantic-settings）加载，支持字段别名映射（如 `OPENAI_API_KEY` → `openai_api_key`）。

## pyproject.toml

```toml
[project]
name = "byou"
version = "0.1.0"
requires-python = ">=3.10"

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "pytest-cov", "ruff", "mypy"]
ocr = ["pytesseract"]
asr = ["openai-whisper"]

[project.scripts]
byou = "byou.cli:cli"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
```
