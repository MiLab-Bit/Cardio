"""Browser Execution Subsystem — Task Executor.

将 BrowserTask (动作序列) 转换为 Playwright 执行:
- 逐个执行 BrowserAction
- 每一步做安全前检查 + 安全后检查
- 失败时触发 RecoveryEngine
- 提取页面内容
- 输出 BrowserTrace + BrowserExecutionReport
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from urllib.parse import urlparse

from byou.tools.browser.types import (
    BrowserAction,
    BrowserActionResult,
    BrowserActionType,
    BrowserErrorCategory,
    BrowserExecutionReport,
    BrowserSelectorType,
    BrowserTask,
    ExtractedPageData,
    PageSnapshot,
    ResearchFinding,
    ResearchMode,
)
from byou.tools.browser.session import BrowserSession, BrowserSessionManager
from byou.tools.browser.safety import SafetyGuard
from byou.tools.browser.recovery import RecoveryEngine

logger = logging.getLogger(__name__)


class BrowserTaskExecutor:
    """浏览器任务执行器 — 核心引擎。

    不依赖任何 Agent 或 LLM。
    只接受 BrowserTask (含动作序列) + BrowserSession，
    返回 BrowserExecutionReport。
    """

    def __init__(
        self,
        session_manager: BrowserSessionManager | None = None,
        safety_guard: SafetyGuard | None = None,
        recovery_engine: RecoveryEngine | None = None,
    ):
        self._session_manager = session_manager or BrowserSessionManager()
        self._safety = safety_guard or SafetyGuard()
        self._recovery = recovery_engine or RecoveryEngine()

    # ── 主入口 ──────────────────────────────────

    async def execute(self, task: BrowserTask) -> BrowserExecutionReport:
        """执行一个浏览器研究任务。

        流程:
        1. 获取/创建会话
        2. 导航到入口页
        3. 循环执行动作序列
        4. 每步安全检查
        5. 失败恢复
        6. 输出完整报告
        """
        report = BrowserExecutionReport(task=task)
        t_start = time.monotonic()

        try:
            # 1. 会话
            session = await self._session_manager.get_session(
                task.session_id,
                headless=task.headless,
                reuse=task.reuse_session,
            )
            session.increment_task()
            report.task.session_id = session.session_id

            # 2. 导航入口
            if task.target_url:
                ok = await self._navigate(session, task.target_url, report)
                if not ok:
                    report.aborted = True
                    report.abort_reason = "Initial navigation failed"
                    return report

            # 3. 循环执行动作
            consecutive_errors = 0
            for i, action in enumerate(task.actions):
                if report.aborted:
                    break

                # 步数限制
                ok, reason = self._safety.check_step_limit(i)
                if not ok:
                    report.aborted = True
                    report.abort_reason = reason
                    break

                # 连续错误限制
                ok, reason = self._safety.check_error_limit(consecutive_errors)
                if not ok:
                    report.aborted = True
                    report.abort_reason = reason
                    break

                # 执行单步
                result = await self._execute_action(session, action, report)
                report.action_trace.append(result)

                if result.success:
                    consecutive_errors = 0
                    report.success_steps += 1

                    # 提取页面内容
                    if action.action_type in (BrowserActionType.NAVIGATE, BrowserActionType.CLICK):
                        await self._extract_current_page(session, report)
                else:
                    consecutive_errors += 1
                    report.failed_steps += 1
                    report.errors.append(f"Step {i}: {result.error}")

                    # 恢复
                    recovered = await self._recovery.apply_recovery(
                        error_category=BrowserErrorCategory(result.error_category or "unknown"),
                        attempt=consecutive_errors - 1,
                        retry_fn=lambda: self._execute_action(session, action, report),
                        refresh_fn=lambda: self._refresh(session),
                        navigate_back_fn=lambda: self._go_back(session),
                        restart_fn=lambda: session.start(),
                    )
                    if not recovered and not action.continue_on_failure:
                        report.aborted = True
                        report.abort_reason = f"Failed to recover from: {result.error}"
                        break

                report.total_steps = i + 1

        except Exception as e:
            logger.exception("Task execution error")
            report.aborted = True
            report.abort_reason = str(e)

        finally:
            report.completed_at = time.monotonic()  # type: ignore
            report.total_elapsed_ms = (report.completed_at - t_start) * 1000  # type: ignore

        return report

    # ── 单步执行 ─────────────────────────────────

    async def _execute_action(
        self, session: BrowserSession, action: BrowserAction, report: BrowserExecutionReport
    ) -> BrowserActionResult:
        """执行单个 BrowserAction"""
        t_start = time.monotonic()
        page = session.active_page
        if not page:
            return BrowserActionResult(
                action=action, success=False,
                error="No active page", error_category=BrowserErrorCategory.UNKNOWN.value,
            )

        try:
            # 安全检查: URL
            if action.action_type == BrowserActionType.NAVIGATE:
                allowed, reason = self._safety.check_url_allowed(action.value)
                if not allowed:
                    return BrowserActionResult(
                        action=action, success=False, error=reason,
                        error_category=BrowserErrorCategory.INVALID_URL.value,
                    )

            if action.action_type == BrowserActionType.NAVIGATE:
                await self._do_navigate(page, action)
            elif action.action_type == BrowserActionType.CLICK:
                await self._do_click(page, action)
            elif action.action_type == BrowserActionType.TYPE:
                await self._do_type(page, action)
            elif action.action_type == BrowserActionType.SCROLL:
                await self._do_scroll(page, action)
            elif action.action_type == BrowserActionType.EXTRACT:
                pass  # 提取在 _extract_current_page 中做
            elif action.action_type == BrowserActionType.WAIT:
                await asyncio.sleep(action.wait_after_ms / 1000)
            elif action.action_type == BrowserActionType.GO_BACK:
                await page.go_back(wait_until="domcontentloaded")
            elif action.action_type == BrowserActionType.REFRESH:
                await page.reload(wait_until="domcontentloaded")
            elif action.action_type == BrowserActionType.SCROLL_INTO_VIEW:
                await self._do_scroll_into_view(page, action)
            else:
                logger.warning("Unhandled action type: %s", action.action_type)

            elapsed = (time.monotonic() - t_start) * 1000

            return BrowserActionResult(
                action=action, success=True,
                page_url=page.url, page_title=await self._safe_title(page),
                elapsed_ms=round(elapsed, 1),
            )

        except asyncio.TimeoutError:
            elapsed = (time.monotonic() - t_start) * 1000
            return BrowserActionResult(
                action=action, success=False,
                error=f"Timeout after {action.timeout_ms}ms",
                error_category=BrowserErrorCategory.TIMEOUT.value,
                elapsed_ms=round(elapsed, 1),
            )
        except Exception as e:
            elapsed = (time.monotonic() - t_start) * 1000
            error_category = self._classify_error(e)
            return BrowserActionResult(
                action=action, success=False,
                error=str(e)[:200],
                error_category=error_category.value,
                elapsed_ms=round(elapsed, 1),
            )

    # ── Playwright 原子操作 ──────────────────────

    async def _do_navigate(self, page, action: BrowserAction) -> None:
        await page.goto(
            action.value,
            wait_until="domcontentloaded",
            timeout=action.timeout_ms,
        )
        if action.wait_after_ms:
            await asyncio.sleep(action.wait_after_ms / 1000)

    async def _do_click(self, page, action: BrowserAction) -> None:
        locator = self._build_locator(page, action)
        await locator.click(timeout=action.timeout_ms)
        if action.wait_for_navigation:
            await page.wait_for_load_state("domcontentloaded")
        if action.wait_after_ms:
            await asyncio.sleep(action.wait_after_ms / 1000)

    async def _do_type(self, page, action: BrowserAction) -> None:
        locator = self._build_locator(page, action)
        await locator.fill(action.value, timeout=action.timeout_ms)
        if action.wait_after_ms:
            await asyncio.sleep(action.wait_after_ms / 1000)

    async def _do_scroll(self, page, action: BrowserAction) -> None:
        amount = action.value or "0"
        await page.evaluate(f"window.scrollBy(0, {amount})")

    async def _do_scroll_into_view(self, page, action: BrowserAction) -> None:
        locator = self._build_locator(page, action)
        await locator.scroll_into_view_if_needed()

    # ── Locator 构建 ─────────────────────────────

    @staticmethod
    def _build_locator(page, action: BrowserAction):
        stype = action.selector_type
        sel = action.selector

        if stype == BrowserSelectorType.TEXT:
            return page.get_by_text(sel, exact=False)
        elif stype == BrowserSelectorType.ROLE:
            return page.get_by_role(sel.split("[")[0], name=action.value or None)
        elif stype == BrowserSelectorType.PLACEHOLDER:
            return page.get_by_placeholder(sel)
        elif stype == BrowserSelectorType.TEST_ID:
            return page.get_by_test_id(sel)
        elif stype == BrowserSelectorType.CSS:
            return page.locator(sel)
        elif stype == BrowserSelectorType.XPATH:
            return page.locator(f"xpath={sel}")
        elif stype == BrowserSelectorType.ARIA_LABEL:
            return page.get_by_label(sel)
        else:
            # AUTO: 按优先级试探
            if sel:
                return page.locator(sel)
            return page.get_by_text(action.description, exact=False)

    # ── 页面提取 ─────────────────────────────────

    async def _extract_current_page(self, session: BrowserSession, report: BrowserExecutionReport) -> None:
        """提取当前页面内容并记录到 report"""
        page = session.active_page
        if not page:
            return

        try:
            url = page.url
            title = await self._safe_title(page)

            # 安全检查: 反爬 / 登录墙 / 错误页
            text = await page.evaluate("() => document.body?.innerText || ''")
            text = text[:5000]

            is_blocked, block_reason = self._safety.detect_anti_bot(title, text, 200)
            is_login, login_reason = self._safety.detect_login_wall(title, text)
            is_error, error_reason = self._safety.detect_error_page(title, 200)

            if is_blocked:
                report.errors.append(f"Anti-bot on {url}: {block_reason}")
                logger.warning("Anti-bot detected: %s — %s", url, block_reason)
                return
            if is_login:
                logger.info("Login wall on %s — skipping", url)
                return

            # 提取链接
            links = []
            try:
                hrefs = await page.evaluate("""() => {
                    const links = document.querySelectorAll('a[href]');
                    return Array.from(links).slice(0, 30).map(a => ({
                        text: (a.textContent || '').trim().slice(0, 80),
                        href: a.href
                    }));
                }""")
                links = hrefs or []
            except Exception:
                pass

            # 提取 headings
            headings = []
            try:
                h_texts = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('h1,h2,h3'))
                        .slice(0, 20)
                        .map(h => h.textContent.trim());
                }""")
                headings = h_texts or []
            except Exception:
                pass

            # 构建快照
            parsed = urlparse(url)
            snapshot = PageSnapshot(
                url=url,
                title=title,
                domain=parsed.netloc,
                text_summary=text[:2000],
                headings=headings,
                links=links,
                content_length=len(text),
                is_blocked=is_blocked,
                has_captcha=is_blocked and "captcha" in block_reason.lower(),
                is_login_wall=is_login,
                is_error_page=is_error,
            )
            report.pages_visited.append(snapshot)
            session.increment_page()

            # 提取结构化数据
            extracted = ExtractedPageData(
                url=url,
                title=title,
                key_paragraphs=self._split_paragraphs(text[:5000]),
                key_links=links,
                sections={},
                full_text=text,
                raw_html_hash=hashlib.md5(text.encode()).hexdigest()[:12],
            )
            report.extracted_data.append(extracted)

            # 生成 finding
            if task_desc := report.task.description:
                finding = ResearchFinding(
                    source_url=url,
                    source_title=title,
                    finding_type="page_content",
                    content=text[:2000],
                    confidence=0.85,
                )
                report.findings.append(finding)

        except Exception as e:
            logger.warning("Extract page failed: %s", e)

    # ── 辅助方法 ─────────────────────────────────

    @staticmethod
    async def _safe_title(page) -> str:
        try:
            return await page.title()
        except Exception:
            return ""

    async def _navigate(self, session: BrowserSession, url: str, report: BrowserExecutionReport) -> bool:
        """导航到入口 URL"""
        page = session.active_page
        if not page:
            await session.new_tab(url)
            page = session.active_page

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            await self._extract_current_page(session, report)
            return True
        except Exception as e:
            report.errors.append(f"Navigate to {url}: {e}")
            return False

    async def _refresh(self, session: BrowserSession) -> None:
        page = session.active_page
        if page:
            await page.reload(wait_until="domcontentloaded")

    async def _go_back(self, session: BrowserSession) -> None:
        page = session.active_page
        if page:
            await page.go_back(wait_until="domcontentloaded")

    @staticmethod
    def _classify_error(error: Exception) -> BrowserErrorCategory:
        """异常 → BrowserErrorCategory"""
        msg = str(error).lower()
        if "timeout" in msg:
            return BrowserErrorCategory.TIMEOUT
        if any(kw in msg for kw in ("not found", "no element", "locator", "resolve")):
            return BrowserErrorCategory.ELEMENT_NOT_FOUND
        if any(kw in msg for kw in ("net::err", "connection refused", "dns", "name not resolved")):
            return BrowserErrorCategory.NETWORK
        if any(kw in msg for kw in ("navigation", "redirect")):
            return BrowserErrorCategory.NAVIGATION_FAILED
        if "stale" in msg:
            return BrowserErrorCategory.STALE_ELEMENT
        return BrowserErrorCategory.UNKNOWN

    @staticmethod
    def _split_paragraphs(text: str, min_len: int = 20) -> list[str]:
        """将文本拆为有意义的段落"""
        paragraphs = []
        for para in text.split("\n\n"):
            para = para.strip()
            if len(para) >= min_len:
                paragraphs.append(para)
        if not paragraphs:
            paragraphs = [t.strip() for t in text.split("\n") if len(t.strip()) >= min_len]
        return paragraphs[:15]
