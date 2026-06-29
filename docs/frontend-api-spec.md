# Byou API — 前端对接文档

> 版本 0.1.0 | 后端技术栈: FastAPI + Pydantic | 默认地址 http://127.0.0.1:8000

---

## 1. 快速概览

| 端点 | 方法 | 用途 | 典型响应时间 |
|------|------|------|------------|
| `/health` | GET | 健康检查 | <10ms |
| `/pipeline` | POST | 文件路径方式跑流水线 | 30-120s |
| `/pipeline/upload` | POST | 上传文件跑流水线 | 30-120s |
| `/pipeline/upload/stream` | POST | 上传+SSE实时进度 | 30-120s |
| `/research` | POST | 单独做背调 | 5-20s |
| `/insights` | GET | 学习循环数据 | <50ms |
| `/history` | GET | 历史执行记录 | <50ms |

**注意:** CORS 已开启（`*`），前端无需代理即可跨域调用。

---

## 2. 端点详情

### 2.1 `GET /health`

**Response 200:**
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

### 2.2 `POST /pipeline`

传服务器本地已有文件的路径。

**Request:**
```json
{
  "card_image_path": "/data/cards/zhangsan.png",
  "audio_file_path": "/data/audio/meeting.mp3",
  "context": {}
}
```
字段全可选。不传 `card_image_path` 和 `audio_file_path` 也行，会跳过提名片/录音步骤。

**Response 200 — 完整 PipelineContext:**

