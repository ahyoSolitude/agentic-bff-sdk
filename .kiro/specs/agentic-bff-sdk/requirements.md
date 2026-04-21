# Requirements Document

## Introduction

本文档定义了 Agentic BFF（Backend for Frontend）SDK 的需求规格。该 SDK 基于 Python + LangChain 框架构建，采用多智能体系统（MAS）架构，为上层渠道端提供统一的智能体编排与调度能力。

整体架构分为三层：
- **Agentic BFF 上层**：全局 MAS 入口，负责上下文管理、话题管理、意图路由与任务编排
- **Domain Business Layer（中间层）**：核心业务微服务，按业务领域纵向划分（如分级资产、公募基金等）
- **Agentic BFF 下层**：结果聚合、综合决策与富媒体生成

SDK 的设计目标是提供抽象、可复用的基础能力，支持在此基础上落地到具体业务场景（如托管外包），并允许多个渠道端按统一方式接入。

## Glossary

- **MAS_Gateway**：全局多智能体系统入口，负责上下文管理、话题管理和统一智能体接口
- **Session_Context**：会话上下文，维护单次会话的状态信息与对话历史
- **Blackboard**：黑板模式的共享状态存储，供多个智能体在协作过程中读写中间结果
- **Top_Level_Router**：顶层意图路由器，负责识别用户意图并将请求分发到对应的处理链路
- **IMC_Planner**：一次开发完成器（One-Shot Intent-to-Multi-Call Planner），基于 CoT 链式推理生成完整执行计划
- **Batch_SOP_Runner**：跨领域合并执行器，管理 NLP 对话策略，处理电话/面谈等多场景交互
- **Concurrent_Dispatcher**：分步并发调度引擎，基于 DAG 的并发调度策略，支持流式合并
- **Domain_Gateway**：集成式领域网关（ONE-AI-TRADING），负责多业务归口管理，为上层提供统一 API
- **Agent_Executor**：客户 Agent 执行代理，内部基于 ReAct 模式定义执行链
- **Rule_Engine**：策略规则引擎，基于 Java 实现复杂业务计算
- **Fan_In_Aggregator**：扩展结果聚合器，基于 Async Fan-In 模式聚合多步执行结果
- **Synthesizer**：结果综合与回调决策器，整合交叉 LLM 回路与策略决策
- **Card_Generator**：富媒体生成器，将结构化结果转换为前端可渲染的卡片/富文本格式
- **Task_Package**：业务领域任务包，封装特定领域的业务逻辑与工具调用集合
- **Channel**：渠道端，指接入 SDK 的前端应用或第三方系统
- **CoT**：Chain of Thought，链式思维推理
- **ReAct**：Reasoning + Acting，推理与行动交替的智能体执行模式
- **DAG**：Directed Acyclic Graph，有向无环图
- **SOP**：Standard Operating Procedure，标准操作流程

## Requirements

### Requirement 1: 全局 MAS 入口管理

**User Story:** As a 渠道端开发者, I want 通过统一的 MAS 入口提交请求并获取响应, so that 无需关心底层多智能体的编排细节。

#### Acceptance Criteria

1. THE MAS_Gateway SHALL 提供统一的请求接收接口，接受包含用户输入、会话标识和渠道标识的请求消息
2. WHEN 收到新请求时, THE MAS_Gateway SHALL 创建或恢复对应的 Session_Context 实例
3. THE MAS_Gateway SHALL 维护每个会话的话题列表，支持话题的创建、切换和关闭
4. IF 请求中缺少必要的会话标识或渠道标识, THEN THE MAS_Gateway SHALL 返回包含错误码和错误描述的标准错误响应
5. WHEN 会话超过可配置的空闲超时时间时, THE MAS_Gateway SHALL 自动清理对应的 Session_Context 资源

### Requirement 2: 会话记忆与状态管理

**User Story:** As a SDK 使用者, I want 在多轮对话中保持上下文连贯, so that 智能体能够基于历史信息做出更准确的决策。

