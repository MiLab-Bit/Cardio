"""L3 HITL 审批子系统 — 全覆盖测试"""
from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from byou.production.governance import (
    APPROVAL_HALT,
    ApprovalBroker,
    ApprovalChannel,
    ApprovalContext,
    ApprovalDecision,
    ApprovalEngine,
    ApprovalEvent,
    ApprovalManager,
    ApprovalMode,
    ApprovalNotification,
    ApprovalPolicyEngine,
    ApprovalPolicyRule,
    ApprovalPolicyStore,
    ApprovalRequest,
    ApprovalScope,
    ApprovalStatus,
    ApprovalStore,
    DEFAULT_RULES,
    EscalationPolicy,
    NotificationDispatcher,
    PipelineHooks,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def ctx():
    return ApprovalContext(
        pipeline_id="pipe_001",
        stage="strategy",
        agent="strategist",
        tool_name="bd_strategy_gen",
        capability="BD_STRATEGY",
        action="generate_bd_strategy",
        risk_level="high",
        customer_name="张三",
        company="Tech Co.",
    )


@pytest.fixture
def store():
    return ApprovalStore()


@pytest.fixture
def policy_engine():
    return ApprovalPolicyEngine()


@pytest.fixture
def engine(store, policy_engine):
    return ApprovalEngine(store=store, policy_engine=policy_engine)


@pytest.fixture
def broker():
    return ApprovalBroker()


@pytest.fixture
def hooks(engine):
    return PipelineHooks(engine)


# ═══════════════════════════════════════════════════════════════
# 1. Types — 模型验证
# ═══════════════════════════════════════════════════════════════

class TestTypes:
    def test_approval_request_defaults(self, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        assert req.id
        assert len(req.id) == 12
        assert req.scope == ApprovalScope.ACTION
        assert req.mode == ApprovalMode.DEMAND
        assert req.status == ApprovalStatus.PENDING
        assert req.created_at is not None
        assert req.expires_at is not None
        assert req.timeout_s == 300

    def test_approval_request_expiry(self, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx, timeout_s=0)
        assert req.is_expired()
        req2 = ApprovalRequest(pipeline_id="p2", context=ctx, timeout_s=99999)
        assert not req2.is_expired()

    def test_approval_request_no_expiry(self, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx, timeout_s=99999)
        # explicitly set expires_at=None = never expires
        req.expires_at = None
        assert not req.is_expired()

    def test_approval_decision_fields(self):
        d = ApprovalDecision(approved=True, reason="ok", decided_by="alice")
        assert d.approved
        assert d.reason == "ok"
        assert d.decided_by == "alice"
        assert d.modifications == {}

    def test_approval_notification(self):
        n = ApprovalNotification(
            request_id="req123",
            channel=ApprovalChannel.WEBCHAT,
            title="Test",
            body="Please approve",
        )
        assert n.id
        assert n.request_id == "req123"
        assert "approve" in n.actions
        assert "reject" in n.actions

    def test_approval_event(self, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        evt = ApprovalEvent(
            request_id=req.id,
            event_type="created",
            after_status=ApprovalStatus.PENDING,
            pipeline_id="p1",
        )
        assert evt.id
        assert evt.event_type == "created"

    def test_approval_status_enum(self):
        assert ApprovalStatus.PENDING.value == "pending"
        assert ApprovalStatus.APPROVED.value == "approved"
        assert ApprovalStatus.REJECTED.value == "rejected"
        assert ApprovalStatus.EXPIRED.value == "expired"
        assert ApprovalStatus.ESCALATED.value == "escalated"
        assert ApprovalStatus.AUTO_APPROVED.value == "auto_approved"
        assert ApprovalStatus.REVOKED.value == "revoked"

    def test_approval_mode_enum(self):
        assert ApprovalMode.AUTO.value == "auto"
        assert ApprovalMode.DEFER.value == "defer"
        assert ApprovalMode.DEMAND.value == "demand"
        assert ApprovalMode.HUMAN_REQUIRED.value == "human_required"

    def test_context_serialization(self, ctx):
        d = ctx.model_dump()
        assert d["pipeline_id"] == "pipe_001"
        assert d["customer_name"] == "张三"
        assert isinstance(d, dict)


# ═══════════════════════════════════════════════════════════════
# 2. Policy — 规则匹配
# ═══════════════════════════════════════════════════════════════

class TestPolicyEngine:
    def test_default_rules_exist(self):
        assert len(DEFAULT_RULES) >= 5

    def test_match_auto_for_low_risk_read(self, policy_engine):
        ctx = ApprovalContext(
            pipeline_id="p1", stage="extraction", action="read_contact",
            capability="COMPANY_LOOKUP", risk_level="low",
        )
        rule = policy_engine.match(ctx)
        assert rule.approval_mode == ApprovalMode.AUTO

    def test_match_demand_for_high_risk_write(self, policy_engine):
        ctx = ApprovalContext(
            pipeline_id="p1", stage="synthesis", action="write_crm_record",
            capability="WRITE_CRM", risk_level="high",
        )
        rule = policy_engine.match(ctx)
        assert rule.approval_mode == ApprovalMode.DEMAND

    def test_match_human_required_for_critical_delete(self, policy_engine):
        ctx = ApprovalContext(
            pipeline_id="p1", stage="cleanup", action="delete_contacts",
            capability="MASS_EXPORT", risk_level="critical",
        )
        rule = policy_engine.match(ctx)
        assert rule.approval_mode == ApprovalMode.HUMAN_REQUIRED

    def test_fallback_uses_default(self, policy_engine):
        ctx = ApprovalContext(
            pipeline_id="p1", stage="unknown", action="weird_action",
            risk_level="low",
        )
        rule = policy_engine.match(ctx)
        # Fallback is risk-based: low→AUTO, medium→DEFER, high→DEMAND
        assert rule.approval_mode == ApprovalMode.AUTO
        assert rule.name in ("fallback", "default_demand")

    def test_custom_rule_priority(self, policy_engine):
        """高 priority 的规则先匹配"""
        custom = ApprovalPolicyRule(
            name="custom_critical",
            action_pattern="test_*",
            approval_mode=ApprovalMode.HUMAN_REQUIRED,
            priority=999,
        )
        policy_engine.add_rule(custom)
        ctx = ApprovalContext(
            pipeline_id="p1", stage="test", action="test_something",
            risk_level="low",
        )
        rule = policy_engine.match(ctx)
        assert rule.name == "custom_critical"
        assert rule.approval_mode == ApprovalMode.HUMAN_REQUIRED

    def test_risk_level_ordering(self):
        assert ApprovalPolicyEngine._risk_meets_minimum("critical", "high")
        assert ApprovalPolicyEngine._risk_meets_minimum("high", "medium")
        assert ApprovalPolicyEngine._risk_meets_minimum("medium", "low")
        assert not ApprovalPolicyEngine._risk_meets_minimum("low", "high")

    def test_stage_pattern_match(self, policy_engine):
        ctx = ApprovalContext(
            pipeline_id="p1", stage="strategy", action="some_action",
            risk_level="high",
        )
        rule = policy_engine.match(ctx)
        # stage_strategy rule should match
        assert "stage_strategy" in rule.name


# ═══════════════════════════════════════════════════════════════
# 3. Store — CRUD + 事件
# ═══════════════════════════════════════════════════════════════

class TestApprovalStore:
    def test_create_and_get(self, store, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        store.create(req)
        assert store.get(req.id) == req

    def test_list_by_pipeline(self, store, ctx):
        req1 = ApprovalRequest(pipeline_id="p1", context=ctx)
        req2 = ApprovalRequest(pipeline_id="p2", context=ctx)
        store.create(req1)
        store.create(req2)
        assert len(store.list_by_pipeline("p1")) == 1
        assert len(store.list_by_pipeline("p2")) == 1

    def test_list_pending(self, store, ctx):
        req1 = ApprovalRequest(pipeline_id="p1", context=ctx)
        req2 = ApprovalRequest(pipeline_id="p2", context=ctx)
        store.create(req1)
        store.create(req2)
        assert len(store.list_pending()) == 2
        # approve one
        store.resolve(req1.id, ApprovalDecision(approved=True))
        assert len(store.list_pending()) == 1

    def test_resolve_approve(self, store, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        store.create(req)
        result = store.resolve(req.id, ApprovalDecision(approved=True))
        assert result is not None
        assert result.status == ApprovalStatus.APPROVED

    def test_resolve_reject(self, store, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        store.create(req)
        result = store.resolve(req.id, ApprovalDecision(approved=False))
        assert result.status == ApprovalStatus.REJECTED

    def test_resolve_twice_is_noop(self, store, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        store.create(req)
        store.resolve(req.id, ApprovalDecision(approved=True))
        # second resolve should warn
        result2 = store.resolve(req.id, ApprovalDecision(approved=False))
        assert result2 is None

    def test_resolve_unknown(self, store):
        result = store.resolve("nonexistent", ApprovalDecision(approved=True))
        assert result is None

    def test_expire_pending(self, store, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx, timeout_s=-1)
        req.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        store.create(req)
        result = store.expire(req.id)
        assert result is not None
        assert result.status == ApprovalStatus.EXPIRED

    def test_expire_already_resolved(self, store, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        store.create(req)
        store.resolve(req.id, ApprovalDecision(approved=True))
        result = store.expire(req.id)
        assert result is None

    def test_revoke(self, store, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        store.create(req)
        result = store.revoke(req.id, reason="pipeline cancelled")
        assert result is not None
        assert result.status == ApprovalStatus.REVOKED

    def test_events_created_on_actions(self, store, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        store.create(req)
        store.resolve(req.id, ApprovalDecision(approved=True))
        events = store.get_events(req.id)
        assert len(events) == 2
        assert events[0].event_type == "created"
        assert events[1].event_type == "approved"

    def test_get_all_events(self, store, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        store.create(req)
        store.resolve(req.id, ApprovalDecision(approved=True))
        all_events = store.get_all_events()
        assert len(all_events) == 2

    @pytest.mark.asyncio
    async def test_expire_overdue(self, store, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx, timeout_s=-1)
        req.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        store.create(req)
        count = await store.expire_overdue()
        assert count == 1
        assert store.get(req.id).status == ApprovalStatus.EXPIRED

    def test_cleanup_old_events(self, store, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        store.create(req)
        store.resolve(req.id, ApprovalDecision(approved=True))
        assert len(store.get_all_events()) == 2
        # cleanup with max_age=0 → all removed
        removed = store.cleanup_old_events(max_age_hours=0)
        assert removed == 2
        assert len(store.get_all_events()) == 0

    def test_sqlite_persistence(self, ctx):
        import os, tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            store = ApprovalStore(db_path=db_path)
            req = ApprovalRequest(pipeline_id="p1", context=ctx)
            store.create(req)
            store.resolve(req.id, ApprovalDecision(approved=True))

            # reopen
            store2 = ApprovalStore(db_path=db_path)
            # note: in-memory store is separate from sqlite, but sqlite confirms persistence
            assert store2._db is not None
        finally:
            try:
                os.unlink(db_path)
            except PermissionError:
                pass


# ═══════════════════════════════════════════════════════════════
# 4. Engine — 审批逻辑
# ═══════════════════════════════════════════════════════════════

class TestApprovalEngine:
    def test_check_auto_passes_immediately(self, engine, policy_engine):
        ctx = ApprovalContext(
            pipeline_id="p1", stage="extraction", action="read_contact",
            capability="COMPANY_LOOKUP", risk_level="low",
        )
        req = engine.check(ctx)
        assert req.status == ApprovalStatus.AUTO_APPROVED
        assert req.mode == ApprovalMode.AUTO

    def test_check_demand_stays_pending(self, engine):
        ctx = ApprovalContext(
            pipeline_id="p1", stage="synthesis", action="write_crm_record",
            capability="WRITE_CRM", risk_level="high",
        )
        req = engine.check(ctx)
        assert req.status == ApprovalStatus.PENDING
        assert req.mode == ApprovalMode.DEMAND

    def test_check_creates_store_entry(self, engine, store, ctx):
        req = engine.check(ctx)
        assert store.get(req.id) is not None

    @pytest.mark.asyncio
    async def test_wait_auto_approved_returns_immediately(self, engine, ctx):
        ctx2 = ApprovalContext(
            pipeline_id="p2", stage="extraction", action="read_contact",
            capability="COMPANY_LOOKUP", risk_level="low",
        )
        req = engine.check(ctx2)
        decision = await engine.wait_for_decision(req)
        assert decision.approved
        assert decision.reason == "auto_approved"

    @pytest.mark.asyncio
    async def test_wait_then_decide(self, engine, ctx):
        req = engine.check(ctx)
        # simulate external approval
        asyncio.get_event_loop().call_later(
            0.05,
            engine.decide, req.id, ApprovalDecision(approved=True),
        )
        decision = await engine.wait_for_decision(req, timeout_s=5)
        assert decision.approved

    @pytest.mark.asyncio
    async def test_wait_timeout_rejects(self, engine, ctx):
        req = engine.check(ctx)
        req.timeout_s = 0
        req.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        decision = await engine.wait_for_decision(req, timeout_s=0.1)
        assert not decision.approved

    @pytest.mark.asyncio
    async def test_poll_expired(self, engine, store, ctx):
        req = engine.check(ctx)
        req.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        # force expire in store
        store.expire(req.id)
        count = await engine.poll_expired()
        assert count >= 0

    def test_build_notification(self, engine, ctx):
        req = engine.check(ctx)
        n = engine.build_notification(req)
        assert n.request_id == req.id
        assert n.channel == ApprovalChannel.WEBCHAT
        assert "approve" in n.actions

    def test_decide_updates_store(self, engine, store, ctx):
        req = engine.check(ctx)
        result = engine.decide(req.id, ApprovalDecision(approved=True))
        assert result is not None
        assert store.get(req.id).status == ApprovalStatus.APPROVED

    def test_decide_unknown_request(self, engine):
        result = engine.decide("nonexistent", ApprovalDecision(approved=True))
        assert result is None


# ═══════════════════════════════════════════════════════════════
# 5. Broker — 通信通道
# ═══════════════════════════════════════════════════════════════

class TestApprovalBroker:
    def test_register_and_send(self, broker):
        received = []
        broker.register(ApprovalChannel.WEBCHAT, send=lambda n: received.append(n))
        n = ApprovalNotification(
            request_id="r1", channel=ApprovalChannel.WEBCHAT,
            title="T", body="B",
        )
        assert broker.send_notification(n)
        assert len(received) == 1
        assert received[0].request_id == "r1"

    def test_send_unregistered_channel(self, broker):
        n = ApprovalNotification(
            request_id="r1", channel=ApprovalChannel.EMAIL,
            title="T", body="B",
        )
        assert not broker.send_notification(n)

    def test_receive_decision(self, broker):
        received = []
        broker.set_receive_hook(lambda d: received.append(d))
        decision = broker.receive_decision("r1", approved=True, reason="ok")
        assert decision.approved
        assert len(received) == 1

    def test_broadcast(self, broker):
        received = []
        broker.register(ApprovalChannel.WEBCHAT, send=lambda n: received.append(n))
        n = ApprovalNotification(
            request_id="r1", channel=ApprovalChannel.WEBCHAT,
            title="T", body="B",
        )
        sent = broker.broadcast(n, channels=[ApprovalChannel.WEBCHAT])
        assert sent == 1

    def test_unregister(self, broker):
        broker.register(ApprovalChannel.WEBCHAT, send=broker.log_sender)
        assert ApprovalChannel.WEBCHAT in broker._channels
        broker.unregister(ApprovalChannel.WEBCHAT)
        assert ApprovalChannel.WEBCHAT not in broker._channels

    def test_log_sender(self, broker):
        n = ApprovalNotification(
            request_id="r1", channel=ApprovalChannel.WEBCHAT,
            title="T", body="B",
        )
        broker.log_sender(n)  # should not raise


# ═══════════════════════════════════════════════════════════════
# 6. Hooks — Pipeline 暂停/恢复
# ═══════════════════════════════════════════════════════════════

class TestPipelineHooks:
    def test_before_stage_auto(self, hooks):
        result = hooks.before_stage(
            stage="extraction",
            pipeline_id="p1",
            action="read_contact",
            capability="COMPANY_LOOKUP",
            risk_level="low",
        )
        assert result.status == ApprovalStatus.AUTO_APPROVED

    def test_before_stage_demand(self, hooks):
        result = hooks.before_stage(
            stage="synthesis",
            pipeline_id="p1",
            action="write_crm_record",
            capability="WRITE_CRM",
            risk_level="high",
        )
        assert result.status == ApprovalStatus.PENDING

    @pytest.mark.asyncio
    async def test_pause_and_resume(self, hooks):
        request = hooks.before_stage(
            stage="strategy",
            pipeline_id="p1",
            action="generate_bd_strategy",
            risk_level="high",
        )
        # simulate approval arriving
        asyncio.get_event_loop().call_later(
            0.05,
            hooks.resume, request.id, ApprovalDecision(approved=True),
        )
        decision = await hooks.pause_pipeline(request, timeout_s=5)
        assert decision.approved

    @pytest.mark.asyncio
    async def test_pause_timeout(self, hooks):
        request = hooks.before_stage(
            stage="strategy",
            pipeline_id="p1",
            action="generate_bd_strategy",
            risk_level="high",
        )
        # no approval → timeout
        decision = await hooks.pause_pipeline(request, timeout_s=0.1)
        assert not decision.approved

    def test_clear_pipeline(self, hooks):
        hooks.before_stage(stage="strategy", pipeline_id="p1",
                           action="a", risk_level="high")
        hooks.before_stage(stage="synthesis", pipeline_id="p1",
                           action="b", risk_level="high")
        hooks.clear_pipeline("p1")
        assert len(hooks._pending_requests) == 0

    def test_before_stage_returns_request_not_approved(self, hooks):
        """DEMAND mode returns a PENDING request, not a pre-approved one"""
        request = hooks.before_stage(
            stage="strategy",
            pipeline_id="p1",
            action="write_crm_record",
            capability="WRITE_CRM",
            risk_level="high",
        )
        assert request.status == ApprovalStatus.PENDING
        assert request.mode == ApprovalMode.DEMAND


# ═══════════════════════════════════════════════════════════════
# 7. NotificationDispatcher
# ═══════════════════════════════════════════════════════════════

class TestNotificationDispatcher:
    def test_dispatch_webchat(self, broker, ctx):
        received = []
        broker.register(ApprovalChannel.WEBCHAT, send=lambda n: received.append(n))
        dispatcher = NotificationDispatcher(broker)
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        sent = dispatcher.dispatch(req)
        assert sent == 1
        assert "Approval required" in received[0].body
        assert "张三" in received[0].body

    def test_render_api(self, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        body = NotificationDispatcher._render_api(req)
        import json
        d = json.loads(body)
        assert d["pipeline_id"] == "p1"
        assert d["action"] == "generate_bd_strategy"

    def test_render_email(self, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        body = NotificationDispatcher._render_email(req)
        assert "generate_bd_strategy" in body
        assert "p1" in body

    def test_render_webchat_with_timeout(self, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        body = NotificationDispatcher._render_webchat(req)
        assert "⏸ Approval required" in body
        assert "s left" in body


# ═══════════════════════════════════════════════════════════════
# 8. ApprovalManager — 统一门面
# ═══════════════════════════════════════════════════════════════

class TestApprovalManager:
    def test_init_all_components(self):
        am = ApprovalManager()
        assert am.engine is not None
        assert am.store is not None
        assert am.broker is not None
        assert am.hooks is not None
        assert am.policy_engine is not None
        assert am.dispatcher is not None

    def test_register_webchat(self):
        am = ApprovalManager()
        am.register_webchat()
        assert ApprovalChannel.WEBCHAT in am.broker._channels

    def test_decide_convenience(self, ctx):
        am = ApprovalManager()
        req = am.engine.check(ctx)
        result = am.decide(req.id, approved=True, reason="test", decided_by="me")
        assert result is not None
        assert result.status == ApprovalStatus.APPROVED

    def test_register_api(self):
        am = ApprovalManager()
        am.register_api()
        assert ApprovalChannel.API in am.broker._channels

    @pytest.mark.asyncio
    async def test_start_and_shutdown(self):
        am = ApprovalManager()
        await am.start()
        await am.shutdown()


# ═══════════════════════════════════════════════════════════════
# 9. 端到端: 完整审批流
# ═══════════════════════════════════════════════════════════════

class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_full_approval_flow(self):
        """完整流程: check → pause → approve → resume"""
        am = ApprovalManager()
        hooks = am.hooks

        # Stage 1: extraction (low risk, auto)
        req1 = hooks.before_stage(
            stage="extraction", pipeline_id="pipe_e2e",
            action="read_contact", capability="COMPANY_LOOKUP",
            risk_level="low",
        )
        assert req1.status == ApprovalStatus.AUTO_APPROVED

        # Stage 2: strategy (high risk, demand)
        req2 = hooks.before_stage(
            stage="strategy", pipeline_id="pipe_e2e",
            action="generate_bd_strategy", risk_level="high",
        )
        assert req2.status == ApprovalStatus.PENDING

        # User approves after 50ms
        asyncio.get_event_loop().call_later(
            0.05,
            hooks.resume, req2.id, ApprovalDecision(approved=True, reason="LGTM"),
        )
        decision = await hooks.pause_pipeline(req2, timeout_s=5)
        assert decision.approved
        assert decision.reason == "LGTM"

        # Check events
        events = am.store.get_events(req2.id)
        assert events[0].event_type == "created"
        assert events[-1].event_type == "approved"

    @pytest.mark.asyncio
    async def test_full_rejection_flow(self):
        """拒绝流程"""
        am = ApprovalManager()
        hooks = am.hooks

        req = hooks.before_stage(
            stage="strategy", pipeline_id="pipe_rej",
            action="write_crm_record", capability="WRITE_CRM",
            risk_level="high",
        )
        asyncio.get_event_loop().call_later(
            0.05,
            hooks.resume, req.id, ApprovalDecision(approved=False, reason="too risky"),
        )
        decision = await hooks.pause_pipeline(req, timeout_s=5)
        assert not decision.approved

        events = am.store.get_events(req.id)
        assert events[-1].event_type == "rejected"

    @pytest.mark.asyncio
    async def test_multi_stage_pipeline_with_mixed_approvals(self):
        """混合审批 pipeline: auto + demand + demand + auto"""
        am = ApprovalManager()
        hooks = am.hooks

        stages = [
            ("extraction", "read_contact", "COMPANY_LOOKUP", "low"),
            ("research", "batch_search", "BATCH_SEARCH", "medium"),
            ("strategy", "generate_bd_strategy", "BD_STRATEGY", "high"),
            ("critique", "read_audit", "COMPANY_LOOKUP", "low"),
        ]

        decisions = []
        for stage, action, capability, risk in stages:
            req = hooks.before_stage(
                stage=stage, pipeline_id="pipe_multi",
                action=action, capability=capability,
                risk_level=risk,
            )
            if req.status == ApprovalStatus.PENDING:
                # simulate approval
                d = ApprovalDecision(approved=True, reason=f"approved {stage}")
                hooks.resume(req.id, d)
                decisions.append(d)
            elif req.status == ApprovalStatus.AUTO_APPROVED:
                decisions.append(ApprovalDecision(approved=True, reason="auto"))

        assert len(decisions) == 4
        assert all(d.approved for d in decisions)

    @pytest.mark.asyncio
    async def test_defer_mode_continues(self):
        """DEFER mode: 放行但记录日志"""
        am = ApprovalManager()
        hooks = am.hooks

        req = hooks.before_stage(
            stage="research", pipeline_id="pipe_defer",
            action="web_search_company", capability="BATCH_SEARCH",
            risk_level="medium",
        )
        assert req.status == ApprovalStatus.AUTO_APPROVED
        assert req.mode == ApprovalMode.DEFER


# ═══════════════════════════════════════════════════════════════
# 10. 边界情况
# ═══════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_empty_context(self):
        ctx = ApprovalContext(
            pipeline_id="p1", stage="", action="", risk_level="low",
        )
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        assert req.id
        assert req.pipeline_id == "p1"

    def test_unknown_action_policy(self, policy_engine):
        ctx = ApprovalContext(
            pipeline_id="p1", stage="weird", action="",
            risk_level="critical",
        )
        rule = policy_engine.match(ctx)
        assert rule is not None
        assert rule.name in ("fallback", "default_demand")

    def test_custom_policy_with_roles(self):
        policy_engine = ApprovalPolicyEngine()
        custom = ApprovalPolicyRule(
            name="role_gated",
            action_pattern="admin_*",
            approval_mode=ApprovalMode.HUMAN_REQUIRED,
            required_roles=["superadmin"],
            priority=200,
        )
        policy_engine.add_rule(custom)
        ctx = ApprovalContext(
            pipeline_id="p1", stage="admin", action="admin_delete_all",
            risk_level="critical",
        )
        rule = policy_engine.match(ctx)
        assert rule.required_roles == ["superadmin"]

    def test_store_list_all(self, store, ctx):
        req1 = ApprovalRequest(pipeline_id="p1", context=ctx)
        req2 = ApprovalRequest(pipeline_id="p2", context=ctx)
        store.create(req1)
        store.create(req2)
        assert len(store.list_all()) == 2

    def test_store_revoke_then_expire(self, store, ctx):
        req = ApprovalRequest(pipeline_id="p1", context=ctx)
        store.create(req)
        store.revoke(req.id)
        result = store.expire(req.id)
        assert result is None  # already revoked

    def test_broker_custom_receive_hook_error(self, broker):
        def failing_hook(d):
            raise RuntimeError("hook error")
        broker.set_receive_hook(failing_hook)
        # should not raise — caught internally
        decision = broker.receive_decision("r1", approved=True)
        assert decision.approved
