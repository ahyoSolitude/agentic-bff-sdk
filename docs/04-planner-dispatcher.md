# 执行计划与并发调度

> 对应源码：`agentic_bff_sdk/planner.py`、`agentic_bff_sdk/dispatcher.py`

## IMCPlanner — 执行计划生成

### 设计思路

IMC（Intent-to-Multi-Call）Planner 的职责是将一个已确认的用户意图转化为一个**包含依赖关系的执行计划**。计划中的每个步骤指定了目标领域、调用动作和参数，步骤之间通过 `dependencies` 字段描述先后关系，形成一个 DAG。

### 核心接口

```python
class IMCPlanner(ABC):
    async def generate_plan(self, intent, session_state, timeout_seconds=None) -> ExecutionPlan
    async def persist_plan(self, plan) -> str  # 返回 plan_id
```

### DefaultIMCPlanner

| 参数 | 说明 |
|------|------|
| `llm` | LangChain LLM，用于 CoT 推理 |
| `config` | SDKConfig（超时等配置） |
| `plan_generator` | 可注入的自定义计划生成函数 |

**超时控制**：使用 `asyncio.wait_for` 包装，超时抛出 `asyncio.TimeoutError`。

**持久化**：默认存储在内存 dict 中，通过 `persist_plan` / `load_plan` 操作。可扩展为数据库持久化。

**ReAct 节点**：`PlanStep.is_react_node = True` 标记需要 ReAct 推理循环的步骤，供下游 AgentExecutor 识别。

### 扩展方向

- **注入 plan_generator**：最常见的扩展，用业务规则替代 LLM 生成计划
- **数据库持久化**：实现 `persist_plan` 写入 PostgreSQL/MongoDB
- **计划模板**：预定义常见意图的计划模板，LLM 只做参数填充

---

## ConcurrentDispatcher — DAG 并发调度

### 设计思路

Dispatcher 接收一个 ExecutionPlan，解析步骤间的依赖关系构建 DAG，然后**按拓扑序批量并发执行**：每一轮找出所有依赖已满足的步骤，用 `asyncio.wait` 并发执行，完成后进入下一轮。

### 核心接口

```python
class ConcurrentDispatcher:
    def validate_dag(self, plan) -> Optional[List[str]]  # 循环检测
    async def dispatch(self, plan, domain_invoker, blackboard=None,
                       step_timeout_seconds=30.0, callback=None) -> List[StepResult]
```

### DAG 循环检测

`validate_dag` 使用 DFS 三色标记法检测循环依赖：
- 返回 `None` 表示无循环
- 返回 `List[str]` 表示循环路径（如 `["a", "b", "c", "a"]`）

### 调度流程

```
while 还有待执行步骤:
    1. 标记被阻塞的步骤（依赖失败/超时）为 FAILED
    2. 找出所有依赖已完成的步骤（ready）
    3. 并发执行 ready 步骤（asyncio.wait）
    4. 收集结果，更新状态
```

### 步骤状态机

```
PENDING → RUNNING → COMPLETED
                  → FAILED
                  → TIMEOUT
PENDING → FAILED（依赖失败时直接跳过）
```

### StatusCallback

```python
class StatusCallback(ABC):
    async def on_status_change(self, step_id, old_status, new_status) -> None
```

每次状态变更都会通知回调，可用于实时进度展示、监控告警等。

### 超时处理

每个步骤用 `asyncio.wait_for(invoker(request), timeout=step_timeout_seconds)` 包装。超时步骤标记为 `TIMEOUT`，不影响无依赖关系的其他步骤继续执行。

### 扩展方向

- **流式结果推送**：在 StatusCallback 中实现 SSE/WebSocket 推送
- **动态重调度**：步骤失败后动态调整 DAG（如添加补偿步骤）
- **资源限制**：添加并发度控制（如最多同时执行 N 个步骤）
- **LangGraph 集成**：将 DAG 调度替换为 LangGraph 的原生图执行引擎
