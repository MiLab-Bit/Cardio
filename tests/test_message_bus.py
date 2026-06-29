"""
Message Bus 测试
"""

import pytest
import asyncio

from byou.core.message_bus import MessageBus, Message


@pytest.mark.asyncio
async def test_register_agent():
    """测试 Agent 注册"""
    bus = MessageBus()
    agent = object()
    bus.register("test_agent", agent)
    assert "test_agent" in bus._agents


@pytest.mark.asyncio
async def test_send_peer_to_peer():
    """测试点对点消息"""
    bus = MessageBus()
    bus.register("agent_a", object())
    bus.register("agent_b", object())

    msg = await bus.send(
        sender="agent_a",
        recipient="agent_b",
        payload={"key": "value"},
    )

    assert msg.sender == "agent_a"
    assert msg.recipient == "agent_b"
    assert msg.payload == {"key": "value"}

    # agent_b 应该收到消息
    received = await bus.receive("agent_b")
    assert len(received) == 1
    assert received[0].sender == "agent_a"


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    """测试发布/订阅"""
    bus = MessageBus()
    received_messages = []

    async def handler(msg):
        received_messages.append(msg)

    bus.subscribe("test_topic", handler)

    await bus.send(
        sender="publisher",
        topic="test_topic",
        payload={"data": 123},
    )

    assert len(received_messages) == 1
    assert received_messages[0].payload["data"] == 123


@pytest.mark.asyncio
async def test_broadcast():
    """测试广播"""
    bus = MessageBus()
    bus.register("agent_a", object())
    bus.register("agent_b", object())
    bus.register("agent_c", object())

    sent = await bus.broadcast("agent_a", {"broadcast": True})
    # 广播给除自己外的所有 Agent
    assert len(sent) == 2

    # agent_a 自己不应收到广播
    own_msgs = await bus.receive("agent_a")
    assert len(own_msgs) == 0


@pytest.mark.asyncio
async def test_receive_limit():
    """测试接收消息数量限制"""
    bus = MessageBus()
    bus.register("agent_a", object())
    bus.register("agent_b", object())

    for i in range(10):
        await bus.send(
            sender="agent_a",
            recipient="agent_b",
            payload={"index": i},
        )

    msgs = await bus.receive("agent_b", limit=3)
    assert len(msgs) == 3

    # 剩余消息仍在队列中
    remaining = await bus.receive("agent_b")
    assert len(remaining) == 7


@pytest.mark.asyncio
async def test_history():
    """测试消息历史"""
    bus = MessageBus()
    bus.register("a", object())
    bus.register("b", object())

    await bus.send("a", recipient="b", payload={"msg": 1})
    await bus.send("b", recipient="a", payload={"msg": 2})

    history = bus.get_history()
    assert len(history) == 2


@pytest.mark.asyncio
async def test_clear():
    """测试清空"""
    bus = MessageBus()
    bus.register("agent_a", object())

    await bus.send("agent_a", recipient="agent_b", payload={"test": True})
    bus.clear()

    assert len(bus._queues) == 0
    assert len(bus._history) == 0


@pytest.mark.asyncio
async def test_history_trimming():
    """测试历史裁剪"""
    bus = MessageBus()
    bus.register("a", object())
    bus.register("b", object())

    for i in range(1500):
        await bus.send("a", recipient="b", payload={"i": i})

    history = bus.get_history(limit=2000)
    assert len(history) <= 1000
