#!/usr/bin/env python3
"""Demo 5: BatchSOPRunner 跨领域 SOP 执行

展示能力：
- SOPDefinition 定义（步骤、异常策略、对话模板）
- InteractionScene 交互场景对话模板选择
- 异常处理策略：retry / skip / rollback
- 步骤结果写入 Blackboard
"""

import asyncio
from typing import Any, Dict

from agentic_bff_sdk import (
    Blackboard,
    ExecutionPlan,
    IntentResult,
    InteractionScene,
    PlanStep,
    SOPDefinition,
)
from agentic_bff_sdk.sop_runner import DefaultBatchSOPRunner

import time


def make_plan() -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="sop_plan", intent=IntentResult(intent_type="onboarding", confidence=0.9),
        steps=[], created_at=time.time(),
    )


# ============================================================
# 模拟步骤执行器
# ============================================================
call_count: Dict[str, int] = {}


async def simulated_step_executor(
    domain: str, action: str, parameters: Dict[str, Any], blackboard: Blackboard,
) -> Dict[str, Any]:
    """模拟领域调用，部分步骤会失败。"""
    key = f"{domain}.{action}"
    call_count[key] = call_count.get(key, 0) + 1

    if domain == "kyc" and action == "verify_identity":
        # 第一次调用失败，第二次成功（模拟 retry 场景）
        if call_count[key] <= 1:
            raise ConnectionError("KYC 服务暂时不可用")
        return {"domain": domain, "action": action, "status": "completed", "data": {"verified": True}}

    if domain == "compliance" and action == "check_sanctions":
        raise ValueError("合规检查数据格式错误")

    if domain == "risk" and action == "assess":
        raise RuntimeError("风控系统严重故障")

    return {"domain": domain, "action": action, "status": "completed", "data": {"result": "ok"}}


async def demo_sop_execution():
    print("=" * 60)
    print("5.1 SOP 执行（含异常策略）")
    print("=" * 60)

    sop = SOPDefinition(
        sop_id="customer_onboarding",
        name="客户开户 SOP",
        steps=[
            {"domain": "account", "action": "create_account", "parameters": {"type": "individual"}},
            {"domain": "kyc", "action": "verify_identity", "parameters": {"doc_type": "id_card"}},
            {"domain": "compliance", "action": "check_sanctions", "parameters": {}},
            {"domain": "notification", "action": "send_welcome", "parameters": {"channel": "sms"}},
        ],
        exception_policies={
            "ConnectionError": "retry",   # KYC 连接失败 → 重试
            "ValueError": "skip",         # 合规格式错误 → 跳过
            "RuntimeError": "rollback",   # 风控故障 → 回滚（这里不会触发，因为 risk 不在步骤中）
        },
        dialog_templates={
            InteractionScene.PHONE: "您好，我是客服小王，正在为您办理{step}...",
            InteractionScene.ONLINE: "正在处理: {step}",
            InteractionScene.FACE_TO_FACE: "请稍等，我正在为您办理{step}...",
        },
    )

    runner = DefaultBatchSOPRunner(step_executor=simulated_step_executor)
    bb = Blackboard()
    plan = make_plan()

    print(f"  SOP: {sop.name} ({len(sop.steps)} 步)")
    print(f"  异常策略: {sop.exception_policies}")
    print()

    results = await runner.execute(plan, sop, InteractionScene.PHONE, bb)

    print("  执行结果:")
    for i, r in enumerate(results):
        status = r.get("status", "unknown")
        policy = r.get("policy_applied", "")
        error = r.get("error", "")
        domain = r.get("domain", "")
        action = r.get("action", "")
        extra = f" [策略: {policy}]" if policy else ""
        err_info = f" (错误: {error})" if error else ""
        print(f"    步骤 {i}: {domain}.{action} → {status}{extra}{err_info}")
    print()


async def demo_dialog_templates():
    print("=" * 60)
    print("5.2 交互场景对话模板")
    print("=" * 60)

    sop = SOPDefinition(
        sop_id="demo_sop",
        name="Demo SOP",
        steps=[],
        exception_policies={},
        dialog_templates={
            InteractionScene.PHONE: "📞 电话场景: 您好，正在为您处理...",
            InteractionScene.ONLINE: "💻 在线场景: 处理中，请稍候...",
            InteractionScene.FACE_TO_FACE: "🤝 面谈场景: 请稍等片刻...",
        },
    )

    runner = DefaultBatchSOPRunner()

    for scene in InteractionScene:
        template = runner.select_dialog_template(sop, scene)
        print(f"  {scene.value}: {template}")
    print()


async def demo_blackboard_results():
    print("=" * 60)
    print("5.3 步骤结果写入 Blackboard")
    print("=" * 60)

    sop = SOPDefinition(
        sop_id="bb_demo",
        name="Blackboard Demo",
        steps=[
            {"domain": "service_a", "action": "fetch_data", "parameters": {}},
            {"domain": "service_b", "action": "process", "parameters": {}},
        ],
        exception_policies={},
        dialog_templates={},
    )

    runner = DefaultBatchSOPRunner()  # 使用默认执行器
    bb = Blackboard()
    plan = make_plan()

    await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

    # 从 Blackboard 读取步骤结果
    for i in range(2):
        key = f"sop_bb_demo_step_{i}"
        value = await bb.get(key)
        print(f"  Blackboard['{key}'] = {value}")
    print()


async def main():
    print("\n🔷 Demo 5: BatchSOPRunner 跨领域 SOP 执行\n")
    await demo_dialog_templates()
    await demo_sop_execution()
    await demo_blackboard_results()
    print("✅ Demo 5 完成\n")


if __name__ == "__main__":
    asyncio.run(main())
