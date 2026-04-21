# Agentic BFF SDK

基于 Python + LangChain/LangGraph 的多智能体系统（MAS）编排 SDK。

---

## 背景

在金融科技等复杂业务场景中，一个用户请求往往需要跨多个业务领域（基金、资产、风控、合规等）协调多个 AI Agent 才能完成。传统的单体 BFF（Backend for Frontend）难以应对这种多智能体协作的复杂性：意图识别、任务拆解、并发调度、结果聚合、多渠道适配——每一环都需要精心编排。

Agentic BFF SDK 正是为解决这一问题而设计的。它将多智能体编排的通用能力抽象为一套可复用的框架，让业务开发者只需关注领域逻辑本身，而非底层的 Agent 协作机制。

## 目标

- **统一入口**：为 Web、App、电话、企业微信等多渠道提供统一的智能体接入层
- **开箱即用**：每个组件都提供默认实现，零配置即可跑通完整管线
- **渐进扩展**：通过 ABC + 默认实现 + 可注入回调的三层模式，支持从局部替换到完全自定义
- **类型安全**：全量 Pydantic 数据模型 + 完整 Type Hints，IDE 友好
- **生产就绪**：统一错误处理、审计日志、异步任务管理、会话超时清理

## 设计思路

### 三层架构

```
┌──────────────────────────────────────────────────┐
│              Agentic BFF 上层                      │
│  MAS Gateway · SessionContext · Blackboard        │
│  TopLevelRouter · IMCPlanner · ConcurrentDispatcher│
│  BatchSOPRunner                                   │
├──────────────────────────────────────────────────┤
│            Domain Business Layer                  │
│  DomainGateway · AgentExecutor · Rule Engine      │
│  TaskPackage（按业务领域纵向划分）                   │
├──────────────────────────────────────────────────┤
│              Agentic BFF 下层                      │
│  FanInAggregator · Synthesizer · CardGenerator    │
└──────────────────────────────────────────────────┘
```

- **上层**：请求接入、上下文管理、意图路由、任务编排与并发调度
- **中间层**：具体业务领域的执行，每个领域封装为独立的 TaskPackage
- **下层**：多领域结果聚合、LLM 综合决策、富媒体卡片生成

### 请求处理全流程

```
RequestMessage
  → 请求验证（session_id / channel_id）
  → 会话恢复或创建（SessionContext）
  → 意图路由（TopLevelRouter）
  → 执行计划生成（IMCPlanner / BatchSOPRunner）
  → DAG 并发调度（ConcurrentDispatcher → DomainGateway）
  → 结果聚合（FanInAggregator）
  → 综合决策（Synthesizer）
  → 富媒体卡片生成（CardGenerator）
  → ResponseMessage
```

### 核心设计原则

| 原则 | 体现 |
|------|------|
| ABC + 默认实现 | 每个组件都有抽象基类和 Default 实现，可整体替换也可局部注入 |
| 全异步 | 所有 I/O 基于 asyncio，并发调度用 asyncio.gather/wait |
| Pydantic 类型安全 | 16 个数据模型 + 4 个枚举，自动验证、序列化、JSON Schema |
| 可注入回调 | Router 的 intent_recognizer、Planner 的 plan_generator、Synthesizer 的 synthesis_fn |
| 声明式配置 | OrchestrationConfig 支持 YAML/JSON，create_sdk 一行组装 |
| 分级错误处理 | 10 种异常子类，可恢复/不可恢复分类，部分失败继续 |

## 项目结构

```
├── agentic_bff_sdk/          # SDK 源码（19 个模块）
│   ├── models.py             # 核心数据模型
│   ├── config.py             # 配置管理
│   ├── gateway.py            # MAS Gateway 全局入口
│   ├── session.py            # 会话管理
│   ├── blackboard.py         # 共享状态存储
│   ├── router.py             # 意图路由
│   ├── planner.py            # 执行计划生成
│   ├── dispatcher.py         # DAG 并发调度
│   ├── sop_runner.py         # SOP 跨领域执行
│   ├── domain_gateway.py     # 领域网关
│   ├── agent_executor.py     # Agent 执行代理
│   ├── aggregator.py         # 结果聚合
│   ├── synthesizer.py        # 综合决策
│   ├── card_generator.py     # 富媒体卡片
│   ├── plugins.py            # 插件系统与渠道适配
│   ├── errors.py             # 统一错误处理
│   ├── audit.py              # 审计日志
│   ├── sdk.py                # SDK 工厂函数
│   └── __init__.py           # 公开 API 导出
├── tests/                    # 569 个测试用例
├── demos/                    # 9 个演示程序
├── docs/                     # 详细技术文档（见下方目录）
└── pyproject.toml            # 项目配置
```

## 安装

```bash
pip install -e ".[dev]"
```

## 快速验证

```bash
# 运行全部测试
python -m pytest tests/

# 运行 demo
python demos/demo_09_full_pipeline.py
```

## 详细文档

以下文档位于 [docs/](./docs/) 目录，按模块深入讲解设计与实现：

| 文档 | 内容 |
|------|------|
| [核心数据模型与配置](./docs/01-models-config.md) | Pydantic 模型设计、SDKConfig 参数、YAML/JSON 配置 |
| [会话与状态管理](./docs/02-session-blackboard.md) | SessionContext、Blackboard、话题管理、对话压缩 |
| [意图路由](./docs/03-router.md) | TopLevelRouter：优先规则、置信度阈值、歧义检测、兜底 |
| [执行计划与并发调度](./docs/04-planner-dispatcher.md) | IMCPlanner CoT 计划 + ConcurrentDispatcher DAG 调度 |
| [领域网关与 Agent 执行](./docs/05-domain-agent.md) | DomainGateway、TaskPackage、AgentExecutor、规则引擎 |
| [SOP 跨领域执行](./docs/06-sop-runner.md) | BatchSOPRunner：异常策略、对话模板、Blackboard 写入 |
| [结果聚合与响应生成](./docs/07-aggregator-synthesizer-cards.md) | Aggregator + Synthesizer + CardGenerator |
| [MAS Gateway 与异步任务](./docs/08-gateway.md) | 完整管线编排、异步任务队列、会话清理 |
| [插件系统与渠道适配](./docs/09-plugins-factory.md) | PluginRegistry、ChannelAdapter、create_sdk 工厂 |
| [错误处理与审计日志](./docs/10-errors-audit.md) | SDKError 层次、30 个错误码、AuditLogger |
| [测试策略](./docs/11-testing.md) | Property-Based Testing、31 个正确性属性、测试分层 |

## License

MIT
