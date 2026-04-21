# Implementation Plan: Agentic BFF SDK

## Overview

基于 Python + LangChain/LangGraph 构建多智能体系统（MAS）编排 SDK。按照自底向上的策略，先实现核心数据模型和基础组件（Blackboard、SessionContext），再逐步构建上层编排组件（Router、Planner、Dispatcher），最后实现结果聚合与富媒体生成，最终通过 MAS Gateway 将所有组件串联起来。

## Tasks

- [x] 1. 项目初始化与核心数据模型
  - [x] 1.1 创建项目结构和包配置
    - 创建 `agentic_bff_sdk/` 包目录结构，包含 `__init__.py`
    - 创建 `pyproject.toml`，声明依赖：`pydantic`, `langchain-core`, `langgraph`, `httpx`, `pyyaml`
    - 创建 `tests/` 目录和 `conftest.py`，配置 pytest + hypothesis + pytest-asyncio
    - _Requirements: 12.6_

  - [x] 1.2 实现核心数据模型（Pydantic Models）
    - 创建 `agentic_bff_sdk/models.py`
    - 实现 `RequestMessage`, `ResponseMessage`, `ErrorResponse` 请求/响应模型
    - 实现 `Topic`, `SessionState` 会话模型
    - 实现 `IntentResult`, `ClarificationQuestion`, `RouterMode` 意图模型
    - 实现 `PlanStep`, `ExecutionPlan` 执行计划模型
    - 实现 `StepStatus`, `StepResult` 步骤状态模型
    - 实现 `DomainRequest`, `DomainResponse` 领域调用模型
    - 实现 `AggregatedResult`, `SynthesisResult` 聚合/综合模型
    - 实现 `CardType`, `Card`, `CardOutput` 卡片模型
    - 实现 `TaskStatus` 任务状态枚举
    - _Requirements: 1.1, 1.4, 4.2, 6.5, 10.4_

  - [x] 1.3 实现配置模型
    - 创建 `agentic_bff_sdk/config.py`
    - 实现 `SDKConfig` 全局配置模型，包含会话管理、意图路由、执行控制等所有可配置参数
    - 实现 `ChannelAdapterConfig` 渠道适配器配置
    - 实现 `TaskPackageConfig` 领域任务包配置
    - 实现 `OrchestrationConfig` 编排流程配置（支持 YAML/JSON 加载）
    - 实现 `SOPDefinition`, `InteractionScene` SOP 相关模型
    - 实现 `ToolDefinition`, `AgentExecutorConfig` 工具与执行器配置
    - _Requirements: 12.2, 5.1, 5.2, 8.2_

  - [x] 1.4 编写配置 Round-Trip 属性测试
    - **Property 29: 编排配置 Round-Trip**
    - 使用 Hypothesis 生成随机 `OrchestrationConfig`，验证序列化为 YAML/JSON 后再反序列化与原始配置等价
    - **Validates: Requirements 12.2**

- [x] 2. Blackboard 共享状态组件
  - [x] 2.1 实现 Blackboard 线程安全键值存储
    - 创建 `agentic_bff_sdk/blackboard.py`
    - 实现 `Blackboard` 类，使用 `asyncio.Lock` 保证线程安全
    - 实现 `get(key)`, `set(key, value)`, `delete(key)` 方法
    - 实现 `_access_times` 记录每个 key 的最后访问时间
    - 实现 `cleanup_expired(ttl_seconds)` 方法，清理过期键值并返回被清理的 key 列表
    - _Requirements: 2.2, 2.5_

  - [x] 2.2 编写 Blackboard 键值 Round-Trip 属性测试
    - **Property 5: Blackboard 键值 Round-Trip**
    - 使用 Hypothesis 生成随机键值对，验证 set 后 get 返回等价值
    - **Validates: Requirements 2.2, 5.6, 13.3**

  - [x] 2.3 编写 Blackboard 过期清理属性测试
    - **Property 6: Blackboard 过期清理**
    - 使用 Hypothesis 生成随机键值集合和 TTL，验证过期键被移除、未过期键被保留
    - **Validates: Requirements 2.5**