见下方 [数据模型 → PipelineContext](#33-pipelinecontext)。

### 2.3 `POST /pipeline/upload`

上传文件的方式跑流水线。返回值与 `/pipeline` 完全相同：完整 PipelineContext。

**Request:** `multipart/form-data`
| 字段 | 类型 | 必填 |
|------|------|------|
| `card` | file | 否 |
| `audio` | file | 否 |

Content-Type 必须设 `multipart/form-data`。

**文件限制:**
| 限制 | 值 |
|------|-----|
| 最大体积 | 10 MB |
| 图片类型 | png, jpg, jpeg, webp, tiff, tif |
| 音频类型 | mp3, wav, ogg, m4a |

**Response 200 — 完整 PipelineContext，同 /pipeline**

**Response 400 — 文件校验失败:**
```json
{
  "detail": "File type .exe not allowed. Allowed: ['.png', '.jpg', ...]"
}
```

### 2.4 `POST /pipeline/upload/stream`

上传文件 + SSE 实时进度推送。**推荐前端默认使用这个。**

**Request:** 同 `/pipeline/upload`（multipart/form-data）

**Response:** `text/event-stream`

SSE 事件流格式：
```
data: {"stage":"extraction"}
data: {"stage":"extraction_done"}
data: {"stage":"research"}
data: {"stage":"research_done"}
data: {"stage":"synthesis"}
data: {"stage":"synthesis_done"}
data: {"stage":"strategy"}
data: {"stage":"strategy_done"}
data: {"stage":"critique"}
data: {"stage":"critique_done"}
data: {"stage":"pipeline_done","data":{...完整 PipelineContext...}}
```
出错时：
```
data: {"stage":"pipeline_error","error":"错误信息"}
```

**stage 枚举值：** `extraction` / `extraction_done` / `research` / `research_done` / `synthesis` / `synthesis_done` / `strategy` / `strategy_done` / `critique` / `critique_done` / `pipeline_done` / `pipeline_error`

前端通过 `EventSource` 接收，最后一个 `pipeline_done` 事件携带完整 PipelineContext。

### 2.5 `POST /research`

单独跑背调，不走完整流水线。

**Request:**
```json
{
  "company_name": "字节跳动",
  "person_name": "张三"
}
```

**Response 200 — ResearchResult:**
```json
{
  "company_info": {},
  "industry_analysis": "互联网/科技行业...",
  "person_background": {},
  "news_mentions": [],
  "competitors": [],
  "market_position": "头部企业"
}
```

### 2.6 `GET /insights`

获取学习循环的统计数据。

**Response 200:**
```json
{
  "total_executions": 42,
  "recent_avg_trust_score": 0.78,
  "recent_avg_intent_score": 0.83,
  "recent_quality_pass_rate": 0.91,
  "trend": "improving",
  "strategy_weights": {
    "extractor": 1.05,
    "researcher": 0.98,
    "synthesizer": 1.02,
    "strategist": 1.10,
    "critic": 0.95
  }
}
```

### 2.7 `GET /history`

获取历史执行记录列表，按时间倒序。

**Query Params:**
| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `limit` | int | 20 | 返回条数，最大 100 |

**Response 200:**
```json
{
  "total": 42,
  "limit": 20,
  "records": [
    {
      "timestamp": "2026-06-28T04:30:00",
      "metrics": {
        "trust_score": 0.85,
        "intent_score": 0.90,
        "quality_passed": 1.0
      },
      "stages": ["extraction", "research", "synthesis", "strategy", "critique"]
    }
  ]
}
```

每条 record 的结构：
```typescript
interface HistoryRecord {
  timestamp: string;          // ISO datetime
  metrics: {
    trust_score: number;
    intent_score: number;
    quality_passed: number;   // 1.0 = passed, 0.0 = failed
  };
  stages: string[];           // 执行的阶段名列表
}
```

---

## 3. 数据模型

全部字段都是 Pydantic 的 snake_case，直接传给前端用。

### 3.1 CustomerProfile

```typescript
interface CustomerProfile {
  name: string;              // 姓名
  title: string;             // 职位
  company: string;           // 公司
  department: string;        // 部门
  phone: string;             // 电话
  email: string;             // 邮箱
  wechat: string;            // 微信
  address: string;           // 地址
  industry: string;          // 行业
  company_size: string;      // 公司规模
  company_description: string; // 公司简介
  personal_summary: string;  // 个人简介
  source: string;            // 来源: card/audio/manual
  extracted_at: string|null; // 提取时间 ISO
  confidence: number;        // 置信度 0-1
}
```

### 3.2 BDStrategy — BD 策略（前端核心展示数据）

```typescript
interface TalkingPoint {
  angle: string;         // 切入角度
  script: string;        // 参考话术
  key_message: string;   // 核心信息
}

interface FollowUpPlan {
  timing: string;        // 建议联系时间
  channel: "phone"|"email"|"wechat";  // 渠道
  approach: string;      // 跟进策略
  priority: "high"|"medium"|"low";    // 优先级
}

interface BDRisk {
  type: string;          // 风险类型
  description: string;   // 风险描述
  severity: "high"|"medium"|"low";  // 严重程度
  mitigation: string;    // 缓解措施
}

interface BDStrategy {
  customer_analysis: string;          // 客户需求分析
  pain_points: string[];              // 客户痛点
  opportunities: string[];            // 商业机会
  talking_points: TalkingPoint[];     // 谈话要点
  objection_handling: Record<string,string>; // 异议处理
  follow_up_plan: FollowUpPlan|null;  // 跟进计划
  risks: BDRisk[];                    // 风险评估
  competition_analysis: string;       // 竞争分析
  recommended_actions: string[];      // 推荐行动
  confidence_level: number;           // 策略置信度 0-1
  generated_at: string;               // ISO datetime
  version: string;                    // "1.0"
}
```

### 3.3 PipelineContext — 完整流水线结果（`/pipeline` 返回）

```typescript
interface PipelineContext {
  id: string|null;
  started_at: string;
  completed_at: string|null;
  card_image_path: string|null;
  audio_file_path: string|null;
  extra_context: Record<string,any>;
  // 各阶段输出
  raw_extraction: Record<string,any>;
  raw_text: string;
  profile: CustomerProfile|null;
  research_result: Record<string,any>;
  synthesis_result: Record<string,any>;
  strategy_result: Record<string,any>;
  critique_result: Record<string,any>;
  // 评分
  intent_score: number|null;
  customer_level: string|null;   // "A"/"B"/"C" 等
  trust_score: number|null;
  quality_passed: boolean|null;
  // 风险与错误
  risk_alerts: string[];
  errors: string[];
}
```

### 3.4 流水线各阶段输出字段（放在 `*_result` 里）

**research_result:**
```typescript
{
  company_info: Record<string,any>;   // 公司背景
  industry_analysis: string;          // 行业分析
  person_background: Record<string,any>; // 人物背景
  news_mentions: string[];            // 相关新闻
  competitors: string[];              // 竞品
  market_position: string;            // 市场地位
}
```

**synthesis_result:**
```typescript
{
  enriched_profile: Record<string,any>; // 补充后的客户画像
  intent_score: number;                 // 意向评分
  customer_level: string;               // 客户等级
}
```

**strategy_result:**
```typescript
{
  strategy: BDStrategy;  // 完整 BD 策略对象
}
```

**critique_result:**
```typescript
{
  trust_score: number;        // 信任度评分
  risk_alerts: string[];      // 风险警报列表
  passed: boolean;            // 质量审核是否通过
  feedback: string;           // 审核意见
}
```

---

## 4. 前端实现建议

### 4.1 SSE 实时进度（推荐）

推荐前端默认使用 `/pipeline/upload/stream`，通过 SSE 获取实时阶段推送。

```typescript
const BASE = "http://127.0.0.1:8000";

// SSE 方式 —— 有实时进度
const STAGE_MAP: Record<string, { label: string; pct: number }> = {
  extraction:      { label: "提取名片/录音信息",  pct: 15 },
  extraction_done: { label: "提取完成",            pct: 20 },
  research:        { label: "背调研究",            pct: 35 },
  research_done:   { label: "研究完成",            pct: 40 },
  synthesis:       { label: "客户画像合成",        pct: 55 },
  synthesis_done:  { label: "合成完成",            pct: 60 },
  strategy:        { label: "BD 策略生成",          pct: 75 },
  strategy_done:   { label: "策略生成完成",        pct: 80 },
  critique:        { label: "质量审核",            pct: 95 },
  critique_done:   { label: "审核完成",            pct: 100 },
};

async function runPipelineWithProgress(
  cardFile: File,
  audioFile?: File,
  onProgress?: (label: string, pct: number) => void,
  onError?: (msg: string) => void,
): Promise<PipelineContext> {
  const form = new FormData();
  if (cardFile) form.append("card", cardFile);
  if (audioFile) form.append("audio", audioFile);

  const res = await fetch(`${BASE}/pipeline/upload/stream`, {
    method: "POST",
    body: form,
  });

  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail);
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: PipelineContext | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const event = JSON.parse(line.slice(6));
        if (event.stage === "pipeline_done") {
          result = event.data as PipelineContext;
        } else if (event.stage === "pipeline_error") {
          onError?.(event.error);
          throw new Error(event.error);
        } else {
          const info = STAGE_MAP[event.stage];
          if (info) onProgress?.(info.label, info.pct);
        }
      }
    }
  }

  return result!;
}
```

### 4.2 普通请求（无进度）

```typescript
const BASE = "http://127.0.0.1:8000";

// 上传文件（无进度推送）
async function runPipelineUpload(cardFile: File, audioFile?: File) {
  const form = new FormData();
  if (cardFile) form.append("card", cardFile);
  if (audioFile) form.append("audio", audioFile);

  const res = await fetch(`${BASE}/pipeline/upload`, {
    method: "POST",
    body: form,
    signal: AbortSignal.timeout(180_000),
  });
  if (!res.ok) { const err = await res.json(); throw new Error(err.detail); }
  return res.json(); // → PipelineContext
}

// 历史记录
async function getHistory(limit = 20) {
  const res = await fetch(`${BASE}/history?limit=${limit}`);
  return res.json();
}
```

### 4.3 错误处理

```typescript
interface ApiError {
  detail: string;
}

// 常见 HTTP 状态码
// 400 — 文件类型/大小不符
// 422 — 请求参数格式错误（FastAPI 自动校验）
// 500 — 流水线内部异常，检查 errors 数组
```

### 4.4 前端页面建议

**首页/Dashboard:**
- 调 `/insights` 展示统计数据卡片（总执行次数、通过率、趋势）
- Agent 权重可视化（条形图或雷达图）

**流水线页:**
- 上传区域（拖拽名片图片 / 录音文件）
- 分步进度指示器
- 结果面板：左侧客户画像（Profile），右侧 BD 策略（TalkingPoint + FollowUpPlan + Risks）

**客户详情页:**
- 所有 CustomerProfile 字段
- 背调结果（ResearchResult）
- 策略卡片（BDStrategy）

---

## 5. 待改进点

| 问题 | 状态 | 说明 |
|------|------|------|
| ~~无实时进度推送~~ | ✅ 已解决 | `/pipeline/upload/stream` SSE |
| ~~`/pipeline/upload` 返回值不同~~ | ✅ 已解决 | 统一返回 PipelineContext |
| ~~无历史记录~~ | ✅ 已解决 | `/history?limit=N` |
| ~~CORS 未配置~~ | ✅ 已解决 | `allow_origins=["*"]` |
| 无请求防抖/并发控制 | 待优化 | 多人同时触发可能资源争抢 |

---

## 6. 后端项目结构（给前端了解上下文）

```
byou/
├── api.py           ← FastAPI 路由在这里
├── models/
│   └── customer.py  ← 所有数据模型定义
├── core/
│   ├── orchestrator.py  ← 流水线编排
│   └── runtime.py       ← 浏览器自动化
├── agents/
│   └── configs.py   ← Agent LLM prompt 模板
├── cua/             ← Computer-Use Agent 三层
├── tools/           ← OCR/ASR/搜索/CRM 工具
└── config/
    └── settings.py  ← 全局配置
```