#### Acceptance Criteria

1. THE Session_Context SHALL 存储当前会话的对话历史、用户画像摘要和活跃话题信息
2. THE Blackboard SHALL 提供线程安全的键值读写接口，供多个智能体在同一会话中共享中间结果
3. WHEN 对话历史超过可配置的最大轮次时, THE Session_Context SHALL 对早期对话进行摘要压缩，保留关键信息
4. WHEN 会话状态发生变更时, THE Session_Context SHALL 将状态持久化到可配置的存储后端
5. IF Blackboard 中的某个键值在可配置的时间内未被访问, THEN THE Blackboard SHALL 标记该键值为过期并在下次清理周期中移除

### Requirement 3: 顶层意图路由

**User Story:** As a SDK 使用者, I want 用户的自然语言输入被准确路由到对应的处理链路, so that 每个请求都能被正确的智能体处理。

#### Acceptance Criteria

1. WHEN 收到用户输入时, THE Top_Level_Router SHALL 识别用户意图并返回意图类型和置信度分数
2. THE Top_Level_Router SHALL 支持意图生成与确认意图两种模式：生成模式用于首次识别，确认模式用于向用户确认歧义意图
3. WHEN 意图置信度低于可配置的阈值时, THE Top_Level_Router SHALL 进入确认模式，生成澄清问题返回给用户
4. THE Top_Level_Router SHALL 支持优先匹配规则，允许通过配置指定高优先级意图的匹配条件
5. WHEN 存在多个匹配意图且置信度差值在可配置范围内时, THE Top_Level_Router SHALL 返回候选意图列表供用户选择
6. IF 无法识别任何已注册的意图, THEN THE Top_Level_Router SHALL 将请求路由到默认的兜底处理链路

### Requirement 4: 一次开发完成器（IMC Planner）

**User Story:** As a SDK 使用者, I want 对于明确意图的请求能一次性生成完整的执行计划, so that 减少多轮交互提升响应效率。

#### Acceptance Criteria

1. WHEN 收到已确认的用户意图时, THE IMC_Planner SHALL 基于 CoT 推理链生成包含所有必要步骤的执行计划
2. THE IMC_Planner SHALL 生成的执行计划包含步骤列表，每个步骤包含目标领域、调用动作和参数映射
3. THE IMC_Planner SHALL 支持意图无关的通用规划能力，不与特定业务领域耦合
4. WHERE 场景需要在线实时响应时, THE IMC_Planner SHALL 在可配置的超时时间内完成计划生成
5. WHERE 场景允许离线处理时, THE IMC_Planner SHALL 支持将执行计划持久化并异步执行
6. THE IMC_Planner SHALL 在执行计划中标注步骤间的依赖关系，支持后续并发调度优化
7. WHERE 复杂场景需要动态调整时, THE IMC_Planner SHALL 支持在执行计划中嵌入 ReAct 循环节点

### Requirement 5: 跨领域合并执行器（Batch SOP Runner）

**User Story:** As a SDK 使用者, I want 跨多个业务领域的操作能被合并编排执行, so that 复杂的跨域业务流程能高效完成。

#### Acceptance Criteria

1. THE Batch_SOP_Runner SHALL 接收执行计划并按照 SOP 定义的流程编排多个领域的调用序列
2. THE Batch_SOP_Runner SHALL 管理 NLP 对话策略，根据当前交互场景（电话、面谈、在线）选择对应的对话模板
3. WHEN 执行涉及知识库查询时, THE Batch_SOP_Runner SHALL 调用知识大模型检索相关知识并注入到执行上下文中
4. THE Batch_SOP_Runner SHALL 支持富文本格式的中间结果输出，包括结构化数据和自然语言混合格式
5. IF 某个领域调用失败, THEN THE Batch_SOP_Runner SHALL 根据 SOP 定义的异常处理策略执行重试、跳过或回滚操作
6. THE Batch_SOP_Runner SHALL 将每个步骤的执行结果写入 Blackboard，供后续步骤和聚合器读取