- [x] 3. Session Context 会话管理组件
  - [x] 3.1 实现 SessionContext 会话管理
    - 创建 `agentic_bff_sdk/session.py`
    - 定义 `StorageBackend` 抽象基类（`save`, `load`, `delete` 方法）
    - 实现 `InMemoryStorageBackend` 默认内存存储
    - 实现 `SessionContext` 类，包含 `get_or_create`, `save`, `cleanup_expired` 方法
    - 实现话题管理方法：`create_topic`, `switch_topic`, `close_topic`
    - 实现对话历史压缩方法：当轮次超过 `max_dialog_history_turns` 时进行摘要压缩
    - _Requirements: 1.2, 1.3, 2.1, 2.3, 2.4_

  - [x] 3.2 编写 Session 状态 Round-Trip 属性测试
    - **Property 1: Session 状态持久化 Round-Trip**
    - 使用 Hypothesis 生成随机 `SessionState`，验证保存后加载与原始状态等价
    - **Validates: Requirements 1.2, 2.1, 2.4**

  - [x] 3.3 编写会话过期清理属性测试
    - **Property 3: 会话过期清理**
    - 使用 Hypothesis 生成随机会话集合和超时时间，验证过期会话被移除、未过期会话被保留
    - **Validates: Requirements 1.5**

  - [x] 3.4 编写话题管理一致性属性测试
    - **Property 4: 话题管理一致性**
    - 使用 Hypothesis 生成随机话题操作序列，验证操作后话题列表满足一致性约束
    - **Validates: Requirements 1.3**

  - [x] 3.5 编写对话历史压缩属性测试
    - **Property 7: 对话历史压缩后长度不超限**
    - 使用 Hypothesis 生成超长对话历史，验证压缩后长度 ≤ max_dialog_history_turns 且最近轮次完整保留
    - **Validates: Requirements 2.3**

- [x] 4. Checkpoint — 确保基础组件测试通过
  - 确保所有测试通过，如有问题请向用户确认。

- [x] 5. Top Level Router 意图路由组件
  - [x] 5.1 实现 TopLevelRouter 抽象基类与默认实现
    - 创建 `agentic_bff_sdk/router.py`
    - 定义 `TopLevelRouter` 抽象基类，包含 `route`, `register_priority_rule`, `register_fallback_handler` 方法
    - 实现 `DefaultTopLevelRouter`，基于 LLM 进行意图识别
    - 实现优先匹配规则逻辑：优先检查已注册规则，匹配则直接返回
    - 实现置信度阈值判断：低于阈值返回 `ClarificationQuestion`
    - 实现歧义意图检测：前两个候选意图置信度差值在 `intent_ambiguity_range` 内时返回候选列表
    - 实现兜底路由：无匹配意图时路由到已注册的 fallback handler
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 5.2 编写低置信度意图触发澄清属性测试
    - **Property 8: 低置信度意图触发澄清**
    - 使用 Hypothesis 生成随机置信度分数，验证低于阈值时返回 ClarificationQuestion
    - **Validates: Requirements 3.3**

  - [x] 5.3 编写优先匹配规则属性测试
    - **Property 9: 优先匹配规则优先生效**
    - 使用 Hypothesis 生成随机用户输入和优先规则，验证匹配规则时返回对应意图
    - **Validates: Requirements 3.4**

  - [x] 5.4 编写歧义意图返回候选列表属性测试
    - **Property 10: 歧义意图返回候选列表**
    - 使用 Hypothesis 生成随机意图结果集合，验证置信度差值在范围内时返回候选列表
    - **Validates: Requirements 3.5**

  - [x] 5.5 编写无匹配意图路由到兜底链路属性测试
    - **Property 11: 无匹配意图路由到兜底链路**
    - 验证无法匹配任何已注册意图时，请求被路由到兜底处理链路
    - **Validates: Requirements 3.6**

