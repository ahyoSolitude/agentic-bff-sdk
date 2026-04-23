# 错误、事件与审计

> 对应模块：`errors.py`、`events.py`

## 错误体系

SDK 对外只暴露稳定错误码和 `ErrorResponse`，不直接泄露第三方异常。

```python
class ErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, object] = Field(default_factory=dict)
```

建议错误码分类：

- `INVALID_REQUEST`
- `SESSION_NOT_FOUND`
- `INTENT_NOT_RECOGNIZED`
- `PLAN_VALIDATION_FAILED`
- `DOMAIN_UNAVAILABLE`
- `RULE_ENGINE_ERROR`
- `INTERNAL_ERROR`

## 异常层次

```python
class SDKError(Exception): ...
class ValidationError(SDKError): ...
class RoutingError(SDKError): ...
class PlanningError(SDKError): ...
class DispatchError(SDKError): ...
class DomainExecutionError(SDKError): ...
class RuleEngineError(SDKError): ...
```

网关层负责将内部异常映射为 `ErrorResponse`。

## 事件模型

`ExecutionEvent` 是同步流式输出、异步任务通知、审计日志和调试追踪的统一协议。

```python
class ExecutionEvent(BaseModel):
    event_id: str
    event_type: EventType
    request_id: str
    task_id: str | None = None
    session_id: str
    step_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: float
```

常见事件：

- `REQUEST_ACCEPTED`
- `PLAN_CREATED`
- `STEP_STARTED`
- `STEP_OUTPUT`
- `STEP_COMPLETED`
- `STEP_FAILED`
- `TASK_STATUS_CHANGED`
- `RESPONSE_READY`

## 事件发布与订阅

```python
class EventPublisher(ABC):
    async def publish(self, event: ExecutionEvent) -> None: ...


class EventSubscriber(ABC):
    async def handle(self, event: ExecutionEvent) -> None: ...
```

订阅器失败不应阻断主流程，应记录错误并继续。

## 审计设计

审计不再只绑定 `DomainGateway`，而是可以订阅事件流：

- 领域调用审计：订阅 `STEP_STARTED / STEP_COMPLETED / STEP_FAILED`
- 任务审计：订阅 `TASK_STATUS_CHANGED`
- 响应审计：订阅 `RESPONSE_READY`

审计日志建议包含：

- `request_id`
- `task_id`
- `session_id`
- `channel_id`
- `plan_id`
- `step_id`
- `domain`
- `event_type`
- `duration_ms`

## 可观测性

建议指标：

- 请求量
- 成功率
- 计划生成耗时
- 步骤执行耗时
- 规则引擎超时数
- 异步任务积压数
- 卡片降级次数