### Requirement 6: 分步并发调度引擎

**User Story:** As a SDK 使用者, I want 无依赖关系的执行步骤能并发执行, so that 整体响应时间最小化。

#### Acceptance Criteria

1. THE Concurrent_Dispatcher SHALL 解析执行计划中的步骤依赖关系，构建 DAG 调度图
2. WHEN DAG 中存在无依赖关系的步骤时, THE Concurrent_Dispatcher SHALL 并发执行这些步骤
3. THE Concurrent_Dispatcher SHALL 支持流式合并，将各并发步骤的部分结果实时推送到下游
4. WHEN 某个并发步骤执行超时时, THE Concurrent_Dispatcher SHALL 取消该步骤并标记为超时状态，继续执行其余步骤
5. THE Concurrent_Dispatcher SHALL 维护每个步骤的执行状态（待执行、执行中、已完成、失败、超时），并通过回调通知状态变更
6. IF DAG 中检测到循环依赖, THEN THE Concurrent_Dispatcher SHALL 拒绝执行并返回包含循环路径的错误信息

### Requirement 7: 领域网关集成

**User Story:** As a SDK 使用者, I want 通过统一的领域网关访问所有业务微服务, so that 上层编排逻辑无需关心各微服务的具体接入方式。

#### Acceptance Criteria

1. THE Domain_Gateway SHALL 提供统一的 API 接口，将上层请求路由到对应的业务微服务
2. THE Domain_Gateway SHALL 支持多业务归口管理，通过配置注册和发现可用的 Task_Package
3. WHEN 收到领域调用请求时, THE Domain_Gateway SHALL 根据请求中的领域标识路由到对应的 Task_Package
4. THE Domain_Gateway SHALL 支持请求的协议转换，将 SDK 内部格式转换为各微服务要求的格式
5. IF 目标微服务不可用, THEN THE Domain_Gateway SHALL 返回服务不可用错误，并触发可配置的降级策略
6. THE Domain_Gateway SHALL 记录每次调用的请求和响应摘要，用于审计和问题排查

### Requirement 8: Agent 执行代理

**User Story:** As a SDK 使用者, I want 每个领域任务由专属的 Agent 执行代理处理, so that 领域逻辑的封装和执行相互隔离。

#### Acceptance Criteria

1. THE Agent_Executor SHALL 基于 ReAct 模式定义执行链，交替进行推理和工具调用
2. THE Agent_Executor SHALL 支持注册自定义工具集，每个工具包含名称、描述、输入模式和执行函数
3. WHEN Agent_Executor 执行推理步骤时, THE Agent_Executor SHALL 将当前上下文（包括 Blackboard 数据）传递给 LLM 进行决策
4. WHEN Agent_Executor 决定调用工具时, THE Agent_Executor SHALL 验证工具输入参数符合定义的模式后执行调用
5. IF 工具调用返回错误, THEN THE Agent_Executor SHALL 将错误信息反馈给 LLM，由 LLM 决定重试或采用替代方案
6. THE Agent_Executor SHALL 在可配置的最大推理步数内完成执行，超过限制时返回当前中间结果

### Requirement 9: 结果聚合与综合决策

**User Story:** As a SDK 使用者, I want 多个智能体的执行结果被聚合并综合决策, so that 最终返回给用户的是一个连贯完整的响应。

#### Acceptance Criteria

1. THE Fan_In_Aggregator SHALL 基于 Async Fan-In 模式收集多个并发步骤的执行结果
2. WHEN 所有必要步骤完成时, THE Fan_In_Aggregator SHALL 将聚合结果传递给 Synthesizer 进行综合处理
3. WHEN 部分步骤超时或失败时, THE Fan_In_Aggregator SHALL 在可配置的等待时间后将已收集的结果传递给 Synthesizer，并标注缺失部分
4. THE Synthesizer SHALL 整合多个领域的执行结果，通过 LLM 生成连贯的自然语言响应
5. THE Synthesizer SHALL 支持交叉 LLM 回路，在综合结果不满足质量标准时触发补充查询
6. THE Synthesizer SHALL 结合策略规则引擎的输出进行最终决策，确保响应符合业务合规要求