- [x] 6. IMC Planner 执行计划生成组件
  - [x] 6.1 实现 IMCPlanner 抽象基类与默认实现
    - 创建 `agentic_bff_sdk/planner.py`
    - 定义 `IMCPlanner` 抽象基类，包含 `generate_plan`, `persist_plan` 方法
    - 实现 `DefaultIMCPlanner`，基于 CoT 链式推理生成执行计划
    - 实现超时控制：在可配置的超时时间内完成计划生成
    - 实现步骤依赖关系标注
    - 实现 ReAct 循环节点嵌入支持
    - 实现执行计划持久化（离线场景）
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [x] 6.2 编写执行计划结构有效性属性测试
    - **Property 12: 执行计划结构有效性**
    - 使用 Hypothesis 生成随机 ExecutionPlan，验证每个 PlanStep 的 domain/action 非空，dependencies 引用的 step_id 存在
    - **Validates: Requirements 4.2, 4.6**

  - [x] 6.3 编写执行计划持久化 Round-Trip 属性测试
    - **Property 13: 执行计划持久化 Round-Trip**
    - 使用 Hypothesis 生成随机 ExecutionPlan，验证持久化后加载与原始计划等价
    - **Validates: Requirements 4.5**

- [x] 7. Batch SOP Runner 跨领域执行组件
  - [x] 7.1 实现 BatchSOPRunner 抽象基类与默认实现
    - 创建 `agentic_bff_sdk/sop_runner.py`
    - 定义 `BatchSOPRunner` 抽象基类，包含 `execute` 方法
    - 实现 `DefaultBatchSOPRunner`，按 SOP 定义编排多领域调用序列
    - 实现交互场景对话模板选择逻辑
    - 实现异常处理策略（retry/skip/rollback）
    - 实现步骤结果写入 Blackboard
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 7.2 编写 SOP 异常处理策略属性测试
    - **Property 14: SOP 异常处理策略正确执行**
    - 使用 Hypothesis 生成随机失败场景和异常策略，验证执行与策略匹配的恢复操作
    - **Validates: Requirements 5.5**

  - [x] 7.3 编写交互场景对话模板匹配属性测试
    - **Property 15: 交互场景对话模板匹配**
    - 使用 Hypothesis 生成随机 InteractionScene，验证选择对应的对话模板
    - **Validates: Requirements 5.2**

- [x] 8. Concurrent Dispatcher DAG 并发调度组件
  - [x] 8.1 实现 ConcurrentDispatcher DAG 调度引擎
    - 创建 `agentic_bff_sdk/dispatcher.py`
    - 实现 `ConcurrentDispatcher` 类
    - 实现 `validate_dag` 方法：检测循环依赖，返回循环路径或 None
    - 实现 `dispatch` 方法：解析 DAG 依赖关系，使用 asyncio 并发执行无依赖步骤
    - 实现步骤状态管理：PENDING → RUNNING → {COMPLETED, FAILED, TIMEOUT}
    - 实现超时控制：超时步骤标记为 TIMEOUT，继续执行其余步骤
    - 实现 `StatusCallback` 回调通知状态变更
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 8.2 编写 DAG 循环依赖检测属性测试
    - **Property 16: DAG 循环依赖检测**
    - 使用 Hypothesis 生成随机 DAG（含循环和无循环），验证循环检测正确性
    - **Validates: Requirements 6.6**

  - [x] 8.3 编写 DAG 并发调度正确性属性测试
    - **Property 17: DAG 并发调度正确性**
    - 使用 Hypothesis 生成随机有效 DAG，验证每批次调度的步骤的所有依赖已完成
    - **Validates: Requirements 6.1, 6.2**

  - [x] 8.4 编写步骤状态转换有效性属性测试
    - **Property 18: 步骤状态转换有效性**
    - 使用 Hypothesis 生成随机状态转换序列，验证状态转换遵循有效路径
    - **Validates: Requirements 6.5**

  - [x] 8.5 编写超时步骤标记与继续执行属性测试
    - **Property 19: 超时步骤标记与继续执行**
    - 验证超时步骤被标记为 TIMEOUT，不依赖该步骤的其余步骤继续执行
    - **Validates: Requirements 6.4**

