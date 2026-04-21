#!/usr/bin/env python3
"""Demo 3: IMCPlanner 执行计划 & ConcurrentDispatcher DAG 并发调度

展示能力：
- IMCPlanner 执行计划生成（自定义 plan_generator）
- 步骤依赖关系与 ReAct 节点标注
- 执行计划持久化与加载
- ConcurrentDispatcher DAG 循环检测
- DAG 并发调度（无依赖步骤并发执行）
- 步骤超时处理
- StatusCallback 状态变更通知
"""

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock

from agentic_bff_sdk import (
    DomainRequest,
    DomainResponse,
    ExecutionPlan,
    IntentResult,
    PlanStep,
    SDKConfig,
    SessionState,
    StepResult,
    StepStatus,
)
from agentic_bff_sdk.dispatcher import ConcurrentDispatcher, StatusCallback
from agentic_bff_sdk.planner import DefaultIMCPlanner


def make_session() -> SessionState:
    now = time.time()
    return SessionState(session_id="demo", dialog_history=[], created_at=now, last_active_at=now)


# ============================================================
# 自定义 plan_generator：模拟 CoT 推理生成执行计划
# ============================================================
async def wealth_plan_generator(
    llm: Any, intent: IntentResult, session_state: SessionState
) -> List[PlanStep]:
    """模拟为「综合理财查询」生成 DAG 执行计划。

    DAG 结构:
        query_fund ──┐
                     ├──► aggregate_results ──► generate_report
        query_asset ─┘
    """
    return [
        PlanStep(step_id="query_fund", domain="fund", action="query_nav",
                 parameters={"fund_id": "F001"}, dependencies=[]),
        PlanStep(step_id="query_asset", domain="asset", action="query_total",
                 parameters={"account": "main"}, dependencies=[]),
        PlanStep(step_id="aggregate_results", domain="analytics", action="merge",
                 parameters={}, dependencies=["query_fund", "query_asset"]),
        PlanStep(step_id="generate_report", domain="report", action="build",
                 parameters={"format": "pdf"}, dependencies=["aggregate_results"],
                 is_react_node=True),
    ]


# ============================================================
# 模拟领域调用
# ============================================================
async def mock_domain_invoker(request: DomainRequest) -> DomainResponse:
    """模拟各领域微服务调用。"""
    await asyncio.sleep(0.05)  # 模拟网络延迟
    data_map = {
        "fund": {"fund_name": "成长基金", "nav": 1.25},
        "asset": {"total_assets": 500000, "currency": "CNY"},
        "analytics": {"merged": True, "items": 2},
        "report": {"report_url": "/reports/2024-001.pdf"},
    }
    return DomainResponse(
        request_id=request.request_id,
        domain=request.domain,
        success=True,
        data=data_map.get(request.domain, {"result": "ok"}),
    )


# ============================================================
# StatusCallback 实现
# ============================================================
class PrintingCallback(StatusCallback):
    """打印每次状态变更。"""
    async def on_status_change(self, step_id: str, old_status: StepStatus, new_status: StepStatus):
        print(f"    📌 {step_id}: {old_status.value} → {new_status.value}")


async def demo_plan_generation():
    print("=" * 60)
    print("3.1 执行计划生成与持久化")
    print("=" * 60)

    mock_llm = AsyncMock()
    planner = DefaultIMCPlanner(llm=mock_llm, plan_generator=wealth_plan_generator)

    intent = IntentResult(intent_type="wealth_query", confidence=0.95, parameters={})
    session = make_session()

    plan = await planner.generate_plan(intent, session, timeout_seconds=5.0)
    print(f"  计划 ID: {plan.plan_id[:8]}...")
    print(f"  步骤数: {len(plan.steps)}")
    for step in plan.steps:
        react_tag = " [ReAct]" if step.is_react_node else ""
        deps = f" (依赖: {step.dependencies})" if step.dependencies else ""
        print(f"    {step.step_id}: {step.domain}.{step.action}{deps}{react_tag}")

    # 持久化
    plan_id = await planner.persist_plan(plan)
    loaded = await planner.load_plan(plan_id)
    print(f"\n  持久化后加载: plan_id={loaded.plan_id[:8]}..., 步骤数={len(loaded.steps)}")
    print()


