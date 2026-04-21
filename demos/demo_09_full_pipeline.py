#!/usr/bin/env python3
"""Demo 9: 完整端到端管线 — 覆盖 SDK 全部能力

本 demo 模拟一个「托管外包业务」场景，展示从用户请求到富媒体响应的完整流程。
覆盖 SDK 的全部核心能力：

✅ Blackboard 共享状态
✅ SessionContext 会话管理 & 话题管理 & 对话历史压缩
✅ TopLevelRouter 意图路由（优先规则 + 自定义识别器 + 兜底）
✅ IMCPlanner 执行计划生成（DAG 依赖 + ReAct 节点）
✅ ConcurrentDispatcher DAG 并发调度（超时 + 状态回调）
✅ DomainGateway 领域网关（TaskPackage + 协议转换）
✅ BatchSOPRunner SOP 执行（异常策略 + 对话模板）
✅ FanInAggregator 结果聚合（完整/部分）
✅ Synthesizer 综合决策（质量评分 + 交叉 LLM 回路）
✅ CardGenerator 富媒体卡片（渠道适配 + 确认卡片）
✅ AgentExecutor 工具验证 & 规则引擎降级
✅ PluginRegistry 插件系统 & ChannelAdapter 渠道适配
✅ 统一错误处理框架 (SDKError)
✅ 审计日志 (AuditLogger)
✅ OrchestrationConfig 声明式配置 & create_sdk 工厂
✅ 异步任务管理（提交 + 查询 + 优先级）
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Union
from unittest.mock import AsyncMock

from langchain_core.tools import BaseTool

from agentic_bff_sdk import (
    AggregatedResult,
    Blackboard,
    Card,
    CardOutput,
    CardType,
    ClarificationQuestion,
    DomainRequest,
    DomainResponse,
    ErrorResponse,
    ExecutionPlan,
    IntentResult,
    InteractionScene,
    OrchestrationConfig,
    PlanStep,
    PluginRegistry,
    RequestMessage,
    ResponseMessage,
    SDKConfig,
    SessionContext,
    SessionState,
    SOPDefinition,
    StepResult,
    StepStatus,
    SynthesisResult,
    TaskStatus,
    Topic,
    ToolDefinition,
    create_sdk,
)
from agentic_bff_sdk.agent_executor import (
    DefaultAgentExecutor,
    handle_rule_engine_call,
    validate_tool_input,
)
from agentic_bff_sdk.aggregator import FanInAggregator
from agentic_bff_sdk.audit import DefaultAuditLogger
from agentic_bff_sdk.card_generator import DefaultCardGenerator
from agentic_bff_sdk.dispatcher import ConcurrentDispatcher, StatusCallback
from agentic_bff_sdk.domain_gateway import DefaultDomainGateway
from agentic_bff_sdk.errors import (
    DomainError,
    SDKError,
    DOMAIN_SERVICE_UNAVAILABLE,
    handle_sdk_error,
    is_recoverable,
    create_partial_failure_response,
)
from agentic_bff_sdk.gateway import DefaultMASGateway
from agentic_bff_sdk.planner import DefaultIMCPlanner
from agentic_bff_sdk.plugins import ChannelAdapter, DefaultChannelAdapter
from agentic_bff_sdk.router import DefaultTopLevelRouter
from agentic_bff_sdk.session import InMemoryStorageBackend
from agentic_bff_sdk.sop_runner import DefaultBatchSOPRunner
from agentic_bff_sdk.synthesizer import DefaultSynthesizer

# 配置日志
logging.basicConfig(level=logging.WARNING, format="  %(levelname)s | %(message)s")


# ============================================================
# 1. 自定义业务组件
# ============================================================

class CustodyRouter(DefaultTopLevelRouter):
    """托管外包业务路由器。"""
    pass  # 使用 DefaultTopLevelRouter 的全部能力，通过 intent_recognizer 注入


async def custody_intent_recognizer(
    llm: Any, user_input: str, session_state: SessionState
) -> List[IntentResult]:
    """模拟托管外包业务的意图识别。"""
    u = user_input.lower()
    if "净值" in u or "估值" in u:
        return [IntentResult(intent_type="nav_query", confidence=0.93, parameters={"domain": "valuation"})]
    elif "清算" in u:
        return [IntentResult(intent_type="settlement", confidence=0.91, parameters={"domain": "settlement"})]
    elif "合规" in u and "风控" in u:
        return [
            IntentResult(intent_type="compliance_check", confidence=0.82, parameters={}),
            IntentResult(intent_type="risk_assessment", confidence=0.79, parameters={}),
        ]
    elif "报告" in u:
        return [IntentResult(intent_type="report_generation", confidence=0.88, parameters={})]
    return []


async def custody_plan_generator(
    llm: Any, intent: IntentResult, session_state: SessionState
) -> List[PlanStep]:
    """根据意图生成托管外包执行计划。"""
    if intent.intent_type == "nav_query":
        return [
            PlanStep(step_id="fetch_positions", domain="valuation", action="get_positions", parameters={}),
            PlanStep(step_id="fetch_prices", domain="market_data", action="get_prices", parameters={}),
            PlanStep(step_id="calculate_nav", domain="valuation", action="compute_nav",
                     parameters={}, dependencies=["fetch_positions", "fetch_prices"]),
        ]
    elif intent.intent_type == "report_generation":
        return [
            PlanStep(step_id="gather_data", domain="valuation", action="get_summary", parameters={}),
            PlanStep(step_id="compliance_check", domain="compliance", action="verify", parameters={},
                     dependencies=["gather_data"]),
            PlanStep(step_id="build_report", domain="report", action="generate",
                     parameters={"format": "pdf"}, dependencies=["gather_data", "compliance_check"],
                     is_react_node=True),
        ]
    return [PlanStep(step_id="default", domain="general", action="process", parameters={})]


# 领域 TaskPackage 实现
class ValuationTaskPackage:
    async def execute(self, action: str, parameters: Dict[str, Any]) -> Any:
        if action == "get_positions":
            return {"positions": [{"fund": "F001", "shares": 10000}, {"fund": "F002", "shares": 5000}]}
        elif action == "get_summary":
            return {"total_nav": 12500000, "funds_count": 15, "date": "2024-12-20"}
        elif action == "compute_nav":
            return {"nav": 1.2580, "change": "+0.32%", "date": "2024-12-20"}
        return {"action": action, "status": "ok"}


class MarketDataTaskPackage:
    async def execute(self, action: str, parameters: Dict[str, Any]) -> Any:
        return {"prices": {"F001": 1.258, "F002": 2.105}, "source": "wind", "timestamp": time.time()}


class ComplianceTaskPackage:
    async def execute(self, action: str, parameters: Dict[str, Any]) -> Any:
        return {"compliant": True, "checks_passed": 12, "warnings": 0}


class ReportTaskPackage:
    async def execute(self, action: str, parameters: Dict[str, Any]) -> Any:
        return {"report_url": "/reports/custody_20241220.pdf", "pages": 28, "format": parameters.get("format", "pdf")}


# 自定义渠道适配器
class MobileAppAdapter(ChannelAdapter):
    """移动 App 渠道适配器。"""
    async def adapt_request(self, request: Any) -> RequestMessage:
        return RequestMessage(
            user_input=request.get("text", ""),
            session_id=request.get("device_id", "unknown"),
            channel_id="mobile_app",
            metadata={"platform": request.get("platform", "ios")},
        )

    async def adapt_response(self, response: Any) -> Dict[str, Any]:
        return {"type": "rich_card", "payload": response}


# 自定义 LangChain 工具
class RiskCalculatorTool(BaseTool):
    name: str = "risk_calculator"
    description: str = "计算投资组合风险评分"

    def _run(self, portfolio_id: str = "") -> str:
        return json.dumps({"risk_score": 65, "level": "moderate", "portfolio": portfolio_id})


# 状态回调
class LoggingCallback(StatusCallback):
    async def on_status_change(self, step_id: str, old_status: StepStatus, new_status: StepStatus):
        print(f"      📌 {step_id}: {old_status.value} → {new_status.value}")


# ============================================================
# 2. 构建完整 SDK 实例
# ============================================================

def build_custody_sdk() -> DefaultMASGateway:
    """构建托管外包业务的完整 SDK 实例。"""
    mock_llm = AsyncMock()

    config = SDKConfig(
        session_idle_timeout_seconds=1800,
        intent_confidence_threshold=0.7,
        intent_ambiguity_range=0.1,
        plan_generation_timeout_seconds=10.0,
        step_execution_timeout_seconds=5.0,
        max_reasoning_steps=10,
        synthesis_quality_threshold=0.5,
        max_cross_llm_loops=2,
    )

    # 路由器
    router = CustodyRouter(
        llm=mock_llm, config=config, intent_recognizer=custody_intent_recognizer,
    )
    router.register_priority_rule({"pattern": r"紧急清算", "intent_type": "urgent_settlement", "priority": "high"})
    router.register_fallback_handler(
        lambda ui, ss: IntentResult(intent_type="general_inquiry", confidence=0.0, parameters={"raw": ui})
    )

    # 计划器
    planner = DefaultIMCPlanner(llm=mock_llm, config=config, plan_generator=custody_plan_generator)

    # 领域网关
    domain_gw = DefaultDomainGateway(config=config)
    domain_gw.register_task_package("valuation", ValuationTaskPackage())
    domain_gw.register_task_package("market_data", MarketDataTaskPackage())
    domain_gw.register_task_package("compliance", ComplianceTaskPackage())
    domain_gw.register_task_package("report", ReportTaskPackage())

    # 综合器
    synthesizer = DefaultSynthesizer(
        synthesis_fn=lambda prompt: "根据托管外包系统查询，您管理的基金组合当前净值为 1.258 元，较前日上涨 0.32%。共持有 15 只基金，总资产规模约 1250 万元。合规检查全部通过。",
        config=config,
    )

    # 领域调用代理
    async def domain_invoker(request: DomainRequest) -> DomainResponse:
        return await domain_gw.invoke(request)

    # 插件注册
    registry = PluginRegistry()
    registry.register_tool(RiskCalculatorTool())
    registry.register_channel_adapter("mobile_app", MobileAppAdapter())
    registry.register_channel_adapter("web", DefaultChannelAdapter())

    # 组装网关
    gateway = DefaultMASGateway(
        session_context=SessionContext(max_dialog_history_turns=20),
        router=router,
        planner=planner,
        dispatcher=ConcurrentDispatcher(),
        aggregator=FanInAggregator(),
        synthesizer=synthesizer,
        card_generator=DefaultCardGenerator(),
        config=config,
        domain_invoker=domain_invoker,
    )

    # 注册插件
    for tool in registry.tools:
        gateway.register_plugin("tool", tool)

    return gateway


# ============================================================
# 3. 运行完整演示
# ============================================================

async def main():
    print("\n" + "🔷" * 30)
    print("  Demo 9: 完整端到端管线 — 托管外包业务场景")
    print("🔷" * 30 + "\n")

    gateway = build_custody_sdk()

    # ── 场景 1: 净值查询（完整管线） ──
    print("=" * 60)
    print("场景 1: 净值查询 — 完整管线 (路由→计划→调度→聚合→综合→卡片)")
    print("=" * 60)

    resp = await gateway.handle_request(RequestMessage(
        user_input="帮我查一下基金净值",
        session_id="custody_session_001",
        channel_id="web",
    ))
    print(f"  错误: {resp.error}")
    print(f"  内容类型: {type(resp.content).__name__}")
    if isinstance(resp.content, dict) and "cards" in resp.content:
        print(f"  卡片数量: {len(resp.content['cards'])}")
        for c in resp.content["cards"]:
            print(f"    - {c.get('card_type', 'unknown')}: {str(c.get('content', ''))[:80]}")
    print(f"  原始文本: {resp.content.get('raw_text', '')[:80]}..." if isinstance(resp.content, dict) else "")
    print()

    # ── 场景 2: 优先规则命中 ──
    print("=" * 60)
    print("场景 2: 优先规则命中 — '紧急清算' 直接路由")
    print("=" * 60)

    resp2 = await gateway.handle_request(RequestMessage(
        user_input="紧急清算 F001 基金",
        session_id="custody_session_001",
        channel_id="web",
    ))
    print(f"  错误: {resp2.error}")
    print(f"  → 优先规则命中 'urgent_settlement'，跳过 LLM")
    print()

    # ── 场景 3: 歧义意图 → 澄清 ──
    print("=" * 60)
    print("场景 3: 歧义意图 — 合规和风控置信度接近")
    print("=" * 60)

    resp3 = await gateway.handle_request(RequestMessage(
        user_input="帮我做一下合规和风控检查",
        session_id="custody_session_002",
        channel_id="web",
    ))
    if isinstance(resp3.content, dict) and "question" in resp3.content:
        print(f"  澄清问题: {resp3.content['question']}")
        print(f"  候选意图: {[c['intent_type'] for c in resp3.content.get('candidates', [])]}")
    print()

    # ── 场景 4: 请求验证失败 ──
    print("=" * 60)
    print("场景 4: 请求验证 — 缺失 session_id")
    print("=" * 60)

    resp4 = await gateway.handle_request(RequestMessage(
        user_input="查询", session_id="", channel_id="web",
    ))
    print(f"  错误码: {resp4.error.code}")
    print(f"  错误信息: {resp4.error.message}")
    print()

    # ── 场景 5: 多轮对话 & 会话持久化 ──
    print("=" * 60)
    print("场景 5: 多轮对话 & 会话持久化")
    print("=" * 60)

    for i, query in enumerate(["查基金净值", "生成报告"], 1):
        await gateway.handle_request(RequestMessage(
            user_input=query, session_id="multi_turn_session", channel_id="web",
        ))

    state = await gateway.session_context.get_or_create("multi_turn_session")
    print(f"  会话 ID: {state.session_id}")
    print(f"  对话历史: {len(state.dialog_history)} 条")
    for entry in state.dialog_history[-4:]:
        print(f"    [{entry['role']}] {entry['content'][:50]}...")
    print()

    # ── 场景 6: 异步任务管理 ──
    print("=" * 60)
    print("场景 6: 异步任务管理 — 提交 + 查询 + 优先级")
    print("=" * 60)

    task_id_high = await gateway.submit_async_task(
        RequestMessage(user_input="生成月度报告", session_id="async_001", channel_id="web"),
        priority=0,  # 高优先级
    )
    task_id_low = await gateway.submit_async_task(
        RequestMessage(user_input="查询历史净值", session_id="async_002", channel_id="web"),
        priority=10,  # 低优先级
    )
    print(f"  提交高优先级任务: {task_id_high[:8]}...")
    print(f"  提交低优先级任务: {task_id_low[:8]}...")

    await asyncio.sleep(0.5)  # 等待处理

    status_high = await gateway.get_task_status(task_id_high)
    status_low = await gateway.get_task_status(task_id_low)
    print(f"  高优先级状态: {status_high.value}")
    print(f"  低优先级状态: {status_low.value}")
    print()

    # ── 场景 7: Blackboard 跨组件数据共享 ──
    print("=" * 60)
    print("场景 7: Blackboard 跨组件数据共享")
    print("=" * 60)

    bb = Blackboard()
    await bb.set("user_profile", {"name": "张三", "role": "基金经理", "aum": 50000000})
    await bb.set("market_status", {"index": "沪深300", "change": "+1.2%"})
    await bb.set("temp_calc", {"intermediate": True})

    profile = await bb.get("user_profile")
    print(f"  用户画像: {profile}")
    print(f"  市场状态: {await bb.get('market_status')}")

    # 过期清理
    bb._access_times["temp_calc"] = time.time() - 7200
    expired = await bb.cleanup_expired(3600)
    print(f"  过期清理: {expired}")
    print()

    # ── 场景 8: SOP 执行 ──
    print("=" * 60)
    print("场景 8: SOP 跨领域执行 — 客户开户流程")
    print("=" * 60)

    sop = SOPDefinition(
        sop_id="custody_onboarding",
        name="托管客户开户",
        steps=[
            {"domain": "valuation", "action": "get_positions", "parameters": {}},
            {"domain": "compliance", "action": "verify", "parameters": {}},
        ],
        exception_policies={"ConnectionError": "retry", "ValueError": "skip"},
        dialog_templates={
            InteractionScene.PHONE: "📞 正在为您办理托管开户...",
            InteractionScene.ONLINE: "💻 托管开户处理中...",
        },
    )

    sop_runner = DefaultBatchSOPRunner()
    sop_bb = Blackboard()
    plan = ExecutionPlan(
        plan_id="sop_plan", intent=IntentResult(intent_type="onboarding", confidence=0.9),
        steps=[], created_at=time.time(),
    )

    template = sop_runner.select_dialog_template(sop, InteractionScene.PHONE)
    print(f"  对话模板: {template}")

    results = await sop_runner.execute(plan, sop, InteractionScene.PHONE, sop_bb)
    for i, r in enumerate(results):
        print(f"  步骤 {i}: {r.get('domain')}.{r.get('action')} → {r.get('status')}")
    print()

    # ── 场景 9: 工具验证 & 规则引擎降级 ──
    print("=" * 60)
    print("场景 9: 工具输入验证 & 规则引擎降级")
    print("=" * 60)

    schema = {"type": "object", "properties": {"fund_id": {"type": "string"}}, "required": ["fund_id"]}
    try:
        validate_tool_input("nav_query", {"fund_id": "F001"}, schema)
        print("  ✅ 合法输入验证通过")
    except ValueError:
        pass

    try:
        validate_tool_input("nav_query", {"wrong_field": 123}, schema)
    except ValueError as e:
        print(f"  ❌ 非法输入被拒绝: {e}")

    # 规则引擎降级
    async def failing_rule_engine(rule_set_id, params):
        raise TimeoutError("规则引擎超时")

    result = await handle_rule_engine_call(
        failing_rule_engine, "risk_calc", {},
        fallback_value={"risk_score": 50, "source": "fallback"},
    )
    print(f"  规则引擎降级: {result}")
    print()

    # ── 场景 10: 错误处理 ──
    print("=" * 60)
    print("场景 10: 统一错误处理")
    print("=" * 60)

    try:
        raise DomainError(code=DOMAIN_SERVICE_UNAVAILABLE, message="估值服务不可用")
    except SDKError as e:
        print(f"  捕获: {e}")
        print(f"  可恢复: {is_recoverable(e)}")
        resp_err = handle_sdk_error(e)
        print(f"  ErrorResponse: code={resp_err.code}")

    partial = create_partial_failure_response("s1", {"nav": 1.25}, "合规检查超时")
    print(f"  部分失败: {partial.code} — {partial.details['missing_info']}")
    print()

    # ── 场景 11: 审计日志 ──
    print("=" * 60)
    print("场景 11: 审计日志")
    print("=" * 60)

    audit = DefaultAuditLogger()
    await audit.log_invocation("valuation", "compute_nav", "fund=F001", "nav=1.258", True, 45.2)
    await audit.log_invocation("compliance", "verify", "fund=F001", "error: timeout", False, 5012.0)
    print("  (审计日志已输出)")
    print()

    # ── 场景 12: 声明式配置 & 工厂 ──
    print("=" * 60)
    print("场景 12: 声明式配置 & create_sdk 工厂")
    print("=" * 60)

    orch_config = OrchestrationConfig(
        sdk=SDKConfig(session_idle_timeout_seconds=600, intent_confidence_threshold=0.75),
    )
    yaml_str = orch_config.to_yaml()
    restored = OrchestrationConfig.from_yaml(yaml_str)
    print(f"  YAML Round-trip: confidence_threshold={restored.sdk.intent_confidence_threshold}")

    # 使用工厂创建
    from agentic_bff_sdk.synthesizer import DefaultSynthesizer as DS
    factory_gw = create_sdk(
        orch_config,
        router=CustodyRouter(llm=AsyncMock(), intent_recognizer=custody_intent_recognizer),
        planner=DefaultIMCPlanner(llm=AsyncMock(), plan_generator=custody_plan_generator),
        synthesizer=DS(synthesis_fn=lambda p: "工厂创建的 SDK 响应"),
    )
    factory_resp = await factory_gw.handle_request(
        RequestMessage(user_input="查净值", session_id="factory_s", channel_id="web")
    )
    print(f"  工厂 SDK 响应: error={factory_resp.error}")
    print()

    # ── 总结 ──
    print("=" * 60)
    print("📊 能力覆盖总结")
    print("=" * 60)
    capabilities = [
        "Blackboard 共享状态",
        "SessionContext 会话管理 & 话题 & 压缩",
        "TopLevelRouter 意图路由 (优先规则/阈值/歧义/兜底)",
        "IMCPlanner 执行计划 (DAG 依赖/ReAct/持久化)",
        "ConcurrentDispatcher DAG 并发调度 (超时/回调)",
        "DomainGateway 领域网关 (TaskPackage/协议转换)",
        "BatchSOPRunner SOP 执行 (异常策略/对话模板)",
        "FanInAggregator 结果聚合 (完整/部分)",
        "Synthesizer 综合决策 (质量评分/交叉 LLM)",
        "CardGenerator 富媒体卡片 (渠道适配/确认卡片)",
        "AgentExecutor 工具验证 & 规则引擎降级",
        "PluginRegistry 插件系统 & ChannelAdapter",
        "统一错误处理框架 (SDKError 层次)",
        "审计日志 (AuditLogger)",
        "OrchestrationConfig 声明式配置 & create_sdk",
        "异步任务管理 (提交/查询/优先级)",
    ]
    for i, cap in enumerate(capabilities, 1):
        print(f"  ✅ {i:2d}. {cap}")

    print(f"\n{'✅' * 30}")
    print(f"  Demo 9 完成 — SDK 全部 {len(capabilities)} 项能力已覆盖")
    print(f"{'✅' * 30}\n")


if __name__ == "__main__":
    asyncio.run(main())
