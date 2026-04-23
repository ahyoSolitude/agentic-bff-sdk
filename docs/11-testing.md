# 测试策略

> 对应目录：`tests/`

## 测试目标

测试应验证新架构的稳定契约，而不是绑定旧实现细节。重点覆盖：

- 公共模型
- 执行计划校验
- 状态作用域隔离
- Router 澄清和 fallback
- Planner/SOPCompiler 统一产出 `ExecutionPlan`
- Dispatcher DAG 调度
- DomainGateway 到 AgentExecutor 的执行链路
- RuleEngineClient 缓存语义
- Aggregator 和 ResponseEngine
- Gateway/Pipeline/TaskManager 协作

## 测试分层

```text
Unit Tests
  -> 单个模块和边界条件

Property-Based Tests
  -> 模型、DAG、状态机、不变量

Integration Tests
  -> Gateway 到 ResponseEnvelope 的完整链路
```

## 核心属性测试

建议保留并调整以下属性：

| 属性 | 验证内容 |
|------|----------|
| Session Round-Trip | 保存后加载等价 |
| Topic Invariant | 最多一个 active topic |
| Blackboard TTL | 过期键清理 |
| Request Validation | 缺少 session/channel 返回错误 |
| Router Clarification | 低置信度或歧义返回澄清 |
| Plan Validation | step_id 唯一、依赖存在 |
| DAG Cycle Detection | 循环依赖拒绝 |
| Dispatch Ordering | 步骤启动前依赖已完成 |
| Step State Machine | 状态转换合法 |
| Domain Routing | 已注册领域成功，未注册失败 |
| Agent Tool Validation | 工具输入 schema 校验 |
| Rule Metadata Cache | TTL 内不重复查询元数据 |
| Aggregation Completeness | 缺失步骤正确标记 |
| Response Capability Downgrade | 渠道不支持的卡片被降级 |
| Async Task Round-Trip | 提交后可查询状态 |

## 集成测试场景

### 同步请求完整链路

```text
GatewayRequest
  -> MASGateway
  -> RequestPipeline
  -> Router
  -> Planner
  -> Dispatcher
  -> DomainGateway
  -> AgentExecutor
  -> Aggregator
  -> ResponseEngine
  -> GatewayResponse
```

### SOP 请求完整链路

验证 SOP 不再由独立 runner 执行，而是：

```text
Router -> SOPCompiler -> ExecutionPlan -> Dispatcher
```

### 异步任务链路

验证：

- `submit_task()` 返回 `task_id`
- `TaskManager` 更新状态
- Pipeline 成功或失败后快照可查询
- 事件被发布

## 测试工具

- `pytest`
- `pytest-asyncio`
- `hypothesis`
- `pytest-mock`
- `jsonschema`

## 运行方式

```bash
pytest
pytest -m property
pytest tests/test_dispatch.py
```

## 迁移注意

旧测试中如果直接断言以下实现细节，需要更新：

- SOP 独立执行器路径
- `MASGateway` 直接串完整管线
- `Synthesizer` 和 `CardGenerator` 独立作为 Pipeline 依赖
- `DomainGateway` 直接执行任务包

新测试应以新公共契约为准：

- `ExecutionPlan`
- `RequestPipeline`
- `TaskManager`
- `DomainGateway -> AgentExecutor`
- `ResponseEngine.compose()`
