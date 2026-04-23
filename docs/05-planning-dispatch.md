# 执行计划、SOP 编译与调度

> 对应模块：`planning.py`、`dispatch.py`

## 统一执行 IR

新方案将 LLM 规划和 SOP 模板统一收敛到 `ExecutionPlan`：

- `Planner`: 根据已解析意图生成计划
- `SOPCompiler`: 根据 SOP 定义编译计划
- `Dispatcher`: 只接收 `ExecutionPlan`，不关心计划来源

这样可以避免“动态规划”和“标准流程”各自维护独立执行语义。

## Planner

```python
class Planner(ABC):
    async def plan(
        self,
        intent: ResolvedIntent,
        context: RequestContext,
    ) -> ExecutionPlan:
        ...
```

`Planner` 适合开放式请求，例如查询、分析、跨领域组合任务。

## SOPCompiler

```python
class SOPCompiler(ABC):
    async def compile(
        self,
        sop_id: str,
        context: RequestContext,
    ) -> ExecutionPlan:
        ...
```

`SOPCompiler` 适合标准化流程，例如开户、KYC、清算、合规检查。它不直接执行 SOP，而是把 SOP 转换为 `ExecutionPlan`。

## PlanValidator

`PlanValidator` 是 `planning.py` 内部组件，用于校验：

- `step_id` 唯一
- 依赖引用存在
- 无循环依赖
- `kind/domain/action` 合法
- 必要参数绑定完整

## Dispatcher

```python
class Dispatcher(ABC):
    async def dispatch(
        self,
        plan: ExecutionPlan,
        context: ExecutionContext,
    ) -> list[StepResult]:
        ...
```

调度策略：

1. 校验 DAG
2. 找出依赖已完成的步骤
3. 并发执行 ready 步骤
4. 发布 `STEP_*` 事件
5. 处理失败、超时、可选步骤和依赖传播
6. 返回全部 `StepResult`

## 运行时适配

`dispatch.py` 内部可以包含多个运行时：

- `AsyncioRuntime`: 默认轻量实现
- `GraphRuntimeAdapter`: 可选 LangGraph 适配
- `StatusTracker`: 步骤状态跟踪

这些不单独拆成顶层模块。

## 状态转换

```text
PENDING -> RUNNING -> COMPLETED
PENDING -> RUNNING -> FAILED
PENDING -> RUNNING -> TIMEOUT
PENDING -> SKIPPED
```

依赖失败时：

- 必要步骤依赖失败：下游步骤 `SKIPPED` 或 `FAILED`
- 可选步骤失败：不阻断无依赖步骤继续执行

## 事件输出

Dispatcher 应发布：

- `STEP_STARTED`
- `STEP_OUTPUT`
- `STEP_COMPLETED`
- `STEP_FAILED`

这些事件可被异步任务、审计日志、流式响应订阅。
