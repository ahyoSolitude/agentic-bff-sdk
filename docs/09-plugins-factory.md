# 插件系统与渠道适配

> 对应源码：`agentic_bff_sdk/plugins.py`、`agentic_bff_sdk/sdk.py`

## ChannelAdapter — 渠道适配器

### 设计思路

不同渠道（Web、App、微信、电话）的请求/响应格式各不相同。ChannelAdapter 在 SDK 边界做格式转换，使核心编排逻辑完全不感知渠道差异。

### 核心接口

```python
class ChannelAdapter(ABC):
    async def adapt_request(self, request: Any) -> RequestMessage
    async def adapt_response(self, response: Any) -> Any
```

### DefaultChannelAdapter

直通适配器，适用于已经使用 SDK 格式的渠道：
- 输入是 `RequestMessage` → 直接返回
- 输入是 `dict` → 构造 `RequestMessage(**dict)`
- 其他类型 → 抛出 `TypeError`

### 自定义示例

```python
class WeChatAdapter(ChannelAdapter):
    async def adapt_request(self, request):
        return RequestMessage(
            user_input=request["Content"],
            session_id=request["FromUserName"],
            channel_id="wechat",
        )

    async def adapt_response(self, response):
        return {"MsgType": "text", "Content": response.content}
```

---

## PluginRegistry — 插件注册中心

### 设计思路

PluginRegistry 是 SDK 的扩展入口，支持注册 6 种类型的插件：

| 类型 | 存储方式 | 说明 |
|------|---------|------|
| `router` | 单例 | 自定义 TopLevelRouter |
| `executor` | 单例 | 自定义 AgentExecutor |
| `generator` | 单例 | 自定义 CardGenerator |
| `channel_adapter` | 按 channel_id 存储 | 渠道适配器 |
| `tool` | 列表 | LangChain BaseTool |
| `chain` | 列表 | LangChain Chain/Runnable |

### 使用方式

```python
registry = PluginRegistry()
registry.register_router(my_router)
registry.register_tool(my_tool)
registry.register_channel_adapter("wechat", WeChatAdapter())

# 或使用通用接口
registry.register("tool", another_tool)
registry.register("channel_adapter", adapter, channel_id="app")
```

### 类型安全

所有注册方法都做类型检查，传入错误类型会抛出 `TypeError`。

---

## create_sdk — 工厂函数

### 设计思路

`create_sdk` 是 SDK 的一站式组装入口。它接收配置（OrchestrationConfig 或文件路径）和必要的组件实例，自动完成所有组件的创建和连接。

### 签名

```python
def create_sdk(
    config: OrchestrationConfig | str | Path,
    *,
    router: Optional[TopLevelRouter] = None,
    planner: Optional[IMCPlanner] = None,
    synthesizer: Optional[Synthesizer] = None,
    card_generator: Optional[CardGenerator] = None,
    domain_gateway: Optional[DomainGateway] = None,
    plugin_registry: Optional[PluginRegistry] = None,
    domain_invoker: Optional[Callable] = None,
) -> DefaultMASGateway
```

### 组件解析优先级

```
显式参数 > PluginRegistry 中注册的 > 默认实现
```

- `router`：必须提供（直接传入或通过 registry）
- `planner`：必须提供
- `synthesizer`：必须提供
- `card_generator`：可选，默认 DefaultCardGenerator
- 其他基础组件（SessionContext、Dispatcher、Aggregator）自动创建

### 从文件加载

```python
gateway = create_sdk(
    "config.yaml",  # 自动识别 .yaml/.yml/.json
    router=my_router,
    planner=my_planner,
    synthesizer=my_synthesizer,
)
```

### 扩展方向

- **自动发现插件**：扫描 entry_points 自动注册插件
- **配置驱动组件选择**：在 YAML 中指定组件类名，工厂自动实例化
- **多实例支持**：create_sdk 返回的 gateway 是独立实例，可创建多个
