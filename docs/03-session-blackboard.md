# 会话、Blackboard 与状态作用域

> 对应模块：`session.py`、`blackboard.py`

## 状态作用域

新方案明确区分三类状态：

- `session scope`: 跨多轮对话保留，包含历史、摘要、话题、用户画像
- `request/task scope`: 单次请求或异步任务上下文
- `step scope`: 单个执行步骤的输入、输出和临时产物

这能避免异步任务和并发执行时出现状态污染。

## SessionManager

`SessionManager` 负责会话生命周期：

```python
class SessionManager(ABC):
    async def get_or_create(self, session_id: str) -> SessionState: ...
    async def save(self, state: SessionState) -> None: ...
    async def cleanup_expired(self) -> list[str]: ...
```

内部可以包含：

- `TopicManager`: 话题创建、切换、关闭
- `DialogCompressor`: 历史压缩策略
- `SessionStore`: 持久化后端

这些是 `session.py` 内部策略对象，不单独作为顶层模块。

## SessionStore

```python
class SessionStore(ABC):
    async def load(self, session_id: str) -> SessionState | None: ...
    async def save(self, state: SessionState) -> None: ...
    async def delete(self, session_id: str) -> None: ...
```

默认实现可以是内存存储，生产环境建议实现 Redis 或数据库后端。

## 话题管理规则

话题管理维护一个不变量：

> 同一会话中任何时刻最多只有一个 active topic。

关闭的话题不可重新激活，只能创建新话题或切换到未关闭话题。

## Blackboard

Blackboard 是执行期共享状态，默认 request/task 级隔离。

```python
class Blackboard(ABC):
    async def get(self, key: str) -> BlackboardEntry | None: ...
    async def set(self, entry: BlackboardEntry) -> None: ...
    async def delete(self, key: str) -> bool: ...
    async def cleanup_expired(self) -> list[str]: ...
```

典型用途：

- 前置步骤结果传递给后置步骤
- Agent 中间推理结果共享
- 规则引擎输出写入执行上下文

## 设计边界

- `SessionState` 不保存大量临时执行数据
- `Blackboard` 不作为长期记忆存储
- 异步任务状态由 `TaskManager` 管理，不写入 Session

## 测试重点

- 会话保存/加载 round-trip
- 话题 active 唯一性
- 历史压缩长度边界
- Blackboard TTL 清理
- 并发 set/get 一致性
