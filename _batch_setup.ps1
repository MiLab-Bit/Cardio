$scriptDir = "C:\Program Files\QClaw\v0.2.23.532\resources\openclaw\config\skills\qclaw-text-file\scripts\write_file.py"
$python = "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
$base = "Z:\Dev\Byou"

# Helper: write a file via qclaw-text-file
function Write-File($targetPath, $content) {
    $tmp = "$base\_tmp_$(Get-Random).txt"
    $content | Out-File -FilePath $tmp -Encoding UTF8 -NoNewline
    & $python $scriptDir --path $targetPath --content-file $tmp --platform windows
    Remove-Item $tmp -ErrorAction SilentlyContinue
}

# ============================================================
# 1. byou/infrastructure/browser.py — BrowserManager
# ============================================================
Write-File "$base\byou\infrastructure\browser.py" @'
"""
Browser Manager — Playwright 浏览器自动化管理

管理浏览器生命周期，提供页面池、截图、元素提取等能力。
默认使用系统 Edge 浏览器 (channel="msedge")，无需额外安装 Chromium。
"""

import asyncio
import logging
from typing import Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class BrowserManager:
    """Playwright 浏览器管理器。

    特性：
    - 使用系统 Edge 浏览器 (无需额外下载 Chromium)
    - 页面池管理（每任务一页）
    - 自动清理
    - 截图与 DOM 元素提取
    """

    def __init__(
        self,
        channel: str = "msedge",
        headless: bool = True,
        viewport: Optional[dict] = None,
    ):
        self.channel = channel
        self.headless = headless
        self.viewport = viewport or {"width": 1920, "height": 1080}
        self._playwright: Any = None
        self._browser: Any = None
        self._pages: dict[str, Any] = {}
        self._started = False

    async def start(self) -> None:
        """启动浏览器。幂等操作。"""
        if self._started:
            return

        from playwright.async_api import async_playwright

        logger.info("启动 Playwright (channel=%s, headless=%s)", self.channel, self.headless)
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            channel=self.channel,
            headless=self.headless,
        )
        self._started = True
        logger.info("浏览器已启动")

    async def get_page(self, task_id: str) -> Any:
        """获取或创建任务的页面。"""
        if not self._started:
            await self.start()

        if task_id not in self._pages:
            page = await self._browser.new_page()
            await page.set_viewport_size(self.viewport)
            self._pages[task_id] = page
            logger.debug("创建新页面: task=%s", task_id)

        return self._pages[task_id]

    async def close_page(self, task_id: str) -> None:
        """关闭任务页面。"""
        page = self._pages.pop(task_id, None)
        if page:
            await page.close()
            logger.debug("关闭页面: task=%s", task_id)

    async def navigate(
        self, task_id: str, url: str, timeout: int = 30000
    ) -> dict:
        """导航到 URL，返回页面元信息。"""
        page = await self.get_page(task_id)
        response = await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        return {
            "url": page.url,
            "title": await page.title(),
            "status": response.status if response else 0,
        }

    async def screenshot(self, task_id: str, path: Optional[str] = None) -> bytes:
        """截取页面截图。如提供 path 则保存到文件。"""
        page = await self.get_page(task_id)
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=path, full_page=False)
        return await page.screenshot()

    async def extract_elements(self, task_id: str) -> list[dict]:
        """通过 JS 提取页面中所有可交互元素。"""
        page = await self.get_page(task_id)

        elements = await page.evaluate("""() => {
            const selectors = 'button, a, input, select, textarea, [role="button"], [onclick]';
            const results = [];
            const nodes = document.querySelectorAll(selectors);
            for (let i = 0; i < Math.min(nodes.length, 200); i++) {
                const el = nodes[i];
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                const visible = style.display !== 'none' &&
                    style.visibility !== 'hidden' &&
                    rect.width > 0 && rect.height > 0;
                results.push({
                    index: i,
                    tag: el.tagName.toLowerCase(),
                    type: el.getAttribute('type') || el.tagName.toLowerCase(),
                    id: el.id || '',
                    className: (el.className && typeof el.className === 'string')
                        ? el.className : '',
                    text: (el.textContent || '').trim().substring(0, 200),
                    placeholder: el.placeholder || '',
                    href: el.href || '',
                    name: el.name || '',
                    role: el.getAttribute('role') || '',
                    ariaLabel: el.getAttribute('aria-label') || '',
                    visible: visible,
                    enabled: !el.disabled,
                    rect: { x: Math.round(rect.x), y: Math.round(rect.y),
                            w: Math.round(rect.width), h: Math.round(rect.height) },
                    selector: el.id ? '#' + el.id :
                        (el.className && typeof el.className === 'string'
                            ? '.' + el.className.split(' ')[0] : el.tagName)
                });
            }
            return results;
        }""")
        return elements

    async def extract_text(self, task_id: str) -> str:
        """提取页面可见文本。"""
        page = await self.get_page(task_id)
        text = await page.evaluate(
            "() => (document.body?.innerText || '').substring(0, 10000)"
        )
        return text

    async def get_page_info(self, task_id: str) -> dict:
        """获取页面基本信息（url, title, viewport）。"""
        page = await self.get_page(task_id)
        return {
            "url": page.url,
            "title": await page.title(),
            "viewport": self.viewport,
        }

    # ── 交互操作 ────────────────────────────────────────

    async def click(
        self, task_id: str, selector: str, timeout: int = 5000
    ) -> bool:
        """点击元素。返回是否成功。"""
        page = await self.get_page(task_id)
        try:
            await page.click(selector, timeout=timeout)
            return True
        except Exception as e:
            logger.warning("点击失败: selector=%s, error=%s", selector, e)
            return False

    async def type_text(
        self, task_id: str, selector: str, text: str, timeout: int = 5000
    ) -> bool:
        """在输入框中填入文本。"""
        page = await self.get_page(task_id)
        try:
            await page.fill(selector, text, timeout=timeout)
            return True
        except Exception as e:
            logger.warning("输入失败: selector=%s, error=%s", selector, e)
            return False

    async def wait_for(
        self,
        task_id: str,
        selector: Optional[str] = None,
        timeout: int = 5000,
    ) -> bool:
        """等待元素出现，或纯延时。返回是否等到。"""
        page = await self.get_page(task_id)
        if selector:
            try:
                await page.wait_for_selector(selector, timeout=timeout)
                return True
            except Exception:
                return False
        else:
            await page.wait_for_timeout(timeout)
            return True

    async def scroll(
        self, task_id: str, direction: str = "down", amount: int = 500
    ) -> None:
        """滚动页面。"""
        page = await self.get_page(task_id)
        dy = amount if direction == "down" else -amount
        await page.evaluate(f"window.scrollBy(0, {dy})")

    async def refresh(self, task_id: str) -> None:
        """刷新当前页面。"""
        page = await self.get_page(task_id)
        await page.reload(wait_until="domcontentloaded")

    async def evaluate(self, task_id: str, expression: str) -> Any:
        """在页面上下文中执行 JS 表达式。"""
        page = await self.get_page(task_id)
        return await page.evaluate(expression)

    # ── 生命周期 ────────────────────────────────────────

    async def stop(self) -> None:
        """关闭所有页面和浏览器。"""
        for task_id in list(self._pages.keys()):
            await self.close_page(task_id)

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        self._started = False
        logger.info("浏览器已关闭")

    @property
    def active_page_count(self) -> int:
        return len(self._pages)
