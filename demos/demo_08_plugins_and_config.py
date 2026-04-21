#!/usr/bin/env python3
"""Demo 8: 插件系统、渠道适配 & 声明式配置

展示能力：
- PluginRegistry 插件注册（Router、Executor、Generator、Tool、Chain）
- ChannelAdapter 渠道适配器（自定义 + 默认）
- OrchestrationConfig YAML/JSON 声明式配置
- create_sdk 工厂函数
"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional, Union

from langchain_core.tools import BaseTool

from agentic_bff_sdk import (
    CardOutput,
    Card,
    CardType,
    ClarificationQuestion,
    DomainRequest,
    DomainResponse,
    IntentResult,
    OrchestrationConfig,
    PlanStep,
    ExecutionPlan,
    RequestMessage,
    SDKConfig,
    SessionState,
    SynthesisResult,
    AggregatedResult,
    StepResult,
    StepStatus,
)
from agentic_bff_sdk.agent_executor import AgentExecutor
from agentic_bff_sdk.blackboard import Blackboard
from agentic_bff_sdk.card_generator import CardGenerator
from agentic_bff_sdk.config import AgentExecutorConfig
from agentic_bff_sdk.planner import IMCPlanner
from agentic_bff_sdk.plugins import ChannelAdapter, DefaultChannelAdapter, PluginRegistry
from agentic_bff_sdk.router import TopLevelRouter
from agentic_bff_sdk.sdk import create_sdk
from agentic_bff_sdk.synthesizer import Synthesizer


# ============================================================
# 自定义组件实现
# ============================================================

class MyCustomRouter(TopLevelRouter):
    """自定义路由器：基于关键词的简单路由。"""
    async def route(self, user_input, session_state, mode=None):
        if "基金" in user_input:
            return IntentResult(intent_type="fund_query", confidence=0.95, parameters={})
        return IntentResult(intent_type="general", confidence=0.8, parameters={})

    def register_priority_rule(self, rule): pass
    def register_fallback_handler(self, handler): pass


class MyCustomPlanner(IMCPlanner):
    async def generate_plan(self, intent, session_state, timeout_seconds=None):
        return ExecutionPlan(
            plan_id="custom_plan", intent=intent,
            steps=[PlanStep(step_id="s1", domain="demo", action="process", parameters={})],
            created_at=time.time(),
        )
    async def persist_plan(self, plan): return plan.plan_id


class MyCustomSynthesizer(Synthesizer):
    async def synthesize(self, aggregated, session_state, quality_threshold=0.7):
        return SynthesisResult(text_response="自定义综合结果", quality_score=0.9)


class MyCustomTool(BaseTool):
    """自定义 LangChain 工具。"""
    name: str = "calculate_risk"
    description: str = "计算投资风险评分"

    def _run(self, portfolio: str = "") -> str:
        return f"风险评分: 65 (组合: {portfolio})"


class WeChatAdapter(ChannelAdapter):
    """微信渠道适配器。"""
    async def adapt_request(self, request: Any) -> RequestMessage:
        # 将微信消息格式转换为 SDK RequestMessage
        return RequestMessage(
            user_input=request.get("Content", ""),
            session_id=request.get("FromUserName", "unknown"),
            channel_id="wechat",
            metadata={"msg_type": request.get("MsgType", "text")},
        )

    async def adapt_response(self, response: Any) -> Dict[str, Any]:
        # 将 SDK 响应转换为微信回复格式
        return {
            "MsgType": "text",
            "Content": str(response.content) if hasattr(response, "content") else str(response),
        }


async def demo_plugin_registry():
    print("=" * 60)
    print("8.1 PluginRegistry 插件注册")
    print("=" * 60)

    registry = PluginRegistry()

    # 注册各类插件
    registry.register_router(MyCustomRouter())
    registry.register_tool(MyCustomTool())
    registry.register_chain({"name": "risk_assessment_chain", "steps": ["fetch", "compute", "report"]})
    registry.register_channel_adapter("wechat", WeChatAdapter())
    registry.register_channel_adapter("web", DefaultChannelAdapter())

    print(f"  Router: {type(registry.router).__name__}")
    print(f"  Tools: {[t.name for t in registry.tools]}")
    print(f"  Chains: {len(registry.chains)} 个")
    print(f"  Channel Adapters: {list(registry.channel_adapters.keys())}")

    # 通用注册接口
    registry.register("tool", MyCustomTool(name="another_tool", description="另一个工具"))
    print(f"  通用注册后 Tools: {[t.name for t in registry.tools]}")
    print()


async def demo_channel_adapter():
    print("=" * 60)
    print("8.2 ChannelAdapter 渠道适配")
    print("=" * 60)

    # 微信适配器
    wechat_adapter = WeChatAdapter()
    wechat_msg = {
        "FromUserName": "wx_user_001",
        "MsgType": "text",
        "Content": "帮我查一下基金净值",
    }
    adapted = await wechat_adapter.adapt_request(wechat_msg)
    print(f"  微信消息 → RequestMessage:")
    print(f"    user_input: {adapted.user_input}")
    print(f"    session_id: {adapted.session_id}")
    print(f"    channel_id: {adapted.channel_id}")
    print(f"    metadata: {adapted.metadata}")

    # 默认适配器（直通）
    default_adapter = DefaultChannelAdapter()
    sdk_msg = RequestMessage(user_input="hello", session_id="s1", channel_id="web")
    passthrough = await default_adapter.adapt_request(sdk_msg)
    print(f"\n  默认适配器（直通）: {passthrough.user_input}")

    # 从 dict 构造
    dict_msg = {"user_input": "from dict", "session_id": "s2", "channel_id": "api"}
    from_dict = await default_adapter.adapt_request(dict_msg)
    print(f"  从 dict 构造: {from_dict.user_input}")
    print()


async def demo_yaml_config():
    print("=" * 60)
    print("8.3 YAML/JSON 声明式配置")
    print("=" * 60)

    config = OrchestrationConfig(
        sdk=SDKConfig(
            session_idle_timeout_seconds=900,
            intent_confidence_threshold=0.8,
            max_reasoning_steps=15,
        ),
    )

    # 序列化为 YAML
    yaml_str = config.to_yaml()
    print("  YAML 配置 (前 200 字符):")
    print("  " + yaml_str[:200].replace("\n", "\n  ") + "...")

    # 序列化为 JSON
    json_str = config.to_json()
    parsed = json.loads(json_str)
    print(f"\n  JSON 配置 keys: {list(parsed.keys())}")

    # Round-trip
    restored = OrchestrationConfig.from_yaml(yaml_str)
    print(f"  YAML Round-trip: session_timeout={restored.sdk.session_idle_timeout_seconds}")
    print()


async def demo_create_sdk():
    print("=" * 60)
    print("8.4 create_sdk 工厂函数")
    print("=" * 60)

    async def mock_invoker(req: DomainRequest) -> DomainResponse:
        return DomainResponse(request_id=req.request_id, domain=req.domain, success=True, data={"ok": True})

    config = OrchestrationConfig(
        sdk=SDKConfig(session_idle_timeout_seconds=600),
    )

    # 通过工厂创建完整 SDK 实例
    gateway = create_sdk(
        config,
        router=MyCustomRouter(),
        planner=MyCustomPlanner(),
        synthesizer=MyCustomSynthesizer(),
        domain_invoker=mock_invoker,
    )

    print(f"  Gateway 类型: {type(gateway).__name__}")
    print(f"  Session 超时: {gateway.config.session_idle_timeout_seconds}s")

    # 发送请求
    resp = await gateway.handle_request(
        RequestMessage(user_input="查询基金", session_id="factory_demo", channel_id="web")
    )
    print(f"  请求结果: error={resp.error}, content 类型={type(resp.content).__name__}")
    print()

    print("✅ Demo 8 完成\n")


async def main():
    print("\n🔷 Demo 8: 插件系统、渠道适配 & 声明式配置\n")
    await demo_plugin_registry()
    await demo_channel_adapter()
    await demo_yaml_config()
    await demo_create_sdk()


if __name__ == "__main__":
    asyncio.run(main())
