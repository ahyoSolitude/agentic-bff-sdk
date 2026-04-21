#!/usr/bin/env python3
"""Demo 2: TopLevelRouter 意图路由

展示能力：
- 自定义意图识别器（替代真实 LLM）
- 优先匹配规则（关键词/正则）
- 置信度阈值判断 → 触发澄清
- 歧义意图检测 → 返回候选列表
- 兜底路由处理
"""

import asyncio
import time
from typing import Any, List
from unittest.mock import AsyncMock

from agentic_bff_sdk import (
    ClarificationQuestion,
    IntentResult,
    SDKConfig,
    SessionState,
)
from agentic_bff_sdk.router import DefaultTopLevelRouter


def make_session() -> SessionState:
    now = time.time()
    return SessionState(
        session_id="demo_session",
        dialog_history=[],
        created_at=now,
        last_active_at=now,
    )


# 模拟意图识别器：根据关键词返回不同的意图候选
async def mock_intent_recognizer(
    llm: Any, user_input: str, session_state: SessionState
) -> List[IntentResult]:
    """模拟 LLM 意图识别，根据输入关键词返回候选意图。"""
    input_lower = user_input.lower()

    if "基金" in input_lower:
        return [
            IntentResult(intent_type="fund_query", confidence=0.92, parameters={"domain": "fund"}),
            IntentResult(intent_type="fund_purchase", confidence=0.45, parameters={}),
        ]
    elif "转账" in input_lower and "理财" in input_lower:
        # 歧义场景：两个意图置信度接近
        return [
            IntentResult(intent_type="transfer", confidence=0.78, parameters={}),
            IntentResult(intent_type="wealth_mgmt", confidence=0.75, parameters={}),
        ]
    elif "天气" in input_lower:
        # 低置信度场景
        return [
            IntentResult(intent_type="weather", confidence=0.3, parameters={}),
        ]
    else:
        return []  # 无法识别


async def main():
    print("\n🔷 Demo 2: TopLevelRouter 意图路由\n")

    mock_llm = AsyncMock()
    config = SDKConfig(
        intent_confidence_threshold=0.7,
        intent_ambiguity_range=0.1,
    )
    router = DefaultTopLevelRouter(
        llm=mock_llm,
        config=config,
        intent_recognizer=mock_intent_recognizer,
    )

    session = make_session()

    # --- 2.1 优先匹配规则 ---
    print("=" * 60)
    print("2.1 优先匹配规则")
    print("=" * 60)
    router.register_priority_rule({"pattern": r"余额", "intent_type": "check_balance"})
    router.register_priority_rule({"pattern": r"开户", "intent_type": "open_account", "channel": "online"})

    result = await router.route("查一下我的余额", session)
    print(f"  输入: '查一下我的余额'")
    print(f"  结果: IntentResult(type={result.intent_type}, confidence={result.confidence})")
    print(f"  → 优先规则命中，跳过 LLM，置信度 1.0")
    print()

    # --- 2.2 正常意图识别 ---
    print("=" * 60)
    print("2.2 正常意图识别（高置信度）")
    print("=" * 60)
    result = await router.route("帮我查一下基金净值", session)
    print(f"  输入: '帮我查一下基金净值'")
    if isinstance(result, IntentResult):
        print(f"  结果: IntentResult(type={result.intent_type}, confidence={result.confidence:.2f})")
        print(f"  参数: {result.parameters}")
    print()

    # --- 2.3 歧义意图检测 ---
    print("=" * 60)
    print("2.3 歧义意图检测")
    print("=" * 60)
    result = await router.route("我想转账到理财账户", session)
    print(f"  输入: '我想转账到理财账户'")
    if isinstance(result, ClarificationQuestion):
        print(f"  结果: ClarificationQuestion")
        print(f"  问题: {result.question}")
        print(f"  候选意图:")
        for c in result.candidates:
            print(f"    - {c.intent_type} (confidence={c.confidence:.2f})")
    print()

    # --- 2.4 低置信度触发澄清 ---
    print("=" * 60)
    print("2.4 低置信度触发澄清")
    print("=" * 60)
    result = await router.route("今天天气怎么样", session)
    print(f"  输入: '今天天气怎么样'")
    if isinstance(result, ClarificationQuestion):
        print(f"  结果: ClarificationQuestion")
        print(f"  问题: {result.question}")
        print(f"  候选: {[f'{c.intent_type}({c.confidence:.2f})' for c in result.candidates]}")
    print()

    # --- 2.5 兜底路由 ---
    print("=" * 60)
    print("2.5 兜底路由")
    print("=" * 60)

    def fallback_handler(user_input, session_state):
        return IntentResult(intent_type="fallback_chitchat", confidence=0.0, parameters={"raw": user_input})

    router.register_fallback_handler(fallback_handler)
    result = await router.route("啊啊啊随便说点什么", session)
    print(f"  输入: '啊啊啊随便说点什么'")
    if isinstance(result, IntentResult):
        print(f"  结果: IntentResult(type={result.intent_type})")
        print(f"  → 无法识别意图，路由到兜底处理器")
    print()

    print("✅ Demo 2 完成\n")


if __name__ == "__main__":
    asyncio.run(main())
