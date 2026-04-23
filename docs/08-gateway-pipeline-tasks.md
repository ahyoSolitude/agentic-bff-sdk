# Gateway、Pipeline 与异步任务

> 对应模块：`gateway.py`、`pipeline.py`、`tasks.py`

## MASGateway

`MASGateway` 是 SDK 对外入口，但不再承担完整编排细节。

```python
class MASGateway(ABC):
    async def handle_request(self, request: GatewayRequest) -> GatewayResponse: ...

    async def submit_task(
        self,
        request: GatewayRequest,
        *,
        priority: int = 0,
    ) -> str:
        ...

    async def get_task(self, task_id: str) -> TaskStateSnapshot: ...
```

职责：

- 请求参数校验
- 同步请求转发给 `RequestPipeline`
- 异步请求转发给 `TaskManager`
- 渠道适配装配
- 错误映射

## RequestPipeline

`RequestPipeline` 负责单次请求编排：

```python
class RequestPipeline(ABC):
    async def run(self, request: GatewayRequest) -> GatewayResponse:
        ...
```

主流程：

1. 创建 `RequestContext`
2. 加载或创建 `SessionState`
3. 发布 `REQUEST_ACCEPTED`
4. `Router.resolve()`
5. `Planner.plan()` 或 `SOPCompiler.compile()`
6. `Dispatcher.dispatch()`
7. `Aggregator.aggregate()`
8. `ResponseEngine.compose()`
9. 保存会话
10. 返回 `GatewayResponse`

## TaskManager

`TaskManager` 管理长任务：

```python
class TaskManager(ABC):
    async def submit(self, request: GatewayRequest, *, priority: int = 0) -> str: ...
    async def get_snapshot(self, task_id: str) -> TaskStateSnapshot: ...
    async def retry(self, task_id: str) -> bool: ...
```

职责：

- 任务入队
- 优先级管理
- 后台执行 `RequestPipeline`
- 状态快照维护
- 失败重试
- 回调通知

`CallbackNotifier` 是 `tasks.py` 内部组件，不作为顶层模块。

## 异步任务状态机

```text
PENDING -> RUNNING -> COMPLETED
PENDING -> RUNNING -> FAILED
FAILED -> PENDING -> RUNNING
RUNNING -> CANCELLED
```

## 与事件系统的关系

`TaskManager` 订阅或消费 `ExecutionEvent` 来更新任务快照，并通过回调通知调用方。

## 错误策略

- 请求校验错误：直接返回 `INVALID_REQUEST`
- Pipeline 内部错误：转成标准 `ErrorResponse`
- 异步任务失败：保存失败原因，支持手动重试