### Requirement 10: 富媒体生成

**User Story:** As a 渠道端开发者, I want 响应结果以富媒体格式呈现, so that 前端能直接渲染结构化的卡片和交互组件。

#### Acceptance Criteria

1. THE Card_Generator SHALL 将 Synthesizer 的输出转换为可配置的富媒体卡片格式
2. THE Card_Generator SHALL 支持多种卡片类型，包括文本卡片、数据表格卡片、图表卡片和操作按钮卡片
3. WHEN 渠道端指定了特定的渲染能力时, THE Card_Generator SHALL 根据渠道能力适配输出格式
4. THE Card_Generator SHALL 输出符合预定义 JSON Schema 的结构化数据，确保前端可解析
5. IF Synthesizer 输出中包含需要用户确认的操作, THEN THE Card_Generator SHALL 生成包含确认按钮和操作摘要的交互卡片

### Requirement 11: 异步消息与任务管理

**User Story:** As a SDK 使用者, I want 长时间运行的任务能异步执行并通知结果, so that 不阻塞用户的实时交互体验。

#### Acceptance Criteria

1. THE MAS_Gateway SHALL 支持将长时间运行的任务转为异步执行模式，立即返回任务标识给调用方
2. WHEN 异步任务状态发生变更时, THE MAS_Gateway SHALL 通过可配置的回调机制（Webhook、消息队列）通知调用方
3. THE MAS_Gateway SHALL 提供任务查询接口，支持按任务标识查询任务的当前状态和中间结果
4. IF 异步任务执行失败, THEN THE MAS_Gateway SHALL 记录失败原因并通过回调通知调用方，同时支持手动重试
5. THE MAS_Gateway SHALL 支持任务的优先级管理，高优先级任务优先获得执行资源

### Requirement 12: SDK 抽象与多渠道接入

**User Story:** As a 渠道端开发者, I want SDK 提供清晰的抽象接口和扩展点, so that 能快速将 SDK 集成到不同的渠道端应用中。

#### Acceptance Criteria

1. THE MAS_Gateway SHALL 提供基于 Python 抽象基类的插件接口，支持自定义意图路由器、执行器和生成器的注册
2. THE MAS_Gateway SHALL 提供声明式的配置方式，通过 YAML 或 JSON 配置文件定义智能体编排流程
3. WHEN 新的 Channel 接入时, THE MAS_Gateway SHALL 仅需实现渠道适配器接口即可完成集成，无需修改核心编排逻辑
4. THE MAS_Gateway SHALL 提供默认实现，覆盖意图路由、计划生成、并发调度和结果聚合的基础能力
5. THE MAS_Gateway SHALL 支持通过 LangChain 的 Tool 和 Chain 抽象注册自定义业务逻辑
6. THE MAS_Gateway SHALL 提供完整的类型注解（Type Hints），确保 IDE 自动补全和静态类型检查的支持

### Requirement 13: 策略规则引擎集成

**User Story:** As a SDK 使用者, I want 复杂的业务规则计算由专用规则引擎处理, so that 规则逻辑与智能体逻辑解耦，便于业务人员维护。

#### Acceptance Criteria

1. THE Domain_Gateway SHALL 支持将特定计算请求路由到 Rule_Engine 进行处理
2. THE Rule_Engine SHALL 通过标准化的 API 接口接收规则执行请求，包含规则集标识和输入参数
3. WHEN Rule_Engine 返回计算结果时, THE Agent_Executor SHALL 将结果写入 Blackboard 供后续步骤使用
4. IF Rule_Engine 调用超时或返回错误, THEN THE Agent_Executor SHALL 根据配置的降级策略返回默认值或抛出异常
5. THE Domain_Gateway SHALL 缓存 Rule_Engine 的规则元数据，减少重复查询开销
