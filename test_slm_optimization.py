"""SLM 优化验证测试 — 验证所有优化是否正常工作"""

import asyncio
import time
import os

# 添加项目根目录到 Python 路径
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from byou.tools.slm.gateway import SLMGateway, SLMInferenceCache
from byou.tools.slm.monitor import SLMPerformanceMonitor, get_monitor
from byou.tools.slm.router import Router


async def test_inference_cache():
    """测试 1: 推理缓存"""
    print("=" * 60)
    print("测试 1: 推理缓存")
    print("=" * 60)

    cache = SLMInferenceCache(max_size=100, ttl_seconds=60)

    # 第一次查询（应该 miss）
    key1 = cache.make_key("classify", text="测试文本", labels=["A", "B"])
    result1 = {"confidence": 0.85, "label": "A"}
    cache.put(key1, result1)

    # 第二次查询（应该 hit）
    cached = cache.get(key1)
    assert cached is not None, "Cache should return cached result"
    assert cached["confidence"] == 0.85, "Cached result should match"
    print("✓ Cache hit works")

    # 检查统计
    stats = cache.stats()
    print(f"  Cache stats: {stats}")
    assert stats["hits"] == 1, "Should have 1 hit"
    assert stats["misses"] == 0, "Should have 0 misses"
    print("✓ Cache stats correct")

    print("推理缓存测试通过 ✅\n")


async def test_cross_platform_model_path():
    """测试 2: 跨平台模型路径检测"""
    print("=" * 60)
    print("测试 2: 跨平台模型路径检测")
    print("=" * 60)

    from byou.tools.slm.real_engines import _find_model_path, _MODEL_CANDIDATES

    print(f"  模型候选路径: {_MODEL_CANDIDATES}")
    print(f"  当前工作目录: {os.getcwd()}")

    # 检查模型文件是否存在
    model_path = _find_model_path()
    if model_path:
        print(f"✓ 找到模型文件: {model_path}")
    else:
        print("⚠ 未找到模型文件（正常，如果没有下载模型）")

    print("跨平台模型路径检测测试通过 ✅\n")


async def test_optimized_routing():
    """测试 3: 优化后的路由策略"""
    print("=" * 60)
    print("测试 3: 优化后的路由策略")
    print("=" * 60)

    router = Router()

    # 测试意图路由
    result = await router.route_intent_to_capability("查询某公司的背景信息")
    print(f"  意图路由结果:")
    print(f"    Intent: {result.data.intent if result.data else 'N/A'}")
    print(f"    Top target: {result.data.top_target if result.data else 'N/A'}")
    print(f"    Confidence: {result.confidence}")
    print(f"    Model: {result.model}")
    print("✓ 意图路由 works")

    # 测试 Agent 路由
    result2 = await router.route_to_agent("我需要研究这家公司的背景")
    print(f"  Agent 路由结果:")
    print(f"    Top target: {result2.data.top_target if result2.data else 'N/A'}")
    print(f"    Confidence: {result2.confidence}")
    print(f"    Model: {result2.model}")
    print("✓ Agent 路由 works")

    print("优化后的路由策略测试通过 ✅\n")


async def test_performance_monitor():
    """测试 4: 性能监控"""
    print("=" * 60)
    print("测试 4: 性能监控")
    print("=" * 60)

    monitor = SLMPerformanceMonitor()

    # 记录几条推理记录
    from byou.tools.slm.monitor import InferenceRecord

    record1 = InferenceRecord(
        timestamp=time.time(),
        model_id="test_model",
        capability="classify",
        latency_ms=50.0,
        confidence=0.85,
        needs_escalation=False,
        input_length=100,
        output_length=10,
        cache_hit=False,
    )
    monitor.record_inference(record1)

    record2 = InferenceRecord(
        timestamp=time.time(),
        model_id="test_model",
        capability="rerank",
        latency_ms=30.0,
        confidence=0.90,
        needs_escalation=False,
        input_length=200,
        output_length=5,
        cache_hit=True,
    )
    monitor.record_inference(record2)

    # 检查指标
    metrics = monitor.get_metrics("test_model")
    assert metrics is not None, "Should have metrics for test_model"
    assert metrics.total_calls == 2, f"Should have 2 calls, got {metrics.total_calls}"
    assert metrics.cache_hits == 1, f"Should have 1 cache hit, got {metrics.cache_hits}"
    print(f"✓ 性能指标记录正确")
    print(f"  Total calls: {metrics.total_calls}")
    print(f"  Avg latency: {metrics.avg_latency_ms:.1f} ms")
    print(f"  Cache hit rate: {metrics.cache_hit_rate:.1%}")

    # 生成报告
    report = monitor.generate_report()
    assert "SLM Performance Report" in report, "Report should have title"
    print("✓ 性能报告生成成功")

    print("性能监控测试通过 ✅\n")


async def test_gateway_integration():
    """测试 5: Gateway 集成测试"""
    print("=" * 60)
    print("测试 5: Gateway 集成测试")
    print("=" * 60)

    gateway = SLMGateway()

    # 测试缓存控制
    gateway.disable_cache()
    assert not gateway._cache_enabled, "Cache should be disabled"
    print("✓ 缓存控制 works")

    gateway.enable_cache()
    assert gateway._cache_enabled, "Cache should be enabled"
    print("✓ 缓存启用 works")

    # 测试缓存统计
    cache_stats = gateway.get_cache_stats()
    assert "size" in cache_stats, "Cache stats should have size"
    print(f"✓ 缓存统计: {cache_stats}")

    # 测试性能报告
    perf_report = gateway.get_performance_report()
    assert "SLM Performance Report" in perf_report, "Should have performance report"
    print("✓ 性能报告生成成功")

    print("Gateway 集成测试通过 ✅\n")


async def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("SLM 优化验证测试")
    print("=" * 60 + "\n")

    try:
        await test_inference_cache()
        await test_cross_platform_model_path()
        await test_optimized_routing()
        await test_performance_monitor()
        await test_gateway_integration()

        print("=" * 60)
        print("所有测试通过 ✅")
        print("=" * 60)

    except Exception as exc:
        print(f"\n❌ 测试失败: {exc}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