- [x] 9. Checkpoint — 确保编排层组件测试通过
  - 确保所有测试通过，如有问题请向用户确认。

- [x] 10. Domain Gateway 领域网关组件
  - [x] 10.1 实现 DomainGateway 抽象基类与默认实现
    - 创建 `agentic_bff_sdk/domain_gateway.py`
    - 定义 `DomainGateway` 抽象基类，包含 `invoke`, `register_task_package`, `invoke_rule_engine` 方法
    - 实现 `DefaultDomainGateway`，根据 domain 标识路由到对应 TaskPackage
    - 实现协议转换逻辑（SDK 内部格式 → 微服务格式）
    - 实现服务不可用降级策略
    - 实现调用审计日志记录
    - 实现规则引擎调用（通过 httpx 异步 HTTP）
    - 实现规则元数据缓存（TTL 机制）
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 13.1, 13.2, 13.5_

  - [x] 10.2 编写领域路由正确性属性测试
    - **Property 20: 领域路由正确性**
    - 使用 Hypothesis 生成随机 DomainRequest 和已注册 TaskPackage 集合，验证路由正确性
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.5**

  - [x] 10.3 编写规则元数据缓存有效性属性测试
    - **Property 31: 规则元数据缓存有效性**
    - 验证首次查询后在 TTL 内的后续查询返回缓存数据而不触发实际调用
    - **Validates: Requirements 13.5**

- [x] 11. Agent Executor 执行代理组件
  - [x] 11.1 实现 AgentExecutor 抽象基类与默认实现
    - 创建 `agentic_bff_sdk/agent_executor.py`
    - 定义 `AgentExecutor` 抽象基类，包含 `execute`, `register_tool` 方法
    - 实现 `DefaultAgentExecutor`，基于 LangChain ReAct Agent 构建
    - 实现自定义工具注册机制
    - 实现工具输入参数验证（基于 input_schema）
    - 实现最大推理步数限制
    - 实现 Blackboard 上下文传递给 LLM
    - 实现工具调用错误反馈给 LLM 决策
    - 实现规则引擎降级策略（超时/错误时返回默认值或抛出异常）
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 13.3, 13.4_

  - [x] 11.2 编写工具输入参数验证属性测试
    - **Property 21: 工具输入参数验证**
    - 使用 Hypothesis 生成随机工具调用请求和 input_schema，验证合规参数通过、不合规参数拒绝
    - **Validates: Requirements 8.4**

  - [x] 11.3 编写 Agent 推理步数上限属性测试
    - **Property 22: Agent 推理步数上限**
    - 验证 AgentExecutor 执行过程中推理步数不超过配置的 max_reasoning_steps
    - **Validates: Requirements 8.6**

  - [x] 11.4 编写规则引擎降级策略属性测试
    - **Property 30: 规则引擎降级策略**
    - 使用 Hypothesis 生成随机超时/错误场景，验证配置降级策略时返回默认值，未配置时抛出异常
    - **Validates: Requirements 13.4**

- [x] 12. Fan-In Aggregator 结果聚合组件
  - [x] 12.1 实现 FanInAggregator 结果聚合器
    - 创建 `agentic_bff_sdk/aggregator.py`
    - 实现 `FanInAggregator` 类，基于 Async Fan-In 模式收集并发步骤结果
    - 实现等待超时逻辑：超时后将已收集的部分结果传递给下游，标注缺失部分
    - 实现完整性判断：所有步骤完成时 `is_partial=False`，部分缺失时 `is_partial=True`
    - _Requirements: 9.1, 9.2, 9.3_

  - [x] 12.2 编写结果聚合完整性属性测试
    - **Property 23: 结果聚合完整性**
    - 使用 Hypothesis 生成随机步骤结果集合，验证完整/部分聚合的正确性
    - **Validates: Requirements 9.1, 9.2, 9.3**

