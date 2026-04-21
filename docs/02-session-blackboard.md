# 会话与状态管理

> 对应源码：`agentic_bff_sdk/session.py`、`agentic_bff_sdk/blackboard.py`

## Blackboard — 共享状态存储

### 设计思路

Blackboard（黑板模式）是多智能体协作的经典模式：多个 Agent 在同一个共享空间中读写中间结果，无需直接通信。SDK 的 Blackboard 是一个**异步线程安全的键值存储**，使用 `asyncio.Lock` 保证并发安全。

### 核心接口

```python
class Blackboard:
    async def get(self, key: str) -> Optional[Any]        # 读取，更新访问时间
    async def set(self, key: str, value: Any) -> None      # 写入
    async def delete(self, key: str) -> bool               # 删除
    async def cleanup_expired(self, ttl_seconds: int) -> List[str]  # TTL 过期清理
```

### 实现要点

- **访问时间追踪**：每次 `get` 和 `set` 都更新 `_access_times[key]`，`cleanup_expired` 据此判断过期
- **线程安全**：所有操作在 `async with self._lock` 内执行
- **值类型无限制**：value 可以是任意 Python 对象（str、int、dict、list 等）

### 典型用法

```python
bb = Blackboard()
await bb.set("user_profile", {"name": "张三", "risk_level": "moderate"})
await bb.set("step_1_result", {"nav": 1.258})

# 其他 Agent 读取前序步骤的结果
profile = await bb.get("user_profile")
nav_data = await bb.get("step_1_result")

# 定期清理过期数据
expired = await bb.cleanup_expired(ttl_seconds=3600)
```

### 扩展方向

- 替换为 Redis 后端：实现一个 `RedisBlackboard`，接口不变，底层用 aioredis
- 添加命名空间：按 session_id 隔离不同会话的 Blackboard 数据
- 添加事件通知：key 变更时触发回调，实现响应式数据流

---

## SessionContext — 会话管理

### 设计思路

SessionContext 管理会话的完整生命周期：创建、恢复、持久化、过期清理。通过可插拔的 `StorageBackend` 抽象，支持从内存到 Redis/数据库的无缝切换。

### 核心接口

```python
class StorageBackend(ABC):
    async def save(self, session_id: str, state: SessionState) -> None
    async def load(self, session_id: str) -> Optional[SessionState]
    async def delete(self, session_id: str) -> None

class SessionContext:
    async def get_or_create(self, session_id: str) -> SessionState
    async def save(self, session_id: str, state: SessionState) -> None
    async def cleanup_expired(self, idle_timeout_seconds: int) -> List[str]
    def create_topic(self, state, name, metadata=None) -> Topic
    def switch_topic(self, state, topic_id) -> bool
    def close_topic(self, state, topic_id) -> bool
    def compress_dialog_history(self, state) -> None
```

### 话题管理

话题管理维护一个关键不变量：**任何时刻最多只有一个 active 话题**。

- `create_topic`：创建新话题（active），自动将其他话题设为 suspended
- `switch_topic`：切换到指定话题，其余设为 suspended，已 closed 的不可切换
- `close_topic`：将话题标记为 closed

### 对话历史压缩

当 `len(dialog_history) > max_dialog_history_turns` 时：

1. 保留最近的 `max_turns - 1` 条记录
2. 将更早的记录摘要为一条 `role=system` 的摘要条目
3. 压缩后总长度 ≤ `max_dialog_history_turns`

### 扩展方向

- **Redis StorageBackend**：实现 `RedisStorageBackend`，用 JSON 序列化 SessionState
- **LLM 摘要压缩**：当前压缩是简单拼接，可替换为调用 LLM 生成真正的摘要
- **会话迁移**：支持跨节点的会话状态迁移（分布式场景）
