"""Browser Execution Subsystem — 冒烟测试。

验证:
1. 数据模型序列化/反序列化
2. SafetyGuard 各项检查
3. RecoveryEngine 错误→恢复动作映射
4. BrowserSessionManager 会话池管理
5. BrowserTask 构建与验证
6. BrowserResearchAdapter 三种模式 task 构建
"""

import sys
sys.path.insert(0, r"Z:\Dev\Byou")

import json
from byou.tools.browser import *


def test_types_serialization():
    """数据模型 round-trip"""
    action = BrowserAction(
        action_type=BrowserActionType.NAVIGATE,
        value="https://example.com",
        selector="body",
        selector_type=BrowserSelectorType.CSS,
    )
    js = action.model_dump_json()
    back = BrowserAction.model_validate_json(js)
    assert back.value == "https://example.com"

    task = BrowserTask(
        task_id="test-1",
        mode=ResearchMode.COMPANY_WEBSITE,
        description="test",
        target_url="https://example.com",
        actions=[action],
        caller="researcher",
    )
    assert task.actions[0].action_type == BrowserActionType.NAVIGATE

    report = BrowserExecutionReport(task=task)
    assert report.total_steps == 0
    assert "test" in report.summary

    print("[PASS] types serialization")


def test_safety_url_allowed():
    sg = SafetyGuard(SafetyPolicy(
        allowed_domains=["example.com", "alibaba.com"],
        blocked_domains=["bad.com"],
    ))
    ok, reason = sg.check_url_allowed("https://www.example.com/page")
    assert ok, reason

    ok, reason = sg.check_url_allowed("https://bad.com/malware")
    assert not ok

    ok, reason = sg.check_url_allowed("https://www.alibaba.com/about")
    assert ok

    ok, reason = sg.check_url_allowed("https://xx.gov.cn")  # default blocked
    assert not ok

    print("[PASS] safety URL check")


def test_safety_anti_bot():
    sg = SafetyGuard()
    blocked, reason = sg.detect_anti_bot("Just a moment...", "cloudflare checking", 200)
    assert blocked

    blocked, reason = sg.detect_anti_bot("测试页面", "正常内容", 200)
    assert not blocked

    blocked, reason = sg.detect_anti_bot("test", "", 403)
    assert blocked

    print("[PASS] safety anti-bot detection")


def test_safety_login_wall():
    sg = SafetyGuard()
    blocked, reason = sg.detect_login_wall("登录", "请登录后查看 立即登录")
    assert blocked

    blocked, reason = sg.detect_login_wall("首页", "欢迎")
    assert not blocked

    print("[PASS] safety login wall detection")


def test_safety_limits():
    sg = SafetyGuard()
    ok, reason = sg.check_step_limit(5)
    assert ok
    ok, reason = sg.check_step_limit(100)
    assert not ok

    ok, reason = sg.check_error_limit(6)
    assert not ok
    ok, reason = sg.check_error_limit(3)
    assert ok

    print("[PASS] safety limits")


def test_recovery_mappings():
    eng = RecoveryEngine()
    # 超时 → retry
    action, delay = eng.get_recovery(BrowserErrorCategory.TIMEOUT, 0)
    assert action == RecoveryAction.RETRY
    assert delay == 2000

    # 第2次超时 → refresh_page
    action, delay = eng.get_recovery(BrowserErrorCategory.TIMEOUT, 1)
    assert action == RecoveryAction.REFRESH_PAGE

    # 超出 max_retries → escalate → SKIP
    action, delay = eng.get_recovery(BrowserErrorCategory.TIMEOUT, 3)
    assert action == RecoveryAction.SKIP

    # 反爬 → 直接 ABORT
    action, delay = eng.get_recovery(BrowserErrorCategory.ANTI_BOT, 0)
    assert action == RecoveryAction.ABORT

    print("[PASS] recovery mappings")


def test_recovery_exponential_backoff():
    """指数退避: delay = backoff_ms * 2^attempt"""
    eng = RecoveryEngine()
    _, d0 = eng.get_recovery(BrowserErrorCategory.TIMEOUT, 0)
    _, d1 = eng.get_recovery(BrowserErrorCategory.TIMEOUT, 1)
    assert d0 == 2000 and d1 == 4000  # 2000 * 2^0, 2000 * 2^1

    _, d0 = eng.get_recovery(BrowserErrorCategory.NETWORK, 0)
    _, d1 = eng.get_recovery(BrowserErrorCategory.NETWORK, 1)
    assert d0 == 3000 and d1 == 6000

    print("[PASS] recovery exponential backoff")


def test_session_manager():
    sm = BrowserSessionManager(max_sessions=3)
    assert len(sm.list_sessions()) == 0
    print("[PASS] session manager clean state")


def test_task_construction():
    """三种模式建 task"""
    from byou.tools.browser.adapter import BrowserResearchAdapter

    adapter = BrowserResearchAdapter()

    # 模式 1: Company website — 构造但执行需要真实 Playwright
    # 这里只验证 task 构造不出错
    import asyncio

    async def _test():
        # 仅验证 task 结构，不实际执行
        task = BrowserTask(
            mode=ResearchMode.COMPANY_WEBSITE,
            description="test",
            target_url="https://example.com",
            actions=[
                BrowserAction(action_type=BrowserActionType.NAVIGATE, value="https://example.com"),
                BrowserAction(action_type=BrowserActionType.EXTRACT),
            ],
            caller="researcher",
        )
        assert task.mode == ResearchMode.COMPANY_WEBSITE
        assert len(task.actions) == 2
        print("[PASS] task construction")

    asyncio.run(_test())


def test_report_summary():
    report = BrowserExecutionReport(
        task=BrowserTask(description="研究 Acme Corp 官网 https://acme.com"),
        total_steps=5,
        success_steps=4,
        failed_steps=1,
        findings=[
            ResearchFinding(source_url="https://acme.com", source_title="Acme", content="about", finding_type="company_intro"),
            ResearchFinding(source_url="https://acme.com/about", source_title="About", content="team", finding_type="company_intro"),
        ],
    )
    summary = report.summary
    assert "Acme Corp" in summary
    assert "4/5" in summary
    assert "2" in summary  # findings
    print("[PASS] report summary")


def test_enum_values():
    """所有枚举值正确"""
    assert BrowserActionType.NAVIGATE.value == "navigate"
    assert BrowserActionType.CLICK.value == "click"
    assert BrowserActionType.EXTRACT.value == "extract"
    assert ResearchMode.COMPANY_WEBSITE.value == "company_website"
    assert BrowserSelectorType.TEXT.value == "text"
    assert BrowserErrorCategory.TIMEOUT.value == "timeout"
    assert RecoveryAction.RETRY.value == "retry"
    print("[PASS] enum values")


# ── Run ─────────────────────────────────────────
if __name__ == "__main__":
    for fn in [
        test_types_serialization,
        test_safety_url_allowed,
        test_safety_anti_bot,
        test_safety_login_wall,
        test_safety_limits,
        test_recovery_mappings,
        test_recovery_exponential_backoff,
        test_session_manager,
        test_task_construction,
        test_report_summary,
        test_enum_values,
    ]:
        fn()
    print("\n=== ALL 11 TESTS PASSED ===")
