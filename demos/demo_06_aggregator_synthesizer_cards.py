#!/usr/bin/env python3
"""Demo 6: FanInAggregator + Synthesizer + CardGenerator

展示能力：
- FanInAggregator 结果聚合（完整/部分）
- DefaultSynthesizer 综合决策（含质量评分、交叉 LLM 回路）
- DefaultCardGenerator 富媒体卡片生成
- 渠道能力适配（过滤不支持的卡片类型）
- 确认操作交互卡片
"""

import asyncio
import time
from typing import Any, Dict, List

from agentic_bff_sdk import (
    AggregatedResult,
    Card,
    CardOutput,
    CardType,
    SDKConfig,
    SessionState,
    StepResult,
    StepStatus,
    SynthesisResult,
)
from agentic_bff_sdk.aggregator import FanInAggregator
from agentic_bff_sdk.card_generator import DefaultCardGenerator
from agentic_bff_sdk.synthesizer import DefaultSynthesizer


def make_session() -> SessionState:
    now = time.time()
    return SessionState(session_id="demo", dialog_history=[], created_at=now, last_active_at=now)


async def demo_aggregation():
    print("=" * 60)
    print("6.1 FanInAggregator 结果聚合")
    print("=" * 60)

    aggregator = FanInAggregator()

    # 完整聚合
    results_complete = [
        StepResult(step_id="s1", status=StepStatus.COMPLETED, result={"fund": "成长基金", "nav": 1.25}, duration_ms=50),
        StepResult(step_id="s2", status=StepStatus.COMPLETED, result={"total_assets": 500000}, duration_ms=80),
    ]
    agg = await aggregator.aggregate(results_complete, expected_steps=["s1", "s2"])
    print(f"  完整聚合: is_partial={agg.is_partial}, missing={agg.missing_steps}, results={len(agg.results)}")

    # 部分聚合（s3 缺失）
    agg_partial = await aggregator.aggregate(results_complete, expected_steps=["s1", "s2", "s3"])
    print(f"  部分聚合: is_partial={agg_partial.is_partial}, missing={agg_partial.missing_steps}")

    # 含失败步骤的聚合
    results_mixed = [
        StepResult(step_id="s1", status=StepStatus.COMPLETED, result={"data": "ok"}, duration_ms=50),
        StepResult(step_id="s2", status=StepStatus.FAILED, error="service down", duration_ms=100),
        StepResult(step_id="s3", status=StepStatus.TIMEOUT, error="timed out", duration_ms=5000),
    ]
    agg_mixed = await aggregator.aggregate(results_mixed, expected_steps=["s1", "s2", "s3"])
    print(f"  混合聚合: is_partial={agg_mixed.is_partial}, results={len(agg_mixed.results)}")
    print(f"    (失败/超时步骤仍计入结果，不算 missing)")
    print()


async def demo_synthesis():
    print("=" * 60)
    print("6.2 Synthesizer 综合决策")
    print("=" * 60)

    # 使用 synthesis_fn 替代真实 LLM
    call_count = [0]

    def mock_synthesis(prompt: str) -> str:
        call_count[0] += 1
        if call_count[0] == 1:
            return ""  # 第一次返回空（质量低，触发重试）
        return "根据查询结果，您持有的成长基金当前净值为 1.25 元，总资产约 50 万元。建议关注近期市场波动。"

    config = SDKConfig(max_cross_llm_loops=3, synthesis_quality_threshold=0.5)
    synthesizer = DefaultSynthesizer(synthesis_fn=mock_synthesis, config=config)

    aggregated = AggregatedResult(
        results=[
            StepResult(step_id="s1", status=StepStatus.COMPLETED, result={"nav": 1.25}, duration_ms=50),
        ],
        missing_steps=[],
        is_partial=False,
    )

    result = await synthesizer.synthesize(aggregated, make_session(), quality_threshold=0.5)
    print(f"  综合结果: {result.text_response[:60]}...")
    print(f"  质量评分: {result.quality_score:.2f}")
    print(f"  LLM 调用次数: {call_count[0]} (首次质量低，触发了交叉 LLM 重试)")
    print()

    # 含规则引擎输出的综合
    print("  --- 含规则引擎输出 ---")
    aggregated_with_rules = AggregatedResult(
        results=[
            StepResult(step_id="s1", status=StepStatus.COMPLETED,
                       result={"rule_engine_output": {"risk_score": 72, "recommendation": "moderate"}},
                       duration_ms=50),
        ],
        missing_steps=[], is_partial=False,
    )
    call_count[0] = 1  # 跳过空响应
    result2 = await synthesizer.synthesize(aggregated_with_rules, make_session())
    print(f"  structured_data: {result2.structured_data}")
    print()


