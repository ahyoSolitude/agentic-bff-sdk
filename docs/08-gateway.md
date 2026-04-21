# MAS Gateway 与异步任务

> 对应源码：`agentic_bff_sdk/gateway.py`

## 设计思路

MASGateway 是整个 SDK 的**全局入口**，负责将所有组件串联成完整的请求处理管线。它同时管理异步任务队列，支持长时间运行的任务异步执行。

## 核心接口

```python
class MASGateway(ABC):
    async def handle_request(self, request: RequestMessage) -> ResponseMessage
    async def submit_async_task(self, request, priority=0) -> str  # 返回 task_id
    async def get_task_status(self, task_id) -> TaskStatus
    def register_plugin(self, plugin_type, plugin) -> None
```

## 同步管线

`handle_request` 的完整处理流程：

```
1. 请求验证
   └─ session_id 为空？→ REQ_MISSING_SESSION_ID
   └─ channel_id 为空？→ REQ_MISSING_CHANNEL_ID

2. 会话恢复
   └─ SessionContext.get_or_create(session_id)
   └─ 更新 last_active_at

3. 意图路由
   └─ TopLevelRouter.route(user_input, session_state)
   └─ 返回 ClarificationQuestion？→ 直接返回给用户

4. 执行计划生成
   └─ IMCPlanner.generate_plan(intent, session_state)

5. DAG 并发调度
   └─ ConcurrentDispatcher.dispatch(plan, domain_invoker)

6. 结果聚合
   └─ FanInAggregator.aggregate(step_results, expected_steps)

7. 综合决策
   └─ Synthesizer.synthesize(aggregated, session_state)

8. 卡片生成
   └─ CardGenerator.generate(synthesis, channel_capabilities)

9. 会话保存
   └─ 追加对话历史（user + assistant）
   └─ SessionContext.save()

10. 返回 ResponseMessage
```

任何步骤抛出异常都会被捕获，返回 `SYS_INTERNAL_ERROR`。

## 异步任务管理

### 提交任务

```python
task_id = await gateway.submit_async_task(request, priority=0)
# priority 越小优先级越高
```

内部使用 `asyncio.PriorityQueue`，按 `(priority, enqueue_time, task_id)` 排序。

### 查询状态

```python
status = await gateway.get_task_status(task_id)  # PENDING / RUNNING / COMPLETED / FAILED
result = await gateway.get_task_result(task_id)   # 完成后获取 ResponseMessage
```

### 失败重试

```python
success = await gateway.retry_task(task_id)  # 仅 FAILED 状态可重试
```

### 回调通知

配置 `SDKConfig.async_task_callback_url` 后，任务完成/失败时自动发送 webhook 通知：

```json
{"task_id": "xxx", "status": "completed", "error": null}
```

## 会话清理

```python
cleaned_ids = await gateway.cleanup_idle_sessions()
# 清理 last_active_at 超过 session_idle_timeout_seconds 的会话
```

## 扩展方向

- **中间件链**：在管线步骤之间插入中间件（日志、限流、鉴权）
- **分布式任务队列**：将 asyncio.PriorityQueue 替换为 Celery/RQ
- **管线可配置**：通过配置跳过某些步骤（如不需要卡片生成的 API 场景）
- **健康检查**：暴露 `/health` 端点，报告各组件状态