async def demo_dag_validation():
    print("=" * 60)
    print("3.2 DAG 循环依赖检测")
    print("=" * 60)

    dispatcher = ConcurrentDispatcher()

    # 有效 DAG
    valid_plan = ExecutionPlan(
        plan_id="valid", intent=IntentResult(intent_type="t", confidence=0.9),
        steps=[
            PlanStep(step_id="a", domain="d", action="a", dependencies=[]),
            PlanStep(step_id="b", domain="d", action="b", dependencies=["a"]),
        ],
        created_at=time.time(),
    )
    cycle = dispatcher.validate_dag(valid_plan)
    print(f"  有效 DAG (a→b): 循环={cycle}")

    # 含循环的 DAG
    cyclic_plan = ExecutionPlan(
        plan_id="cyclic", intent=IntentResult(intent_type="t", confidence=0.9),
        steps=[
            PlanStep(step_id="x", domain="d", action="a", dependencies=["z"]),
            PlanStep(step_id="y", domain="d", action="b", dependencies=["x"]),
            PlanStep(step_id="z", domain="d", action="c", dependencies=["y"]),
        ],
        created_at=time.time(),
    )
    cycle = dispatcher.validate_dag(cyclic_plan)
    print(f"  循环 DAG (x→y→z→x): 循环路径={cycle}")
    print()


async def demo_concurrent_dispatch():
    print("=" * 60)
    print("3.3 DAG 并发调度（含状态回调）")
    print("=" * 60)

    mock_llm = AsyncMock()
    planner = DefaultIMCPlanner(llm=mock_llm, plan_generator=wealth_plan_generator)
    dispatcher = ConcurrentDispatcher()
    callback = PrintingCallback()

    intent = IntentResult(intent_type="wealth_query", confidence=0.95, parameters={})
    plan = await planner.generate_plan(intent, make_session())

    print("  开始调度:")
    start = time.monotonic()
    results = await dispatcher.dispatch(
        plan, mock_domain_invoker, step_timeout_seconds=2.0, callback=callback,
    )
    elapsed = (time.monotonic() - start) * 1000

    print(f"\n  调度完成 ({elapsed:.0f}ms):")
    for r in results:
        print(f"    {r.step_id}: {r.status.value} ({r.duration_ms:.0f}ms) → {r.result}")
    print()


async def demo_timeout_handling():
    print("=" * 60)
    print("3.4 步骤超时处理")
    print("=" * 60)

    async def slow_invoker(request: DomainRequest) -> DomainResponse:
        if request.domain == "slow_service":
            await asyncio.sleep(10)  # 模拟超慢服务
        return DomainResponse(request_id=request.request_id, domain=request.domain, success=True, data="ok")

    plan = ExecutionPlan(
        plan_id="timeout_test",
        intent=IntentResult(intent_type="t", confidence=0.9),
        steps=[
            PlanStep(step_id="fast", domain="fast_service", action="ping", dependencies=[]),
            PlanStep(step_id="slow", domain="slow_service", action="heavy_compute", dependencies=[]),
        ],
        created_at=time.time(),
    )

    dispatcher = ConcurrentDispatcher()
    results = await dispatcher.dispatch(plan, slow_invoker, step_timeout_seconds=0.1)

    for r in results:
        print(f"  {r.step_id}: {r.status.value}" + (f" (error: {r.error})" if r.error else ""))
    print("  → fast 正常完成，slow 超时但不影响 fast")
    print()


async def main():
    print("\n🔷 Demo 3: IMCPlanner & ConcurrentDispatcher\n")
    await demo_plan_generation()
    await demo_dag_validation()
    await demo_concurrent_dispatch()
    await demo_timeout_handling()
    print("✅ Demo 3 完成\n")


if __name__ == "__main__":
    asyncio.run(main())