'@

# ============================================================
# 2. byou/cua/perception.py — 重写：接入 Playwright
# ============================================================
Write-File "$base\byou\cua\perception.py" @'
"""
CUA Layer 1: Perception — 感知层

通过 Playwright 真实检测页面 DOM：
- UI 元素检测与定位
- 文本内容提取
- 页面截图
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PerceptionLayer:
    """感知层 — CUA 的第一层。

    通过 Playwright BrowserManager 获取真实页面状态，
    将原始 DOM 转化为结构化的元素描述。
    """

    def __init__(self, browser_manager: Optional[Any] = None):
        self.browser = browser_manager
        self.supported_elements = [
            "button", "input", "link", "image", "text",
            "dropdown", "checkbox", "table", "form", "dialog",
        ]

    def set_browser(self, browser_manager: Any) -> None:
        """注入浏览器管理器。"""
        self.browser = browser_manager

    async def process(self, task: Any, context: Any) -> dict:
        """感知当前界面状态。

        如果有 Playwright 浏览器，则从真实 DOM 提取；
        否则回退到上下文中的历史数据。
        """
        logger.debug("CUA Perception: 感知界面状态")

        if self.browser and task.target_url:
            return await self._perceive_from_browser(task, context)
        else:
            return await self._perceive_from_context(task, context)

    async def _perceive_from_browser(self, task: Any, context: Any) -> dict:
        """通过 Playwright 真实感知页面。"""
        try:
            info = await self.browser.get_page_info(task.id)
            elements = await self.browser.extract_elements(task.id)
            text = await self.browser.extract_text(task.id)
            screenshot_bytes = await self.browser.screenshot(task.id)

            # 存储截图引用到上下文
            screenshot_ref = f"memory://{task.id}/screenshot"
            context.memory["last_screenshot"] = screenshot_ref
            context.screenshots.append(screenshot_ref)

            return {
                "url": info["url"],
                "title": info["title"],
                "elements": elements,
                "text_content": text[:5000],
                "screenshot_ref": screenshot_ref,
                "viewport": info["viewport"],
                "element_count": len(elements),
                "visible_element_count": sum(
                    1 for e in elements if e.get("visible")
                ),
                "source": "playwright",
            }
        except Exception as e:
            logger.warning("Playwright 感知失败，回退到上下文: %s", e)
            return await self._perceive_from_context(task, context)

    async def _perceive_from_context(self, task: Any, context: Any) -> dict:
        """回退模式：从历史上下文推断。"""
        prev_state = context.current_state.get("perception", {})
        return {
            "url": task.target_url or prev_state.get("url", ""),
            "title": prev_state.get("title", ""),
            "elements": prev_state.get("elements", []),
            "text_content": prev_state.get("text_content", ""),
            "screenshot_ref": (
                context.screenshots[-1] if context.screenshots else ""
            ),
            "viewport": {"width": 1920, "height": 1080},
            "source": "context_fallback",
        }

    def is_ready(self) -> bool:
        return True
'@

# ============================================================
# 3. byou/cua/execution.py — 重写：接入 Playwright
# ============================================================
Write-File "$base\byou\cua\execution.py" @'
"""
CUA Layer 5: Execution — 执行层

