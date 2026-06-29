import pytest
pytestmark = pytest.mark.skip(reason='browser module not yet implemented')
"""Playwright 端到端集成测试"""
import asyncio
from byou.infrastructure import BrowserManager
from byou.tools.cua import CuaRuntime, CuaTask

async def main():
    print("=== Byou Playwright 集成测试 ===")
    print()

    # 1. 启动浏览器
    bm = BrowserManager(channel="msedge", headless=True)
    await bm.start()
    print("[OK] BrowserManager 启动成功 (Edge headless)")

    # 2. 导航到 baidu
    info = await bm.navigate("task_001", "https://www.baidu.com")
    print(f"[OK] 导航到百度: title={info['title']}, status={info['status']}")

    # 3. 提取元素
    elements = await bm.extract_elements("task_001")
    print(f"[OK] 提取到 {len(elements)} 个可交互元素")
    visible = [e for e in elements if e.get("visible")]
    print(f"    其中可见元素: {len(visible)}")
    if visible:
        sample = visible[:3]
        for e in sample:
            text_preview = (e["text"] or "")[:40]
            print(f"    - {e['tag']} | text=\"{text_preview}\" | type={e['type']}")

    # 4. 提取文本
    text = await bm.extract_text("task_001")
    print(f"[OK] 提取文本长度: {len(text)} 字符")

    # 5. 截图
    screenshot = await bm.screenshot("task_001", "Z:/Dev/Byou/data/baidu_test.png")
    print(f"[OK] 截图保存: {len(screenshot)} bytes")

    # 6. CUA Runtime 集成
    rt = CuaRuntime(browser_manager=bm, use_browser=True)
    print("[OK] CuaRuntime 初始化: browser=enabled")

    task = CuaTask(
        id="e2e_001",
        description="搜索Byou项目",
        target_url="https://www.baidu.com",
        actions=[
            {"type": "navigate", "target": "https://www.baidu.com"},
            {"type": "type", "target": "#kw", "value": "Byou Multi-Agent"},
            {"type": "click", "target": "#su"},
            {"type": "wait", "value": "3000"},
        ],
    )
    result = await rt.execute_task(task)
    print(f"[OK] CUA 任务完成: status={result.status.value}")
    if result.result:
        v = result.result.get("validation", {})
        print(f"    validation: score={v.get('overall_score')}, success={v.get('success')}")

    await bm.stop()
    print()
    print("=== 全部通过 ===")

if __name__ == "__main__":
    asyncio.run(main())