- [x] 13. Synthesizer 结果综合组件
  - [x] 13.1 实现 Synthesizer 抽象基类与默认实现
    - 创建 `agentic_bff_sdk/synthesizer.py`
    - 定义 `Synthesizer` 抽象基类，包含 `synthesize` 方法
    - 实现 `DefaultSynthesizer`，通过 LLM 生成连贯的自然语言响应
    - 实现质量评分机制
    - 实现交叉 LLM 回路：质量不达标时触发补充查询，最多重试 `max_cross_llm_loops` 次
    - 实现策略规则引擎结果整合
    - _Requirements: 9.4, 9.5, 9.6_

- [x] 14. Card Generator 富媒体生成组件
  - [x] 14.1 实现 CardGenerator 抽象基类与默认实现
    - 创建 `agentic_bff_sdk/card_generator.py`
    - 定义 `CardGenerator` 抽象基类，包含 `generate` 方法
    - 实现 `DefaultCardGenerator`，将 SynthesisResult 转换为富媒体卡片
    - 实现多种卡片类型支持：TEXT, TABLE, CHART, ACTION_BUTTON, CONFIRMATION
    - 实现渠道能力适配：根据渠道支持的卡片类型过滤输出
    - 实现确认操作交互卡片生成
    - 实现 JSON Schema 输出验证
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 14.2 编写卡片输出 JSON Schema 合规属性测试
    - **Property 24: 卡片输出 JSON Schema 合规**
    - 使用 Hypothesis 生成随机 CardOutput，验证序列化为 JSON 后通过预定义 Schema 验证
    - **Validates: Requirements 10.4**

  - [x] 14.3 编写渠道能力适配属性测试
    - **Property 25: 渠道能力适配**
    - 使用 Hypothesis 生成随机渠道能力描述，验证生成的卡片仅使用该渠道支持的类型
    - **Validates: Requirements 10.3**

  - [x] 14.4 编写确认操作生成交互卡片属性测试
    - **Property 26: 确认操作生成交互卡片**
    - 使用 Hypothesis 生成 requires_confirmation=True 的 SynthesisResult，验证输出包含 CONFIRMATION 卡片
    - **Validates: Requirements 10.5**

- [x] 15. Checkpoint — 确保领域层与下层组件测试通过
  - 确保所有测试通过，如有问题请向用户确认。


- [x] 16. MAS Gateway 全局入口组件
  - [x] 16.1 实现 MASGateway 抽象基类与默认实现
    - 创建 `agentic_bff_sdk/gateway.py`
    - 定义 `MASGateway` 抽象基类，包含 `handle_request`, `submit_async_task`, `get_task_status`, `register_plugin` 方法
    - 实现 `DefaultMASGateway`，串联所有组件完成请求处理全流程
    - 实现请求验证：缺失 session_id 或 channel_id 时返回 ErrorResponse
    - 实现同步请求处理流程：Session 恢复 → 意图路由 → 计划生成 → 并发调度 → 结果聚合 → 综合决策 → 卡片生成
    - 实现会话空闲超时自动清理
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 12.1, 12.4_

  - [x] 16.2 编写请求验证属性测试
    - **Property 2: 请求验证 — 缺失标识返回错误**
    - 使用 Hypothesis 生成缺失 session_id 或 channel_id 的 RequestMessage，验证返回 ErrorResponse
    - **Validates: Requirements 1.4**

  - [x] 16.3 实现异步任务管理
    - 在 `DefaultMASGateway` 中实现 `submit_async_task` 方法，将长时间任务转为异步执行
    - 实现任务优先级队列管理
    - 实现 `get_task_status` 任务状态查询
    - 实现回调通知机制（Webhook / 消息队列）
    - 实现失败任务记录与手动重试支持
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

  - [x] 16.4 编写异步任务提交与查询 Round-Trip 属性测试
    - **Property 27: 异步任务提交与查询 Round-Trip**
    - 使用 Hypothesis 生成随机异步任务请求，验证返回非空 task_id 且查询返回有效 TaskStatus
    - **Validates: Requirements 11.1, 11.3**

  - [x] 16.5 编写任务优先级调度顺序属性测试
    - **Property 28: 任务优先级调度顺序**
    - 使用 Hypothesis 生成随机优先级任务集合，验证高优先级任务优先执行
    - **Validates: Requirements 11.5**

