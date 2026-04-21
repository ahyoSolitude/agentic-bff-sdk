# 领域网关与 Agent 执行

> 对应源码：`agentic_bff_sdk/domain_gateway.py`、`agentic_bff_sdk/agent_executor.py`

## DomainGateway — 领域网关

### 设计思路

DomainGateway 是上层编排与下层业务微服务之间的桥梁。它提供统一的 `invoke` 接口，内部根据 `domain` 标识路由到对应的 TaskPackage，完成协议转换（SDK 内部格式 → 微服务格式）。

### 核心接口

```python
class DomainGateway(ABC):
    async def invoke(self, request: DomainRequest) -> DomainResponse
    def register_task_package(self, domain: str, task_package: TaskPackage) -> None
    async def invoke_rule_engine(self, rule_set_id: str, params: Dict) -> Any

# TaskPackage 是一个 Protocol（鸭子类型）
class TaskPackage(Protocol):
    async def execute(self, action: str, parameters: Dict[str, Any]) -> Any
```

### DefaultDomainGateway 实现要点

| 能力 | 实现方式 |
|------|---------|
| 领域路由 | `_task_packages` dict，按 domain key 查找 |
| 协议转换 | 将 DomainRequest 拆解为 `(action, parameters)` 传给 TaskPackage.execute |
| 降级处理 | 未注册的 domain 返回 error DomainResponse |
| 审计日志 | 每次 invoke 通过 Python logging 记录 AUDIT 日志 |
| 规则引擎 | 通过 httpx 异步 HTTP 调用，支持 TTL 缓存 |

### 规则引擎缓存

```python
# 缓存结构：rule_set_id -> (result, timestamp)
_rule_cache: Dict[str, Tuple[Any, float]]

# 查询时：若 time.time() - cached_at < ttl，直接返回缓存
# 否则发起 HTTP 调用并更新缓存
```

### 扩展方向

- **gRPC 支持**：TaskPackage 内部可以用 gRPC 调用微服务
- **服务发现**：集成 Consul/Nacos，动态注册 TaskPackage
- **熔断器**：在 invoke 中添加 circuit breaker 逻辑
- **链路追踪**：在 DomainRequest 中传递 trace_id

---

## AgentExecutor — 执行代理

### 设计思路

AgentExecutor 基于 ReAct（Reasoning + Acting）模式，交替进行 LLM 推理和工具调用。每个领域任务由专属的 Agent 处理，领域逻辑通过注册的工具集封装。

### 核心接口

```python
class AgentExecutor(ABC):
    async def execute(self, action, parameters, blackboard, config) -> Any
    def register_tool(self, tool: BaseTool) -> None

# 工具输入验证（独立函数）
def validate_tool_input(tool_name, input_params, input_schema) -> None

# 规则引擎降级（独立函数）
async def handle_rule_engine_call(callable, rule_set_id, params, fallback_value=None) -> Any
```

### DefaultAgentExecutor 实现要点

| 能力 | 实现方式 |
|------|---------|
| 工具注册 | `register_tool` 添加到内部列表 |
| 输入验证 | 使用 jsonschema 库校验工具参数 |
| 推理步数限制 | `config.max_reasoning_steps` 控制循环上限 |
| Blackboard 上下文 | 执行前提取 Blackboard 快照传给 LLM |
| 工具错误反馈 | 工具调用失败时将错误信息反馈给 LLM 决策 |
| 可注入推理循环 | `reasoning_loop` 参数，方便测试和自定义 |

### 规则引擎降级策略

```python
result = await handle_rule_engine_call(
    rule_engine_callable,
    rule_set_id="risk_calc",
    params={"user_id": "u1"},
    fallback_value={"risk_score": 50},  # 超时/错误时返回此值
)
# 若 fallback_value=None 且调用失败，抛出 RuntimeError
```

### 扩展方向

- **LangChain create_react_agent**：将默认推理循环替换为 LangChain 原生 ReAct Agent
- **工具市场**：从配置文件动态加载工具定义
- **沙箱执行**：在隔离环境中执行工具调用，防止副作用
