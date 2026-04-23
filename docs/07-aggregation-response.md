# 结果聚合与响应生成

> 对应模块：`aggregation.py`、`response.py`

## Aggregator

`Aggregator` 将多个步骤结果汇总为 `AggregatedResult`，为响应决策提供结构化输入。

```python
class Aggregator(ABC):
    async def aggregate(
        self,
        plan: ExecutionPlan,
        results: list[StepResult],
    ) -> AggregatedResult:
        ...
```

聚合逻辑：

- 识别缺失步骤
- 识别失败步骤
- 标记 `is_partial`
- 保留必要结构化输出

失败或超时步骤如果有 `StepResult`，不算 missing；完全没有结果的步骤才算 missing。

## ResponseEngine

`response.py` 收敛原先分散的 `DecisionEngine`、`Synthesizer`、`CardGenerator`，对外暴露统一入口：

```python
class ResponseEngine(ABC):
    async def compose(
        self,
        aggregated: AggregatedResult,
        context: ExecutionContext,
        capabilities: ChannelCapabilities,
    ) -> ResponseEnvelope:
        ...
```

内部顺序：

1. `DecisionEngine.decide()`
2. `Synthesizer.synthesize()`
3. `CardGenerator.generate()`

## DecisionEngine

职责：

- 判断是否可直接答复
- 判断是否需要用户确认
- 判断是否部分结果
- 输出合规标记
- 生成结构化业务决策

```python
class DecisionOutcome(BaseModel):
    status: DecisionStatus
    summary: str
    structured_payload: dict[str, object] = Field(default_factory=dict)
    confirmation_actions: list[ConfirmationAction] = Field(default_factory=list)
    compliance_flags: list[str] = Field(default_factory=list)
```

## Synthesizer

职责：

- 将结构化决策转成自然语言
- 结合会话上下文组织表述
- 必要时进行有限重试

它不负责业务决策，只负责表达。

## CardGenerator

职责：

- 根据综合结果和 `ChannelCapabilities` 生成卡片
- 不支持的卡片类型自动降级
- 确认动作生成确认卡片

最终输出统一为 `ResponseEnvelope`。

## 渠道降级

如果渠道只支持文本，`ResponseEngine` 应保留 `text`，过滤或合并卡片内容到文本中。
