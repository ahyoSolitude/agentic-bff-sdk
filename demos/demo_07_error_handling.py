#!/usr/bin/env python3
"""Demo 7: 统一错误处理框架

展示能力：
- SDKError 基类与异常层次结构
- 错误码常量（REQ_, SESSION_, ROUTE_, PLAN_, DISPATCH_, DOMAIN_, RULE_, AGG_, SYNTH_, SYS_）
- to_error_response() 转换为 ErrorResponse
- is_recoverable() 判断可恢复性
- create_partial_failure_response() 部分失败响应
- handle_rule_engine_call() 规则引擎降级策略
"""

import asyncio

from agentic_bff_sdk.errors import (
    # 错误码常量
    REQ_MISSING_SESSION_ID,
    SESSION_EXPIRED,
    ROUTE_NO_INTENT,
    PLAN_GENERATION_TIMEOUT,
    DISPATCH_CYCLE_DETECTED,
    DOMAIN_SERVICE_UNAVAILABLE,
    RULE_ENGINE_TIMEOUT,
    AGG_PARTIAL_RESULTS,
    SYNTH_QUALITY_LOW,
    SYS_INTERNAL_ERROR,
    # 异常类
    SDKError,
    RequestValidationError,
    SessionError,
    RoutingError,
    PlanningError,
    DispatchError,
    DomainError,
    RuleEngineError,
    AggregationError,
    SynthesisError,
    SystemError,
    # 工具函数
    handle_sdk_error,
    is_recoverable,
    create_partial_failure_response,
)
from agentic_bff_sdk.agent_executor import handle_rule_engine_call


async def demo_error_hierarchy():
    print("=" * 60)
    print("7.1 异常层次结构")
    print("=" * 60)

    errors = [
        RequestValidationError(code=REQ_MISSING_SESSION_ID, message="缺少 session_id"),
        SessionError(code=SESSION_EXPIRED, message="会话已过期"),
        RoutingError(code=ROUTE_NO_INTENT, message="无法识别意图"),
        PlanningError(code=PLAN_GENERATION_TIMEOUT, message="计划生成超时"),
        DispatchError(code=DISPATCH_CYCLE_DETECTED, message="检测到循环依赖"),
        DomainError(code=DOMAIN_SERVICE_UNAVAILABLE, message="领域服务不可用"),
        RuleEngineError(code=RULE_ENGINE_TIMEOUT, message="规则引擎超时"),
        AggregationError(code=AGG_PARTIAL_RESULTS, message="部分结果缺失"),
        SynthesisError(code=SYNTH_QUALITY_LOW, message="综合质量不达标"),
        SystemError(code=SYS_INTERNAL_ERROR, message="内部系统错误"),
    ]

    for err in errors:
        recoverable = "✅ 可恢复" if err.recoverable else "❌ 不可恢复"
        print(f"  [{err.code}] {err.message} — {recoverable}")
    print()


async def demo_error_conversion():
    print("=" * 60)
    print("7.2 错误转换为 ErrorResponse")
    print("=" * 60)

    err = DomainError(
        code=DOMAIN_SERVICE_UNAVAILABLE,
        message="基金服务暂时不可用",
        details={"domain": "fund", "retry_after_seconds": 30},
    )

    # 转换为 ErrorResponse
    resp = err.to_error_response()
    print(f"  ErrorResponse:")
    print(f"    code: {resp.code}")
    print(f"    message: {resp.message}")
    print(f"    details: {resp.details}")

    # 使用工具函数
    resp2 = handle_sdk_error(err)
    print(f"\n  handle_sdk_error() 结果相同: {resp2.code == resp.code}")
    print()


async def demo_recoverable_check():
    print("=" * 60)
    print("7.3 可恢复性判断")
    print("=" * 60)

    test_cases = [
        RequestValidationError(),
        SessionError(),
        DomainError(),
        DispatchError(),
        SystemError(),
    ]

    for err in test_cases:
        result = is_recoverable(err)
        action = "重试/降级" if result else "直接返回错误"
        print(f"  {type(err).__name__}: recoverable={result} → {action}")
    print()


async def demo_partial_failure():
    print("=" * 60)
    print("7.4 部分失败响应")
    print("=" * 60)

    resp = create_partial_failure_response(
        session_id="sess_001",
        partial_content={"fund_nav": 1.25},
        missing_info="资产查询步骤超时",
    )
    print(f"  code: {resp.code}")
    print(f"  message: {resp.message}")
    print(f"  details: {resp.details}")
    print()


async def demo_rule_engine_degradation():
    print("=" * 60)
    print("7.5 规则引擎降级策略")
    print("=" * 60)

    # 成功调用
    async def ok_engine(rule_set_id, params):
        return {"risk_score": 72}

    result = await handle_rule_engine_call(ok_engine, "risk_calc", {"user": "u1"})
    print(f"  正常调用: {result}")

    # 失败 + 有降级值
    async def failing_engine(rule_set_id, params):
        raise TimeoutError("规则引擎超时")

    result = await handle_rule_engine_call(
        failing_engine, "risk_calc", {"user": "u1"},
        fallback_value={"risk_score": 50, "source": "fallback"},
    )
    print(f"  超时 + 降级: {result}")

    # 失败 + 无降级值 → 抛异常
    try:
        await handle_rule_engine_call(failing_engine, "risk_calc", {"user": "u1"}, fallback_value=None)
    except RuntimeError as e:
        print(f"  超时 + 无降级: RuntimeError — {e}")
    print()


async def demo_exception_catching():
    print("=" * 60)
    print("7.6 异常捕获示例")
    print("=" * 60)

    try:
        # 模拟业务代码抛出 SDK 异常
        raise DomainError(
            code=DOMAIN_SERVICE_UNAVAILABLE,
            message="基金服务不可用",
            details={"domain": "fund"},
        )
    except SDKError as e:
        # 统一捕获所有 SDK 异常
        if is_recoverable(e):
            print(f"  捕获可恢复错误: {e}")
            print(f"  → 执行重试或降级策略")
        else:
            resp = handle_sdk_error(e)
            print(f"  捕获不可恢复错误: {e}")
            print(f"  → 返回 ErrorResponse: {resp.code}")
    print()


async def main():
    print("\n🔷 Demo 7: 统一错误处理框架\n")
    await demo_error_hierarchy()
    await demo_error_conversion()
    await demo_recoverable_check()
    await demo_partial_failure()
    await demo_rule_engine_degradation()
    await demo_exception_catching()
    print("✅ Demo 7 完成\n")


if __name__ == "__main__":
    asyncio.run(main())