通过 Playwright 真实执行浏览器操作：
- navigate / click / type / wait / scroll / refresh
- 操作超时与重试
- 执行日志
"""

import asyncio
import logging
from typing import Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ExecutionLayer:
    """执行层 — CUA 的第五层。

    将 Planning 层的操作计划转化为真实的浏览器操作。
    支持 Playwright 驱动，无浏览器时回退到模拟模式。
    """

    def __init__(self, browser_manager: Optional[Any] = None):
        self.browser = browser_manager
        self._execution_log: list[dict] = []

    def set_browser(self, browser_manager: Any) -> None:
        """注入浏览器管理器。"""
        self.browser = browser_manager

    async def process(self, action_plan: dict, context: Any) -> dict:
        """执行操作计划。"""
        logger.debug("CUA Execution: 执行操作计划")

        steps = action_plan.get("steps", [])
        results = []
        errors = []
        start_time = datetime.now()

        for step in steps:
            try:
                result = await self._execute_step(step, context)
                results.append(result)

                if not result.get("success", True):
                    err_msg = (
                        f"步骤 {step.get('step')} 失败: "
                        f"{result.get('error', 'unknown')}"
                    )
                    errors.append(err_msg)

                    if step.get("retry_on_failure"):
                        logger.info("重试步骤 %d", step.get("step"))
                        await asyncio.sleep(0.5)
                        retry = await self._execute_step(step, context)
                        results.append({"retry": True, **retry})
                        if retry.get("success"):
                            errors.pop()

            except Exception as e:
                errors.append(
                    f"步骤 {step.get('step')} 异常: {e}"
                )
                logger.warning(
                    "步骤执行异常: step=%d, error=%s",
                    step.get("step"), e,
                )

        duration_ms = int(
            (datetime.now() - start_time).total_seconds() * 1000
        )

        execution_result = {
            "executed_steps": len(results),
            "total_steps": len(steps),
            "results": results,
            "success": len(errors) == 0,
            "duration_ms": duration_ms,
            "errors": errors,
        }

        self._execution_log.append(execution_result)
        return execution_result

    async def _execute_step(self, step: dict, context: Any) -> dict:
        """执行单个操作步骤。

        优先使用 Playwright，无浏览器时使用模拟执行。
        """
        action = step.get("action", "")
        target = step.get("target", "")
        value = step.get("value", "")
        timeout = step.get("timeout_ms", 5000)
        task_id = step.get("task_id", "default")

        if self.browser:
            return await self._execute_with_browser(
                action, target, value, timeout, task_id, step
            )
        else:
            return await self._execute_simulated(
                action, target, value, timeout, context, step
            )

    async def _execute_with_browser(
        self,
        action: str,
        target: str,
        value: str,
        timeout: int,
        task_id: str,
        step: dict,
    ) -> dict:
        """通过 Playwright 真实执行操作。"""
        result = {
            "step": step.get("step"),
            "action": action,
            "target": target,
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "engine": "playwright",
        }

        try:
            if action == "navigate":
                info = await self.browser.navigate(task_id, target, timeout)
                result["description"] = (
                    f"导航到 {target} → {info.get('title', '')}"
                )
                result["detail"] = info

            elif action == "click":
                ok = await self.browser.click(task_id, target, timeout)
                result["success"] = ok
                result["description"] = (
                    f"点击 {target}" if ok else f"点击 {target} 失败"
                )
                if not ok:
                    result["error"] = "元素不可点击"

            elif action == "type":
                ok = await self.browser.type_text(
                    task_id, target, value, timeout
                )
                result["success"] = ok
                result["description"] = (
                    f"输入 {target}: {value}"
                    if ok
                    else f"输入 {target} 失败"
                )
                if not ok:
                    result["error"] = "输入框不可用"

            elif action == "wait":
                selector = target if target else None
                ok = await self.browser.wait_for(
                    task_id, selector, timeout
                )
                result["description"] = (
                    f"等待 {selector or timeout}ms"
                )
                result["detail"] = {"timeout_ms": timeout, "found": ok}

            elif action == "scroll":
                direction = value if value in ("up", "down") else "down"
                await self.browser.scroll(task_id, direction)
                result["description"] = f"滚动页面 {direction}"

            elif action == "refresh":
                await self.browser.refresh(task_id)
                result["description"] = "刷新页面"

            else:
                # 通用：尝试在页面执行 JS
                result["description"] = f"执行 {action}"
                result["success"] = True

        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            result["description"] = f"{action} 异常: {e}"

        return result

    async def _execute_simulated(
        self,
        action: str,
        target: str,
        value: str,
        timeout: int,
        context: Any,
        step: dict,
    ) -> dict:
        """模拟执行（无浏览器时回退）。"""
        await asyncio.sleep(0.05)

        result = {
            "step": step.get("step"),
            "action": action,
            "target": target,
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "engine": "simulated",
        }

        if action == "navigate":
            context.memory.setdefault(
                "navigation_path", []
            ).append(target)
            result["description"] = f"导航到 {target}"

        elif action == "click":
            context.memory.setdefault(
                "clicks", []
            ).append(target)
            result["description"] = f"点击 {target}"

        elif action == "type":
            context.memory.setdefault("inputs", []).append(
                {"target": target, "value": value}
            )
            result["description"] = f"输入 {target}: {value}"

        elif action == "wait":
            wait_ms = int(value) if value else min(timeout, 5000)
            await asyncio.sleep(min(wait_ms / 1000, 5.0))
            result["description"] = f"等待 {wait_ms}ms"

        elif action == "refresh":
            result["description"] = "刷新页面"

        else:
            result["description"] = f"执行 {action}"

        return result

    def get_execution_log(self, limit: int = 20) -> list[dict]:
        """获取最近执行日志。"""
        return self._execution_log[-limit:]

    def is_ready(self) -> bool:
        return True
'@

# ============================================================
# 4. byou/core/runtime.py — 注入 BrowserManager
# ============================================================
Write-File "$base\byou\core\runtime.py" @'
"""
CUA (Computer-Use Agent) Runtime — 让 AI 像人一样操作电脑

