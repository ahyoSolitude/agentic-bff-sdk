# Agentic BFF SDK Demos

本目录包含一系列演示程序，展示 Agentic BFF SDK 的各项能力。所有 demo 均可独立运行，无需真实 LLM 服务。

## Demo 列表

| Demo | 文件 | 展示能力 |
|------|------|---------|
| Demo 1 | `demo_01_blackboard_session.py` | Blackboard 共享状态、SessionContext 会话管理、话题管理、对话历史压缩 |
| Demo 2 | `demo_02_intent_routing.py` | TopLevelRouter 意图路由、优先匹配规则、置信度阈值、歧义检测、兜底路由 |
| Demo 3 | `demo_03_plan_and_dispatch.py` | IMCPlanner 执行计划生成、ConcurrentDispatcher DAG 并发调度、步骤依赖与超时 |
| Demo 4 | `demo_04_domain_gateway.py` | DomainGateway 领域网关、TaskPackage 注册、协议转换、审计日志 |
| Demo 5 | `demo_05_sop_runner.py` | BatchSOPRunner 跨领域 SOP 执行、异常策略（retry/skip/rollback）、对话模板 |
| Demo 6 | `demo_06_aggregator_synthesizer_cards.py` | FanInAggregator 结果聚合、Synthesizer 综合决策、CardGenerator 富媒体卡片 |
| Demo 7 | `demo_07_error_handling.py` | 统一错误处理框架、SDKError 异常层次、错误传播与降级 |
| Demo 8 | `demo_08_plugins_and_config.py` | PluginRegistry 插件系统、ChannelAdapter 渠道适配、YAML 声明式配置、create_sdk 工厂 |
| **Demo 9** | `demo_09_full_pipeline.py` | **完整端到端管线**：从 RequestMessage 到 CardOutput，覆盖 SDK 全部能力 |

## 运行方式

```bash
# 确保已安装 SDK
pip install -e ".[dev]"

# 运行单个 demo
python demos/demo_01_blackboard_session.py

# 运行全部 demo
for f in demos/demo_*.py; do echo "=== $f ==="; python "$f"; echo; done
```
