"""
Message Bus — 多 Agent 间消息通信总线

提供 Agent 间的异步消息传递能力，支持：
- 发布/订阅模式
- 点对点消息
- 广播消息
- 消息持久化（可选）
"""

import asyncio
import logging
from typing import Any, Callable, Optional
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


class Message:
    """消息对象"""
    def __init__(
        self,
        sender: str,
        recipient: Optional[str] = None,
        topic: Optional[str] = None,
        payload: Any = None,
    ):
        self.id = f"msg_{datetime.now().timestamp()}"
        self.sender = sender
        self.recipient = recipient
        self.topic = topic
        self.payload = payload
        self.timestamp = datetime.now()
        self.processed = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sender": self.sender,
            "recipient": self.recipient,
            "topic": self.topic,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
        }


class MessageBus:
    """
    消息总线 — Agent 间异步通信基础设施。

    支持三种通信模式：
    1. 点对点：指定 recipient
    2. 主题订阅：基于 topic 的发布/订阅
    3. 广播：不指定 recipient 和 topic
    """

    def __init__(self):
        # 点对点队列: {agent_name: [messages]}
        self._queues: dict[str, list[Message]] = defaultdict(list)

        # 主题订阅: {topic: [handler_functions]}
        self._subscriptions: dict[str, list[Callable]] = defaultdict(list)

        # 已注册的 Agent: {name: agent_instance}
        self._agents: dict[str, Any] = {}

        # 消息历史
        self._history: list[Message] = []
        self._max_history = 1000

        logger.info("MessageBus 初始化完成")

    def register(self, name: str, agent: Any) -> None:
        """注册 Agent 到总线"""
        self._agents[name] = agent
        logger.debug("Agent 已注册到总线: %s", name)

    def subscribe(self, topic: str, handler: Callable) -> None:
        """订阅主题"""
        self._subscriptions[topic].append(handler)
        logger.debug("已订阅主题: %s", topic)

    async def send(
        self,
        sender: str,
        recipient: Optional[str] = None,
        topic: Optional[str] = None,
        payload: Any = None,
    ) -> Message:
        """
        发送消息。

        Args:
            sender: 发送者名称
            recipient: 接收者名称（点对点模式）
            topic: 主题（发布/订阅模式）
            payload: 消息内容

        Returns:
            创建的消息对象
        """
        msg = Message(sender=sender, recipient=recipient, topic=topic, payload=payload)
        self._history.append(msg)
        self._trim_history()

        if recipient:
            # 点对点模式
            self._queues[recipient].append(msg)
            logger.debug("点对点消息: %s → %s", sender, recipient)

        elif topic:
            # 发布/订阅模式
            handlers = self._subscriptions.get(topic, [])
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(msg)
                    else:
                        handler(msg)
                except Exception as e:
                    logger.warning("主题处理异常 [%s]: %s", topic, e)

        else:
            # 广播模式
            for agent_name in self._agents:
                if agent_name != sender:
                    self._queues[agent_name].append(msg)

        msg.processed = True
        return msg

    async def receive(self, agent_name: str, limit: int = 10) -> list[Message]:
        """获取 Agent 的消息"""
        queue = self._queues[agent_name]
        messages = queue[:limit]
        self._queues[agent_name] = queue[limit:]
        return messages

    async def broadcast(self, sender: str, payload: Any) -> list[Message]:
        """广播消息给所有 Agent"""
        messages = []
        for name in self._agents:
            if name != sender:
                msg = await self.send(sender=sender, recipient=name, payload=payload)
                messages.append(msg)
        return messages

    def get_history(self, limit: int = 50) -> list[dict]:
        """获取最近的消息历史"""
        return [m.to_dict() for m in self._history[-limit:]]

    def _trim_history(self) -> None:
        """裁剪历史记录"""
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def clear(self) -> None:
        """清空所有队列和历史"""
        self._queues.clear()
        self._subscriptions.clear()
        self._history.clear()
        logger.info("MessageBus 已清空")
