"""Byou CLI — demo commands to exercise core pipelines.

Usage:
    python -m byou.cli intake --name "张三" --phone "13800001111"
    python -m byou.cli cua     --url "https://example.com/form"
    python -m byou.cli chat    --message "帮我分析这个客户"

All commands work WITHOUT external API calls (use mocks/memory).
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


# ───────────────────────────────────────────────────────────
#  Intake demo
# ───────────────────────────────────────────────────────────

def cmd_intake(args: argparse.Namespace) -> None:
    """Simulate an intake session with mock data."""
    print("\n── Byou Intake Demo ─────────────────────")
    print(f"  Name:  {args.name or '(none)'}")
    print(f"  Phone: {args.phone or '(none)'}")
    print(f"  Card:  {args.card or '(none)'}")

    # Build a mock RawIntakePackage
    from byou.intake.models import BusinessCard, RawIntakePackage

    cards = []
    if args.name or args.phone or args.card:
        cards.append(BusinessCard(
            name=args.name or "",
            phone=args.phone or "",
            company=args.company or "",
        ))

    if not cards and not args.voiceprint:
        print("  ⚠️  No input provided, using demo data...")
        cards.append(BusinessCard(name="张三", phone="13800001111", company="测试科技"))

    raw = RawIntakePackage(cards=cards)

    # Run handler (with in-memory graph)
    from byou.intake.identity.graph import IdentityGraph, IdentityNode, NodeType
    from byou.intake.handler import IntakeHandler

    graph = IdentityGraph()
    # Pre-populate with a known identity
    graph.add_node(IdentityNode(
        node_id="uid_demo_001",
        node_type=NodeType.UID,
        label="张三",
        metadata={"phone": "13800001111", "company": "测试科技"},
    ))

    handler = IntakeHandler(identity_graph=graph)

    print("\n  Running intake pipeline...\n")
    result = asyncio.run(handler.handle(raw))

    print("  Result:")
    print(f"    session_id:  {result.session_id}")
    print(f"    participants: {len(result.canonical_session.get('participants', []))}")
    print(f"    memory_seeds: {len(result.memory_seeds)}")
    print(f"    crm_seeds:     {len(result.crm_seeds)}")
    print(f"    review_required: {result.review_required}")
    if result.errors:
        print(f"    errors: {result.errors}")

    if args.output:
        Path(args.output).write_text(
            json.dumps(result.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n  Output written to: {args.output}")

    print("── Done ─────────────────────────────\n")


# ───────────────────────────────────────────────────────────
#  CUA demo
# ───────────────────────────────────────────────────────────

def cmd_cua(args: argparse.Namespace) -> None:
    """Simulate CUA planning on a mock page state."""
    print("\n── Byou CUA Planning Demo ─────────────────────")
    print(f"  URL: {args.url or '(none)'}")
    print(f"  Title: {args.title or '(none)'}")

    from byou.cua.state_model import StateBuilder, StateClusterer
    from byou.cua.planning import PlanningLayer

    # Build perception from args or use demo data
    perception = {
        "url": args.url or "https://example.com/expo-register",
        "title": args.title or "博览会报名表单",
        "dom_text": "<html><body><form><input name='name'><input name='phone'><button>提交</button></form></body></html>",
        "elements": [
            {"type": "input", "text": "姓名"},
            {"type": "input", "text": "电话"},
            {"type": "button", "text": "提交"},
        ],
    }

    print("\n  Building state model...")
    state = StateBuilder.from_perception(perception)
    print(f"    state_id:  {state.state_id}")
    print(f"    elements:  {state.element_count}")

    print("  Checking state cluster...")
    clusterer = StateClusterer()
    cid, is_new = clusterer.get_or_add(state)
    print(f"    cluster_id: {cid}, is_new: {is_new}")

    print("\n  Generating plan...\n")
    layer = PlanningLayer()

    @dataclass
    class FakeTask:
        id: str = "demo_task"
        target_url: str = ""
        actions: list = None

    task = FakeTask()
    plan = asyncio.run(layer.process(perception, task, context=None))

    print("  Plan:")
    print(f"    plan_id:       {plan['plan_id']}")
    print(f"    state_id:      {plan['state_id']}")
    print(f"    cluster_id:    {plan['cluster_id']}")
    print(f"    estimated_steps: {plan['estimated_steps']}")
    print(f"    reused_plan:    {plan['reused_plan']}")
    print("\n  Steps:")
    for step in plan["steps"]:
        print(f"    [{step['step']}] {step['action']}: {step['description']}")

    if args.output:
        Path(args.output).write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\n  Output written to: {args.output}")

    print("── Done ─────────────────────────────\n")


# ───────────────────────────────────────────────────────────
#  Chat demo
# ───────────────────────────────────────────────────────────

def cmd_chat(args: argparse.Namespace) -> None:
    """Simulate a multi-agent chat (mock response)."""
    print("\n── Byou Multi-Agent Chat Demo ─────────────────────")
    print(f"  Message: {args.message}")

    from byou.core.model_router import ModelRouter, ModelTier

    router = ModelRouter()
    decision = router.route(args.message, force_tier=ModelTier.CHEAP)
    print(f"\n  Routing decision:")
    print(f"    tier:       {decision.tier.value}")
    print(f"    model:      {decision.model_name}")
    print(f"    reasons:    {decision.reasons}")

    # Mock agent response
    print(f"\n  Mock agent response:")
    print(f"    在一起博览会上，我遇到了一位名叫 {args.name or '李明'} 的潜在客户...")
    print(f"    他的公司 ({args.company or '未知'}) 在我们的目标行业中...")

    print("── Done ─────────────────────────────\n")


# ───────────────────────────────────────────────────────────
#  CLI entry point
# ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Byou CLI — demo commands for core pipelines",
    )
    sub = parser.add_subparsers(dest="command")

    # intake
    p_intake = sub.add_parser("intake", help="Run intake pipeline demo")
    p_intake.add_argument("--name", default="", help="Contact name")
    p_intake.add_argument("--phone", default="", help="Contact phone")
    p_intake.add_argument("--company", default="", help="Contact company")
    p_intake.add_argument("--card", default="", help="Path to card image (unused in demo)")
    p_intake.add_argument("--voiceprint", default="", help="Path to voiceprint (unused in demo)")
    p_intake.add_argument("--output", default="", help="Write result to JSON file")

    # cua
    p_cua = sub.add_parser("cua", help="Run CUA planning demo")
    p_cua.add_argument("--url", default="", help="Target URL")
    p_cua.add_argument("--title", default="", help="Page title")
    p_cua.add_argument("--output", default="", help="Write plan to JSON file")

    # chat
    p_chat = sub.add_parser("chat", help="Simulate multi-agent chat")
    p_chat.add_argument("--message", default="帮我分析这个客户", help="User message")
    p_chat.add_argument("--name", default="李明", help="Contact name for mock response")
    p_chat.add_argument("--company", default="", help="Contact company for mock response")

    args = parser.parse_args()

    if args.command == "intake":
        cmd_intake(args)
    elif args.command == "cua":
        cmd_cua(args)
    elif args.command == "chat":
        cmd_chat(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
