"""MCP Tool Bus: integration smoke test"""
import sys
sys.path.insert(0, r"Z:\Dev\Byou")

from byou.tools.mcp import *
from byou.tools.mcp.health import HealthChecker, HealthReport
from byou.tools.mcp.sandbox import ToolSandbox
from byou.tools.mcp.policies import CircuitBreaker, CircuitState
from byou.tools.mcp.errors import map_error as _me

# ── Registry ──────────────────────────────────────
reg = ToolRegistry()
reg.register(MCPToolDescriptor(
    name="tianyancha.baseinfo",
    display_name="天眼查-工商信息",
    category=ToolCategory.BUSINESS_DATA,
    capabilities=[ToolCapability.COMPANY_LOOKUP],
    server_name="tianyancha",
    provider="tianyancha",
    priority=10,
))
reg.register(MCPToolDescriptor(
    name="qichacha.baseinfo",
    display_name="企查查-工商信息",
    category=ToolCategory.BUSINESS_DATA,
    capabilities=[ToolCapability.COMPANY_LOOKUP],
    server_name="qichacha",
    provider="qichacha",
    priority=7,
))
print(f"[registry] {reg.tool_count} tools, {reg.active_tool_count} active")

best = reg.get_best_tool(ToolCapability.COMPANY_LOOKUP)
assert best.name == "tianyancha.baseinfo", f"Expected tianyancha, got {best.name}"
assert best.priority == 10
print(f"[registry] best tool for COMPANY_LOOKUP: {best.name} (pri={best.priority})")

# capability → 2 个候选
tools = reg.find_by_capability(ToolCapability.COMPANY_LOOKUP)
assert len(tools) == 2
print(f"[registry] {len(tools)} tools for COMPANY_LOOKUP")

# ── Agent permissions ─────────────────────────────
reg.grant_agent("researcher", {ToolCapability.COMPANY_LOOKUP})
assert reg.agent_can_use("researcher", ToolCapability.COMPANY_LOOKUP)
assert not reg.agent_can_use("extractor", ToolCapability.COMPANY_LOOKUP)
print("[registry] agent permissions OK")

# ── Policy Engine ─────────────────────────────────
pe = PolicyEngine()
pe.register_policy(MCPInvocationPolicy(
    tool_name="tianyancha.baseinfo",
    max_timeout_ms=10_000,
    max_retries=1,
    circuit_breaker_threshold=3,
))
policy = pe.get_policy("tianyancha.baseinfo")
assert policy.circuit_breaker_threshold == 3
print(f"[policy] threshold={policy.circuit_breaker_threshold}")

# ── AuthProvider ──────────────────────────────────
ap = AuthProvider()
print("[auth] OK")

# ── ToolBus construction ──────────────────────────
bus = ToolBus(registry=reg, policy_engine=pe, auth_provider=ap)
print("[bus] construct OK")

# ── HealthChecker ─────────────────────────────────
hc = HealthChecker(reg, MCPClientManager())
s = hc.status_summary()
print(f"[health] ok={s['ok']}, tools={s['total_tools']}, servers={s['total_servers']}")

# ── Sandbox ───────────────────────────────────────
sb = ToolSandbox()
print("[sandbox] OK")

# ── Error mapping ─────────────────────────────────
e = _me("test.tool", Exception("TooManyRequests: 429"))
assert e.category == ErrorCategory.RATE_LIMIT
assert e.retryable
print(f"[errors] {e.category} retryable={e.retryable} backoff={e.suggested_backoff_ms}ms")

# ── CircuitBreaker ────────────────────────────────
cb = CircuitBreaker("test", threshold=2, recovery_ms=1000)
assert cb.state == CircuitState.CLOSED
cb.on_failure()
cb.on_failure()
assert cb.state == CircuitState.OPEN
assert not cb.allow_call()
print(f"[circuit] OPEN after 2 fails, blocked={not cb.allow_call()}")

# ── Disable/Enable ────────────────────────────────
reg.disable("qichacha.baseinfo")
enabled_tools = reg.find_by_capability(ToolCapability.COMPANY_LOOKUP)
assert len(enabled_tools) == 1, f"Expected 1 enabled, got {len(enabled_tools)}"
print(f"[registry] after disable: {len(enabled_tools)} enabled tools")

reg.enable("qichacha.baseinfo")
enabled_tools = reg.find_by_capability(ToolCapability.COMPANY_LOOKUP)
assert len(enabled_tools) == 2
print(f"[registry] after enable: {len(enabled_tools)} enabled tools")

# ── ToolBus.register_tool ─────────────────────────
new = MCPToolDescriptor(
    name="websearch.google",
    capabilities=[ToolCapability.WEB_SEARCH],
    category=ToolCategory.WEB_SEARCH,
    server_name="websearch",
    provider="google",
    priority=5,
)
bus.register_tool(new)
assert bus.registry.get("websearch.google") is not None
assert bus._policies.get_policy("websearch.google") is not None
print(f"[bus] register_tool OK")

print("\n=== ALL 15 TESTS PASSED ===")
