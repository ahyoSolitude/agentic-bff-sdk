# 渠道适配、插件与 SDK 工厂

> 对应模块：`channels.py`、`sdk.py`

## ChannelAdapter

不同渠道的请求和响应格式不同，`ChannelAdapter` 负责 SDK 边界转换。

```python
class ChannelAdapter(ABC):
    async def adapt_inbound(self, payload: object) -> GatewayRequest: ...

    async def adapt_outbound(
        self,
        response: ResponseEnvelope,
    ) -> object:
        ...

    def get_capabilities(self) -> ChannelCapabilities: ...
```

## ChannelCapabilities

渠道能力必须强类型声明，而不是塞在松散 `metadata` 中。

```python
class ChannelCapabilities(BaseModel):
    supports_markdown: bool = True
    supports_table_card: bool = True
    supports_chart_card: bool = False
    supports_action_card: bool = True
    max_card_count: int = 5
    schema_version: str = "1.0"
```

`ResponseEngine` 根据能力做卡片降级。

## 插件注册

新方案建议插件注册围绕稳定扩展点：

- `Router`
- `Planner`
- `SOPCompiler`
- `DomainGateway`
- `TaskPackage`
- `AgentExecutorFactory`
- `RuleEngineClient`
- `ResponseEngine`
- `ChannelAdapter`
- `EventSubscriber`

不建议继续以 `generator` 作为单独插件类型，因为卡片生成已收敛到 `response.py`。

## SDK 工厂

`create_sdk` 是一站式装配入口：

```python
def create_sdk(
    config: SDKConfig | str | Path,
    *,
    router: Router | None = None,
    planner: Planner | None = None,
    sop_compiler: SOPCompiler | None = None,
    domain_gateway: DomainGateway | None = None,
    response_engine: ResponseEngine | None = None,
    task_manager: TaskManager | None = None,
    channel_adapters: dict[str, ChannelAdapter] | None = None,
) -> AgenticBFFSDK:
    ...
```

装配原则：

- 显式参数优先
- 配置驱动其次
- 默认实现兜底
- 工厂负责类路径解析，配置模型不执行动态导入

## 典型使用

```python
sdk = create_sdk(
    "config.yaml",
    router=my_router,
    planner=my_planner,
    response_engine=my_response_engine,
)

sdk.register_task_package(FundTaskPackage())

response = await sdk.handle_request(
    GatewayRequest(
        user_input="查询客户基金持仓",
        session_id="s_001",
        channel_id="web",
    )
)
```

## 多实例

`create_sdk` 应返回独立实例，允许同一进程创建多个租户、渠道或测试实例。