6 层架构实现自动化信息收集和操作：
├── Perception Layer      感知层：UI 元素识别、文本提取
├── Semantic Align Layer  语义对齐层：元素语义理解
├── State Modeling Layer  状态建模层：操作状态追踪
├── Planning Layer        规划层：任务分解与路径规划
├── Execution Layer       执行层：操作执行（点击/输入/滚动）
└── Validation Layer      校验层：结果验证与回滚

集成 Playwright 浏览器自动化（系统 Edge 通道）。
"""

import asyncio
import logging
from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from byou.core.message_bus import MessageBus
from byou.infrastructure.browser import BrowserManager
from byou.cua.perception import PerceptionLayer
from byou.cua.semantic_align import SemanticAlignLayer
from byou.cua.state_modeling import StateModelingLayer
from byou.cua.planning import PlanningLayer
from byou.cua.execution import ExecutionLayer
from byou.cua.validation import ValidationLayer

logger = logging.getLogger(__name__)


class ExecutionStatus(Enum):
    """执行状态"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class CuaTask:
    """CUA 任务定义"""

    id: str
    description: str
    target_url: Optional[str] = None
    actions: list[dict] = field(default_factory=list)
    max_retries: int = 3
    timeout_seconds: int = 60
    status: ExecutionStatus = ExecutionStatus.PENDING
    result: Optional[dict] = None
    errors: list[str] = field(default_factory=list)


@dataclass
class CuaContext:
    """CUA 执行上下文"""

    current_state: dict[str, Any] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)
    screenshots: list[str] = field(default_factory=list)


