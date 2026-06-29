# Message Bus 消息总线

## 文件

`byou/core/message_bus.py` → `MessageBus`

## 职责

Agent 间通信基础设施，支持三种模式。

## 架构

```
┌──────────────────────────────────────────────┐
│                 MessageBus                    │
│                                               │
│  P2P (点对点):                                 │
│    Agent A ──────────────→ Agent B            │
│    send(sender=A, recipient=B, payload)        │
│                                               │
│  PubSub (发布/订阅):                           │
│    Publisher ─→ Topic ─→ Subscriber1           │
│                       ─→ Subscriber2           │
│                                               │
│  Broadcast (广播):                              │
│    Sender ─→ All (except sender)               │
└──────────────────────────────────────────────┘
```

## 三种通信模式

### 1. P2P（点对点）

```python
await bus.send(
    sender="extractor",
    recipient="researcher",
    payload={"company": "华为"}
)

# Researcher 拉取
msgs = await bus.receive("researcher")
```

### 2. PubSub（发布/订阅）

```python
# 订阅
async def on_customer_update(msg):
    print(f"客户更新: {msg.payload}")

bus.subscribe("customer.updated", on_customer_update)

# 发布
await bus.send(sender="extractor", topic="customer.updated", payload=data)
```

### 3. Broadcast（广播）

```python
sent = await bus.broadcast("orchestrator", {"event": "pipeline_complete"})
# 广播给除 orchestrator 外的所有已注册 Agent
```

## 数据模型

```python
class Message:
    id: str
    sender: str
    recipient: Optional[str]   # P2P 模式
    topic: Optional[str]       # PubSub 模式
    payload: Any
    timestamp: datetime
    type: str = "data"         # data / event / command / error
```

## 核心接口

```python
class MessageBus:
    def register(name: str, agent: Any) -> None
    async def send(sender, recipient=None, topic=None,
                   payload=None, msg_type="data") -> Message
    async def receive(agent_name: str, limit: int = 100) -> list[Message]
    def subscribe(topic: str, handler: Callable) -> None
    async def broadcast(sender: str, payload) -> list[Message]
    def get_history(limit: int = 100) -> list[Message]
    def clear() -> None
```

## 设计约束

1. **异步优先**: 所有发送/接收均为 async，适配 Agent 的异步执行模型
2. **内存存储**: 当前为内存实现，重启后丢失（未来可对接 Redis/RabbitMQ）
3. **历史裁剪**: 超过 1000 条消息后自动裁剪到 500 条
4. **发送者不自收**: Broadcast 排除发送者自身