- [x] 17. SDK 插件系统与渠道适配
  - [x] 17.1 实现插件注册与渠道适配器机制
    - 创建 `agentic_bff_sdk/plugins.py`
    - 实现插件注册接口：支持自定义 TopLevelRouter、AgentExecutor、CardGenerator 的注册
    - 实现渠道适配器抽象基类 `ChannelAdapter`
    - 实现默认渠道适配器
    - 实现 LangChain Tool/Chain 抽象注册自定义业务逻辑
    - 确保所有公开接口具有完整的类型注解（Type Hints）
    - _Requirements: 12.1, 12.3, 12.4, 12.5, 12.6_

  - [x] 17.2 实现声明式配置加载
    - 在 `agentic_bff_sdk/config.py` 中实现 YAML/JSON 配置文件加载器
    - 实现从配置文件构建完整 SDK 实例的工厂方法
    - 支持通过配置定义智能体编排流程、渠道注册、任务包注册
    - _Requirements: 12.2_

- [x] 18. 错误处理与审计日志
  - [x] 18.1 实现统一错误处理框架
    - 创建 `agentic_bff_sdk/errors.py`
    - 定义错误码常量（REQ_, SESSION_, ROUTE_, PLAN_, DISPATCH_, DOMAIN_, RULE_, AGG_, SYNTH_, SYS_）
    - 实现自定义异常类层次结构
    - 实现错误传播机制：可恢复错误重试/降级、不可恢复错误返回 ErrorResponse、部分失败标记 partial 继续
    - _Requirements: 1.4, 5.5, 6.4, 6.6, 7.5, 8.5, 9.3, 13.4_

  - [x] 18.2 实现审计日志记录
    - 创建 `agentic_bff_sdk/audit.py`
    - 实现 `AuditLogger` 抽象基类
    - 实现默认审计日志记录器，记录 DomainGateway 每次调用的请求和响应摘要
    - _Requirements: 7.6_

- [x] 19. 组件集成与端到端串联
  - [x] 19.1 实现完整请求处理管线
    - 在 `DefaultMASGateway.handle_request` 中串联所有组件
    - 实现完整流程：请求验证 → 会话恢复 → 意图路由 → 计划生成/SOP 编排 → DAG 并发调度 → 结果聚合 → 综合决策 → 卡片生成 → 响应返回
    - 确保各组件间数据流正确传递
    - 确保错误处理在各层正确传播
    - _Requirements: 1.1, 1.2, 3.1, 4.1, 6.1, 9.1, 9.2, 10.1_

  - [x] 19.2 实现 SDK 入口与公开 API
    - 更新 `agentic_bff_sdk/__init__.py`，导出所有公开类和接口
    - 创建 `agentic_bff_sdk/sdk.py`，提供 `create_sdk` 工厂函数，从配置创建完整 SDK 实例
    - 确保 API 表面简洁，开发者仅需关注 `MASGateway` 和配置即可快速接入
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [x] 19.3 编写集成测试
    - 使用 Mock LLM 编写端到端集成测试
    - 测试完整请求流程：从 RequestMessage 到 CardOutput
    - 测试异步任务提交与查询流程
    - 测试错误处理与降级流程
    - _Requirements: 1.1, 3.1, 4.1, 9.1, 10.1, 11.1_

- [x] 20. Final Checkpoint — 确保所有测试通过
  - 确保所有测试通过，如有问题请向用户确认。

## Notes

- 标记 `*` 的子任务为可选任务，可跳过以加速 MVP 交付
- 每个任务引用了具体的需求编号，确保可追溯性
- Checkpoint 任务确保增量验证，及时发现问题
- Property-Based Tests 使用 Hypothesis 框架，验证 31 个正确性属性中的核心属性
- Unit Tests 验证具体示例和边界条件
- 所有组件基于 Python asyncio 异步编程模型
- 数据模型统一使用 Pydantic BaseModel，确保类型安全和序列化一致性