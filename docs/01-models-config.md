# 核心数据模型与配置

> 对应源码：`agentic_bff_sdk/models.py`、`agentic_bff_sdk/config.py`

## 设计思路

SDK 的所有数据流转都通过 Pydantic BaseModel 定义的强类型模型完成。这带来三个好处：

1. **运行时类型验证**：构造时自动校验字段类型，错误立即暴露
2. **序列化一致性**：`model_dump_json()` / `model_validate_json()` 保证 round-trip 正确
3. **JSON Schema 自动生成**：CardOutput 的输出格式可直接导出 Schema 供前端校验

所有枚举继承 `str, Enum`，确保 JSON 序列化时输出字符串值而非枚举名。

## 数据模型一览

### 枚举类型

| 枚举 | 值 | 用途 |
|------|-----|------|
| `TaskStatus` | pending / running / completed / failed | 异步任务状态 |
| `RouterMode` | generate / confirm | 意图路由模式 |
| `StepStatus` | pending / running / completed / failed / timeout | 步骤执行状态 |
| `CardType` | text / table / chart / action_button / confirmation | 富媒体卡片类型 |

### 请求/响应模型

| 模型 | 关键字段 | 说明 |
|------|---------|------|
| `RequestMessage` | user_input, session_id, channel_id, metadata | 统一请求入口 |
| `ResponseMessage` | session_id, content, task_id, is_async, error | 统一响应出口 |
| `ErrorResponse` | code, message, details | 标准错误格式 |

### 会话模型

| 模型 | 关键字段 | 说明 |
|------|---------|------|
| `Topic` | topic_id, name, status, created_at, metadata | 会话话题 |
| `SessionState` | session_id, dialog_history, user_profile_summary, active_topics | 会话全状态 |

### 意图模型

| 模型 | 关键字段 | 说明 |
|------|---------|------|
| `IntentResult` | intent_type, confidence, parameters | 意图识别结果 |
| `ClarificationQuestion` | question, candidates | 澄清问题（含候选意图列表） |

### 执行计划模型

| 模型 | 关键字段 | 说明 |
|------|---------|------|
| `PlanStep` | step_id, domain, action, parameters, dependencies, is_react_node | 单个执行步骤 |
| `ExecutionPlan` | plan_id, intent, steps, created_at, timeout_seconds | 完整执行计划 |

### 领域调用模型

| 模型 | 关键字段 | 说明 |
|------|---------|------|
| `DomainRequest` | domain, action, parameters, request_id | 领域调用请求 |
| `DomainResponse` | request_id, domain, success, data, error | 领域调用响应 |
| `StepResult` | step_id, status, result, error, duration_ms | 步骤执行结果 |

### 聚合/综合/卡片模型

| 模型 | 关键字段 | 说明 |
|------|---------|------|
| `AggregatedResult` | results, missing_steps, is_partial | 聚合结果 |
| `SynthesisResult` | text_response, structured_data, requires_confirmation, quality_score | 综合结果 |
| `Card` | card_type, title, content, actions | 单张卡片 |
| `CardOutput` | cards, raw_text | 卡片输出集合 |

## 配置体系

### SDKConfig — 全局配置

```python
class SDKConfig(BaseModel):
    # 会话管理
    session_idle_timeout_seconds: int = 1800      # 会话空闲超时（秒）
    max_dialog_history_turns: int = 50            # 对话历史最大轮次
    dialog_summary_threshold: int = 30            # 触发摘要压缩的阈值

    # 意图路由
    intent_confidence_threshold: float = 0.7      # 置信度阈值
    intent_ambiguity_range: float = 0.1           # 歧义判定范围

    # 执行控制
    plan_generation_timeout_seconds: float = 30.0 # 计划生成超时
    step_execution_timeout_seconds: float = 60.0  # 单步执行超时
    max_reasoning_steps: int = 10                 # Agent 最大推理步数
    fan_in_wait_timeout_seconds: float = 120.0    # 聚合等待超时

    # Blackboard
    blackboard_key_ttl_seconds: int = 3600        # 键值 TTL

    # 异步任务
    async_task_callback_url: Optional[str] = None # 回调地址
    async_task_callback_type: str = "webhook"     # webhook | mq

    # 综合决策
    synthesis_quality_threshold: float = 0.7      # 质量阈值
    max_cross_llm_loops: int = 3                  # 交叉 LLM 最大重试

    # 规则引擎
    rule_engine_base_url: Optional[str] = None    # 规则引擎地址
    rule_engine_timeout_seconds: float = 10.0     # 调用超时
    rule_engine_cache_ttl_seconds: int = 300      # 缓存 TTL
```

### OrchestrationConfig — 编排配置

顶层配置，聚合了 SDKConfig、渠道、任务包、优先规则和 SOP 定义。支持 YAML/JSON 序列化：

```python
config = OrchestrationConfig.from_file("config.yaml")  # 从文件加载
yaml_str = config.to_yaml()                              # 导出 YAML
config2 = OrchestrationConfig.from_yaml(yaml_str)        # round-trip
```

### 其他配置模型

| 模型 | 用途 |
|------|------|
| `ChannelAdapterConfig` | 渠道适配器配置（channel_id, capabilities, adapter_class） |
| `TaskPackageConfig` | 领域任务包配置（domain, base_url, protocol, tools） |
| `SOPDefinition` | SOP 定义（steps, exception_policies, dialog_templates） |
| `InteractionScene` | 交互场景枚举（phone / face_to_face / online） |
| `ToolDefinition` | 工具定义（name, description, input_schema） |
| `AgentExecutorConfig` | Agent 执行器配置（max_reasoning_steps, tools） |

## 扩展方向

- 添加新的数据模型时，继承 `BaseModel` 并在 `__init__.py` 中导出即可
- 需要自定义序列化逻辑时，可覆盖 Pydantic 的 `model_serializer` / `model_validator`
- OrchestrationConfig 可扩展新的顶层字段（如 `monitoring`, `rate_limiting`）
