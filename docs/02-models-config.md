# 数据模型与配置

> 对应模块：`models.py`、`config.py`

## 设计目标

所有对外协议和跨模块数据流都使用 Pydantic 模型表达，保证：

- 构造时校验
- JSON 序列化稳定
- IDE 类型提示明确
- 前端可基于 schema 验证卡片输出

所有可变默认值使用 `Field(default_factory=...)`，所有状态值使用 `str, Enum`。

## 核心请求响应模型

```python
class GatewayRequest(BaseModel):
    user_input: str
    session_id: str
    channel_id: str
    metadata: dict[str, object] = Field(default_factory=dict)
    trace_id: str | None = None


class GatewayResponse(BaseModel):
    session_id: str
    request_id: str
    content: ResponseEnvelope | None = None
    error: ErrorResponse | None = None
    task_id: str | None = None
    is_async: bool = False
```

## 执行上下文模型

```python
class RequestContext(BaseModel):
    request_id: str
    session_id: str
    channel_id: str
    user_input: str
    metadata: dict[str, object] = Field(default_factory=dict)


class ExecutionContext(BaseModel):
    request: RequestContext
    session: SessionState
    blackboard_keys: list[str] = Field(default_factory=list)
```

## 执行计划模型

`ExecutionPlan` 是新方案的统一执行 IR。LLM 规划和 SOP 模板最终都编译为该模型。

```python
class PlanSource(str, Enum):
    INTENT = "intent"
    SOP = "sop"


class StepKind(str, Enum):
    DOMAIN_CALL = "domain_call"
    RULE_EVAL = "rule_eval"
    REACT_AGENT = "react_agent"
    HUMAN_CONFIRM = "human_confirm"
    KNOWLEDGE_QUERY = "knowledge_query"


class ExecutionStep(BaseModel):
    step_id: str
    kind: StepKind
    domain: str | None = None
    action: str | None = None
    description: str
    dependencies: list[str] = Field(default_factory=list)
    timeout_seconds: float | None = None
    retryable: bool = True
    optional: bool = False


class ExecutionPlan(BaseModel):
    plan_id: str
    source: PlanSource
    intent_name: str
    steps: list[ExecutionStep]
    metadata: dict[str, str] = Field(default_factory=dict)
```

计划必须满足：

- `step_id` 唯一
- 依赖引用存在
- 无循环依赖
- `kind/domain/action` 组合合法

## 响应模型

```python
class ResponseEnvelope(BaseModel):
    text: str
    cards: list[Card] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
```

`ResponseEnvelope` 是渠道无关响应，渠道适配器负责把它转换成 Web、App、IM、电话等目标格式。

## 配置模型

配置建议分层：

```python
class RuntimeConfig(BaseModel):
    session_idle_timeout_seconds: int = 1800
    plan_generation_timeout_seconds: float = 30.0
    step_execution_timeout_seconds: float = 60.0
    fan_in_wait_timeout_seconds: float = 30.0
    max_cross_llm_loops: int = 2


class RuleEngineConfig(BaseModel):
    base_url: str | None = None
    timeout_seconds: float = 10.0
    metadata_cache_ttl_seconds: int = 300
    result_cache_enabled: bool = False


class SDKConfig(BaseModel):
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    rule_engine: RuleEngineConfig = Field(default_factory=RuleEngineConfig)
    channels: list[ChannelConfig] = Field(default_factory=list)
    domains: list[DomainConfig] = Field(default_factory=list)
```

## 文档与代码同步要求

如果新增公共模型，需要同步更新：

- `models.py`
- `__init__.py`
- 对应单元测试
- 本文档
