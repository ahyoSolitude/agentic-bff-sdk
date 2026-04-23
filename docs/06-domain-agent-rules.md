# 领域网关、Agent 执行与规则引擎

> 对应模块：`domain.py`、`agent_executor.py`、`rules.py`

## 领域执行链路

```text
Dispatcher
  -> DomainGateway
  -> AgentExecutorFactory
  -> AgentExecutor
  -> TaskPackage tools / RuleEngineClient
```

`DomainGateway` 不直接吞并领域执行语义，而是负责路由和协议转换；真正执行由 `AgentExecutor` 完成。

## DomainGateway

```python
class DomainGateway(ABC):
    def register_task_package(self, package: TaskPackage) -> None: ...

    async def invoke(
        self,
        command: DomainCommand,
        context: ExecutionContext,
    ) -> DomainResult:
        ...
```

职责：

- 按 `domain` 查找 `TaskPackage`
- 构造或获取对应 `AgentExecutor`
- 处理未注册领域
- 记录领域调用摘要
- 返回标准 `DomainResult`

## TaskPackage

```python
class TaskPackage(Protocol):
    name: str
    domain: str

    def get_tools(self) -> list[ToolSpec]: ...
    def get_executor_config(self) -> AgentExecutorConfig: ...
```

`TaskPackage` 是领域能力包，提供工具、配置和元数据，不要求直接暴露统一 `execute()`。

## AgentExecutor

```python
class AgentExecutor(ABC):
    async def execute(
        self,
        command: DomainCommand,
        context: ExecutionContext,
    ) -> DomainResult:
        ...
```

职责：

- ReAct 推理
- 工具调用
- 工具输入校验
- Blackboard 读写
- 规则引擎调用
- 最大推理步数控制

`ToolRegistry` 和 `ToolInputValidator` 作为 `agent_executor.py` 内部组件。

## RuleEngineClient

```python
class RuleEngineClient(ABC):
    async def get_rule_metadata(self, rule_set_id: str) -> RuleMetadata: ...

    async def evaluate(
        self,
        request: RuleEvaluationRequest,
    ) -> RuleEvaluationResult:
        ...
```

规则引擎设计要求：

- 元数据缓存与执行结果缓存分离
- 元数据缓存默认开启
- 结果缓存默认关闭
- 如果开启结果缓存，key 必须包含 `rule_set_id + version + params_hash`

`RuleMetadataCache` 和 `RuleResultCache` 是 `rules.py` 内部组件。

## 错误边界

- 未注册领域：返回 `DOMAIN_UNAVAILABLE`
- 工具输入非法：返回可诊断错误
- 规则引擎超时：按配置降级或抛出 `RuleEngineError`
- Agent 超出最大步数：返回当前中间结果或失败结果
