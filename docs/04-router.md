# 意图路由

> 对应模块：`router.py`

## 职责

`Router` 是请求进入编排层后的第一个决策点，负责判断用户输入应该进入哪条链路：

- 明确意图：进入 `Planner`
- SOP 意图：进入 `SOPCompiler`
- 歧义意图：返回澄清问题
- 无法识别：进入 fallback

## 核心接口

```python
class Router(ABC):
    async def resolve(
        self,
        request: RequestContext,
        session: SessionState,
    ) -> RoutingResult:
        ...
```

`RoutingResult` 可以表达：

- `ResolvedIntent`
- `ClarificationPrompt`
- `FallbackRoute`

## 决策链

```text
用户输入
  -> 优先规则匹配
  -> LLM / 自定义 recognizer 识别
  -> 歧义检测
  -> 置信度阈值判断
  -> fallback
```

## 优先规则

优先规则适合确定性场景，例如关键词、正则、固定按钮触发的意图。

规则命中后可跳过 LLM，直接返回置信度为 1.0 的意图结果。

## 澄清机制

当出现以下情况时返回澄清问题：

- 最高置信度低于阈值
- 前两个候选意图差距过小
- 缺少执行计划所需关键参数

澄清响应由 `ResponseEngine` 生成自然语言和确认卡片。

## 与 Planner 的关系

`Router` 不生成执行步骤，只产出路由结果。执行步骤统一由：

- `Planner.plan()`
- `SOPCompiler.compile()`

生成 `ExecutionPlan`。

## 扩展点

- 规则优先路由
- LLM 意图识别
- 多模型投票
- 意图缓存
- 完全自定义 Router
