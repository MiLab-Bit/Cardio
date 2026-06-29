# CUA 6 层架构

> CUA = Computer Use Agent — 将高层任务转化为具体界面操作的 6 层计算架构

## 架构图

```
┌──────────────────────────────────────────────────────┐
│                   CuaRuntime                          │
│         (协调 6 层执行，管理任务生命周期)              │
├──────────────────────────────────────────────────────┤
│                                                       │
│  L1  Perception ──→ L2  Semantic ──→ L3  State      │
│      (感知)            (语义对齐)        (状态建模)   │
│                                                       │
│  L6  Validation ←── L5  Execution ←── L4  Planning  │
│      (校验)            (执行)            (规划)       │
│                                                       │
└──────────────────────────────────────────────────────┘
```

## 逐层详解

### L1: Perception（感知层）

**文件**: `byou/cua/perception.py` → `PerceptionLayer`

**职责**: 感知当前界面状态。支持 Playwright 真实 DOM 提取和无浏览器回退两种模式。

**核心方法**:
```python
class PerceptionLayer:
    def __init__(self, browser_manager: Optional[BrowserManager] = None)
    def set_browser(browser_manager: BrowserManager)
    async def process(task, context) -> dict

    # 内部分流：
    # - 有 browser 且 task 有 target_url → _perceive_from_browser
    # - 否则 → _perceive_from_context (回退)
```

**Playwright 模式输出**:
```python
{
    "url": str,
    "title": str,
    "elements": [ { "index", "tag", "type", "id", "text", "visible", "enabled", "rect", "selector" } ],
    "text_content": str,        # ≤5000 字符
    "screenshot_ref": str,      # "memory://{task_id}/screenshot"
    "viewport": {"width": 1920, "height": 1080},
    "element_count": int,
    "visible_element_count": int,
    "source": "playwright",
}
```

### L2: Semantic Alignment（语义对齐层）

**文件**: `byou/cua/semantic_align.py` → `SemanticAlignLayer`

**职责**: 将原始 UI 元素映射到业务语义。

**映射规则**:
| UI 元素 | 语义类型 | 可用操作 |
|---------|----------|---------|
| `input` (含 "password") | password_input | type, clear |
| `input` | text_input | type, clear |
| `button` (含 submit/confirm/ok) | submit_button | click |
| `button` | action_button | click |
| `link` | navigation_link | click, hover |
| `table` | data_table | click, scroll |

**意图推断** (action_map):
- "搜索"/"search" → 搜索意图
- "登录"/"signin" → 登录意图
- "提交"/"submit" → 提交意图
- "下一页"/"next" → 翻页意图
- "关闭"/"close" → 关闭意图

### L3: State Modeling（状态建模层）

**文件**: `byou/cua/state_modeling.py` → `StateModelingLayer`

**职责**: 构建和维护操作状态模型。

**状态枚举**:
```python
class PageState(Enum):
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"
    PROCESSING = "processing"
    COMPLETE = "complete"
```

**异常检测**:
- 预期元素未出现 → anomaly
- 连续 3 步页面无变化 → "页面连续3步无变化，可能卡住"
- 出现 error/404/500 文本 → `PageState.ERROR`

### L4: Planning（规划层）

**文件**: `byou/cua/planning.py` → `PlanningLayer`

**职责**: 将任务分解为原子操作序列。

**操作类型**:
| 操作 | 说明 |
|------|------|
| `navigate` | 导航到 URL |
| `click` | 点击元素 |
| `type` | 输入文本 |
| `wait` | 等待 |
| `refresh` | 刷新页面 |
| `scroll` | 滚动页面 |

**后备计划**: 每份主计划附带 fallback（重试上一步 + 通知人工）。

### L5: Execution（执行层）

**文件**: `byou/cua/execution.py` → `ExecutionLayer`

**职责**: 逐步骤执行操作计划。**支持 Playwright 真实浏览器操作和无浏览器模拟两种模式。**

```python
class ExecutionLayer:
    def __init__(self, browser_manager: Optional[BrowserManager] = None)
    def set_browser(browser_manager: BrowserManager)
    async def process(action_plan, context) -> dict

    # 内部分流：
    # - 有 browser → _execute_with_browser (Playwright 真实操作)
    # - 无 browser → _execute_simulated (asyncio.sleep 模拟)
```

**Playwright 模式操作**: navigate, click, type, wait (selector/timeout), scroll (up/down), refresh
**模拟模式**: 通过 `context.memory` 记录操作历史，`asyncio.sleep` 模拟延迟

### L6: Validation（校验层）

**文件**: `byou/cua/validation.py` → `ValidationLayer`

**职责**: 验证执行结果是否符合预期。

**校验规则**:
1. `no_execution_errors` — 无执行错误
2. `all_steps_executed` — 所有步骤均已执行
3. `within_timeout` — 执行时间在超时范围内

**综合评分**:
```
overall_score = passed_checks / total_checks
```

**回滚**: 校验不通过时生成 rollback 动作列表 + retry_pipeline 建议。

## 与 Pipeline 的关系

CuaRuntime 在 Orchestrator 初始化时自动创建。可在有/无 Playwright 浏览器两种模式下运行——通过 `use_browser` 参数控制。

```
Orchestrator.__init__()
  └→ CuaRuntime(message_bus, browser_manager, use_browser)
       └→ Perception / Execution 注入 BrowserManager
```

当 Agent 需要网页自动化时，通过 Orchestrator 的 `cua_runtime` 调用：

```
Agent.execute()
  └→ orch.cua_runtime.execute_task(task)
       └→ L1 → L2 → L3 → L4 → L5 → L6
```
