# 测试策略

> 对应源码：`tests/` 目录

## 测试分层

```
┌─────────────────────────────────────┐
│       Integration Tests (19)        │
│   完整管线端到端验证                  │
├─────────────────────────────────────┤
│     Property-Based Tests (~80)      │
│   31 个正确性属性的自动化验证          │
├─────────────────────────────────────┤
│       Unit Tests (~470)             │
│   具体示例、边界条件、错误处理         │
└─────────────────────────────────────┘
```

总计 **569 个测试用例**。

## Property-Based Testing

SDK 使用 [Hypothesis](https://hypothesis.readthedocs.io/) 框架进行属性测试。与传统单元测试（固定输入 → 固定输出）不同，属性测试**自动生成随机输入**，验证系统在所有合法输入下都满足某个不变量。

每个属性测试运行 100 次随机输入（`@settings(max_examples=100)`）。

### 31 个正确性属性

| # | 属性 | 验证内容 | 测试模式 |
|---|------|---------|---------|
| 1 | Session Round-Trip | 保存后加载等价 | Round-Trip |
| 2 | 请求验证 | 缺失标识返回错误 | Error Condition |
| 3 | 会话过期清理 | 过期移除、未过期保留 | Invariant |
| 4 | 话题管理一致性 | 最多一个 active 话题 | Invariant |
| 5 | Blackboard Round-Trip | set 后 get 等价 | Round-Trip |
| 6 | Blackboard 过期清理 | TTL 过期移除 | Invariant |
| 7 | 对话历史压缩 | 压缩后长度 ≤ 限制 | Invariant |
| 8 | 低置信度触发澄清 | confidence < threshold → ClarificationQuestion | Metamorphic |
| 9 | 优先规则优先生效 | 匹配规则 → 跳过 LLM | Metamorphic |
| 10 | 歧义意图候选列表 | 差值 < range → 返回候选 | Metamorphic |
| 11 | 兜底路由 | 无匹配 → fallback handler | Metamorphic |
| 12 | 执行计划结构有效性 | domain/action 非空，依赖引用存在 | Invariant |
| 13 | 执行计划 Round-Trip | 持久化后加载等价 | Round-Trip |
| 14 | SOP 异常策略 | retry/skip/rollback 正确执行 | Metamorphic |
| 15 | 对话模板匹配 | scene → 对应模板 | Metamorphic |
| 16 | DAG 循环检测 | 有循环返回路径，无循环返回 None | Invariant |
| 17 | DAG 调度正确性 | 步骤启动时依赖已完成 | Invariant |
| 18 | 状态转换有效性 | 遵循 PENDING→RUNNING→{COMPLETED,FAILED,TIMEOUT} | Invariant |
| 19 | 超时继续执行 | 超时步骤标记 TIMEOUT，独立步骤继续 | Invariant |
| 20 | 领域路由正确性 | 已注册路由成功，未注册返回错误 | Metamorphic |
| 21 | 工具输入验证 | 合规通过，不合规拒绝 | Error Condition |
| 22 | 推理步数上限 | 不超过 max_reasoning_steps | Invariant |
| 23 | 结果聚合完整性 | 全部到齐 → is_partial=False | Invariant |
| 24 | 卡片 JSON Schema | 序列化后通过 Schema 验证 | Invariant |
| 25 | 渠道能力适配 | 仅使用支持的卡片类型 | Metamorphic |
| 26 | 确认操作卡片 | requires_confirmation → CONFIRMATION 卡片 | Metamorphic |
| 27 | 异步任务 Round-Trip | 提交后查询返回有效状态 | Round-Trip |
| 28 | 任务优先级 | 高优先级先执行 | Invariant |
| 29 | 配置 Round-Trip | YAML/JSON 序列化后反序列化等价 | Round-Trip |
| 30 | 规则引擎降级 | 有 fallback 返回默认值，无 fallback 抛异常 | Error Condition |
| 31 | 规则缓存有效性 | TTL 内不触发 HTTP 调用 | Idempotence |

### 测试模式分类

| 模式 | 含义 | 示例 |
|------|------|------|
| **Round-Trip** | 序列化 → 反序列化 = 原始值 | Session 保存/加载 |
| **Invariant** | 任何输入下某个条件始终成立 | 压缩后长度 ≤ 限制 |
| **Metamorphic** | 输入变化 → 输出按预期变化 | 置信度降低 → 触发澄清 |
| **Error Condition** | 非法输入 → 正确的错误响应 | 缺失字段 → ErrorResponse |
| **Idempotence** | 重复操作结果不变 | 缓存命中不触发调用 |

## 测试工具链

| 工具 | 用途 |
|------|------|
| pytest | 测试运行器 |
| hypothesis | Property-Based Testing |
| pytest-asyncio | 异步测试支持（mode=auto） |
| pytest-mock | Mock 工具 |
| jsonschema | Card 输出 Schema 验证 |

## 运行测试

```bash
# 全部测试
python -m pytest tests/ -v

# 仅属性测试
python -m pytest tests/ -v -m property

# 单个模块
python -m pytest tests/test_dispatcher_properties.py -v

# CI 模式（200 次随机输入）
python -m pytest tests/ --hypothesis-profile=ci
```