async def demo_card_generation():
    print("=" * 60)
    print("6.3 CardGenerator 富媒体卡片生成")
    print("=" * 60)

    generator = DefaultCardGenerator()

    # 基础文本卡片
    synthesis = SynthesisResult(text_response="您的基金净值为 1.25 元", quality_score=0.9)
    output = await generator.generate(synthesis, {"supported_card_types": list(CardType)})
    print(f"  基础文本: {len(output.cards)} 张卡片")
    for c in output.cards:
        print(f"    - {c.card_type.value}: {c.content}")

    print()

    # 含结构化数据 → TABLE + CHART
    synthesis_rich = SynthesisResult(
        text_response="资产配置概览",
        structured_data={
            "equity": 45, "bond": 30, "cash": 15,
            "chart_data": {"labels": ["股票", "债券", "现金"], "values": [45, 30, 15]},
        },
        quality_score=0.85,
    )
    output_rich = await generator.generate(synthesis_rich, {"supported_card_types": list(CardType)})
    print(f"  富媒体: {len(output_rich.cards)} 张卡片")
    for c in output_rich.cards:
        print(f"    - {c.card_type.value}")

    print()

    # 确认操作卡片
    synthesis_confirm = SynthesisResult(
        text_response="确认转账 10,000 元到理财账户？",
        requires_confirmation=True,
        confirmation_actions=[
            {"label": "确认转账", "action": "confirm_transfer"},
            {"label": "取消", "action": "cancel"},
        ],
        quality_score=0.9,
    )
    output_confirm = await generator.generate(synthesis_confirm, {"supported_card_types": list(CardType)})
    print(f"  确认操作: {len(output_confirm.cards)} 张卡片")
    for c in output_confirm.cards:
        print(f"    - {c.card_type.value}: actions={c.actions}")

    print()


async def demo_channel_adaptation():
    print("=" * 60)
    print("6.4 渠道能力适配")
    print("=" * 60)

    generator = DefaultCardGenerator()
    synthesis = SynthesisResult(
        text_response="资产报告",
        structured_data={"total": 500000},
        requires_confirmation=True,
        confirmation_actions=[{"label": "OK", "action": "confirm"}],
        quality_score=0.9,
    )

    # Web 渠道：支持所有类型
    web_output = await generator.generate(synthesis, {"supported_card_types": list(CardType)})
    print(f"  Web 渠道 (全部支持): {[c.card_type.value for c in web_output.cards]}")

    # SMS 渠道：仅支持 TEXT
    sms_output = await generator.generate(synthesis, {"supported_card_types": [CardType.TEXT]})
    print(f"  SMS 渠道 (仅 TEXT): {[c.card_type.value for c in sms_output.cards]}")

    # 无限制渠道
    any_output = await generator.generate(synthesis, {})
    print(f"  无限制渠道: {[c.card_type.value for c in any_output.cards]}")
    print()


async def main():
    print("\n🔷 Demo 6: Aggregator + Synthesizer + CardGenerator\n")
    await demo_aggregation()
    await demo_synthesis()
    await demo_card_generation()
    await demo_channel_adaptation()
    print("✅ Demo 6 完成\n")


if __name__ == "__main__":
    asyncio.run(main())