class CuaRuntime:
    """Computer-Use Agent 运行时引擎。

    集成 Playwright 浏览器自动化，通过 6 层架构
    实现从感知到执行的完整闭环。
    """

    def __init__(
        self,
        message_bus: Optional[MessageBus] = None,
        browser_manager: Optional[BrowserManager] = None,
        use_browser: bool = True,
    ):
        self.message_bus = message_bus
        self.browser_manager = browser_manager
        self.use_browser = use_browser

        # 初始化 6 层架构
        self.perception = PerceptionLayer(self.browser_manager)
        self.semantic_align = SemanticAlignLayer()
        self.state_modeling = StateModelingLayer()
        self.planning = PlanningLayer()
        self.execution = ExecutionLayer(self.browser_manager)
        self.validation = ValidationLayer()

        self._active_tasks: dict[str, CuaTask] = {}
        self._context = CuaContext()

        logger.info(
            "CUA Runtime 初始化完成 (6 层架构, browser=%s)",
            "enabled" if (use_browser and browser_manager) else "disabled",
        )

    async def start_browser(self) -> None:
        """启动浏览器（如未注入则自动创建）。"""
        if self.browser_manager is None and self.use_browser:
            self.browser_manager = BrowserManager()
            self.perception.set_browser(self.browser_manager)
            self.execution.set_browser(self.browser_manager)

        if self.browser_manager and not self.browser_manager._started:
            await self.browser_manager.start()
            logger.info("CUA Runtime 浏览器已启动")

    async def execute_task(self, task: CuaTask) -> CuaTask:
        """执行一个 CUA 任务。

        6 层流水线：
        1. Perception → 感知当前界面状态
        2. Semantic Align → 理解界面元素语义
        3. State Modeling → 构建操作状态模型
        4. Planning → 规划操作路径
        5. Execution → 执行具体操作
        6. Validation → 验证结果
        """
        self._active_tasks[task.id] = task
        task.status = ExecutionStatus.RUNNING

        try:
            # Layer 1: Perception
            perception_result = await self.perception.process(
                task, self._context
            )
            self._context.current_state["perception"] = perception_result

            # Layer 2: Semantic Alignment
            semantic_result = await self.semantic_align.process(
                perception_result, self._context
            )
            self._context.current_state["semantic"] = semantic_result

            # Layer 3: State Modeling
            state_model = await self.state_modeling.process(
                semantic_result, self._context
            )
            self._context.current_state["model"] = state_model

            # Layer 4: Planning
            action_plan = await self.planning.process(
                state_model, task, self._context
            )
            self._context.current_state["plan"] = action_plan

            # 注入 task_id 到每一步
            for step in action_plan.get("steps", []):
                step.setdefault("task_id", task.id)

            # Layer 5: Execution
            execution_result = await self.execution.process(
                action_plan, self._context
            )
            self._context.current_state["execution"] = execution_result
            self._context.history.append(execution_result)

            # Layer 6: Validation
            validation_result = await self.validation.process(
                execution_result, task, self._context
            )

            if validation_result.get("success"):
                task.status = ExecutionStatus.SUCCESS
            else:
                task.status = ExecutionStatus.FAILED
                task.errors.append(
                    validation_result.get("error", "Unknown error")
                )

            task.result = {
                "perception": perception_result,
                "semantic": semantic_result,
                "state_model": state_model,
                "plan": action_plan,
                "execution": execution_result,
                "validation": validation_result,
            }

        except Exception as e:
            logger.exception("CUA 任务执行异常: %s", task.id)
            task.status = ExecutionStatus.FAILED
            task.errors.append(str(e))

        return task

    async def retry_task(self, task_id: str) -> Optional[CuaTask]:
        """重试失败的 CUA 任务。"""
        task = self._active_tasks.get(task_id)
        if not task:
            logger.warning("任务不存在: %s", task_id)
            return None

        if task.max_retries <= 0:
            logger.warning("任务 %s 已达最大重试次数", task_id)
            return None

        task.max_retries -= 1
        task.status = ExecutionStatus.RETRYING
        task.errors = []

        logger.info(
            "重试 CUA 任务 %s (剩余重试: %d)",
            task_id, task.max_retries,
        )
        return await self.execute_task(task)

    def get_task_status(self, task_id: str) -> Optional[ExecutionStatus]:
        """查询任务状态。"""
        task = self._active_tasks.get(task_id)
        return task.status if task else None

    async def shutdown(self) -> None:
        """关闭 CUA Runtime（含浏览器）。"""
        self._active_tasks.clear()

        if self.browser_manager:
            await self.browser_manager.stop()

        logger.info("CUA Runtime 已关闭")
'@

Write-Host "All files written successfully."
