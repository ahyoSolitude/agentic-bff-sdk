# SOP 跨领域执行

> 对应源码：`agentic_bff_sdk/sop_runner.py`

## 设计思路

BatchSOPRunner 处理的是**预定义流程**场景：当业务流程已经标准化为 SOP（Standard Operating Procedure）时，不需要 LLM 动态规划，而是按照 SOP 定义的步骤顺序依次执行。

与 IMCPlanner + ConcurrentDispatcher 的区别：

| | IMCPlanner + Dispatcher | BatchSOPRunner |
|---|---|---|
| 计划来源 | LLM 动态生成 | 预定义 SOP |
| 执行方式 | DAG 并发 | 顺序执行 |
| 适用场景 | 开放式查询 | 标准化流程（开户、清算等） |
| 异常处理 | 步骤级超时/失败 | SOP 级策略（retry/skip/rollback） |

## 核心接口

```python
class BatchSOPRunner(ABC):
    async def execute(self, plan, sop: SOPDefinition, scene: InteractionScene,
                      blackboard: Blackboard) -> List[Dict[str, Any]]
```

## SOPDefinition 结构

```python
SOPDefinition(
    sop_id="customer_onboarding",
    name="客户开户",
    steps=[
        {"domain": "account", "action": "create", "parameters": {...}},
        {"domain": "kyc", "action": "verify", "parameters": {...}},
        {"domain": "compliance", "action": "check", "parameters": {...}},
    ],
    exception_policies={
        "ConnectionError": "retry",    # 网络错误 → 重试（最多 3 次）
        "ValueError": "skip",          # 数据错误 → 跳过继续
        "RuntimeError": "rollback",    # 严重错误 → 回滚（抛出 RuntimeError）
    },
    dialog_templates={
        InteractionScene.PHONE: "您好，正在为您办理{step}...",
        InteractionScene.ONLINE: "处理中: {step}",
    },
)
```

## 异常处理策略

| 策略 | 行为 | 后续步骤 |
|------|------|---------|
| `retry` | 最多重试 3 次（`MAX_RETRY_ATTEMPTS`） | 成功则继续；全部失败则标记 `retry_exhausted` 并继续 |
| `skip` | 记录日志，标记 `skipped` | 继续执行后续步骤 |
| `rollback` | 抛出 `RuntimeError` | 立即终止，不执行后续步骤 |

策略匹配基于异常类名（如 `"ConnectionError"`），未匹配的异常默认走 `skip`。

## 对话模板

根据 `InteractionScene`（phone / face_to_face / online）选择对应的对话模板，写入 Blackboard 供下游使用。

## Blackboard 写入

每个步骤的执行结果自动写入 Blackboard，key 格式为 `sop_{sop_id}_step_{index}`。

## 扩展方向

- **条件分支**：在 SOP 步骤中支持条件判断（if/else）
- **并行步骤**：标记某些步骤可以并行执行
- **SOP 编辑器**：提供可视化 SOP 编辑工具，导出 SOPDefinition JSON
- **补偿事务**：rollback 时自动执行已完成步骤的补偿操作
