#!/usr/bin/env python3
"""Demo 1: Blackboard 共享状态 & SessionContext 会话管理

展示能力：
- Blackboard 线程安全键值存储（set/get/delete/cleanup_expired）
- SessionContext 会话创建与恢复
- 话题管理（创建、切换、关闭）
- 对话历史压缩
"""

import asyncio
import time

from agentic_bff_sdk import Blackboard, SessionContext, SessionState, Topic


async def demo_blackboard():
    """演示 Blackboard 共享状态存储。"""
    print("=" * 60)
    print("1.1 Blackboard 共享状态存储")
    print("=" * 60)

    bb = Blackboard()

    # 写入多种类型的数据
    await bb.set("user_name", "张三")
    await bb.set("account_balance", 150000.50)
    await bb.set("risk_profile", {"level": "moderate", "score": 65})
    await bb.set("recent_trades", ["基金A买入", "基金B赎回"])

    # 读取数据
    name = await bb.get("user_name")
    balance = await bb.get("account_balance")
    risk = await bb.get("risk_profile")
    print(f"  用户: {name}")
    print(f"  余额: ¥{balance:,.2f}")
    print(f"  风险画像: {risk}")

    # 删除数据
    deleted = await bb.delete("recent_trades")
    print(f"  删除 recent_trades: {deleted}")
    print(f"  再次读取: {await bb.get('recent_trades')}")

    # 过期清理
    bb._access_times["account_balance"] = time.time() - 7200  # 模拟 2 小时前
    expired = await bb.cleanup_expired(ttl_seconds=3600)
    print(f"  过期清理 (TTL=1h): 清理了 {expired}")
    print(f"  余额还在吗: {await bb.get('account_balance')}")
    print()


async def demo_session_context():
    """演示 SessionContext 会话管理。"""
    print("=" * 60)
    print("1.2 SessionContext 会话管理")
    print("=" * 60)

    ctx = SessionContext(max_dialog_history_turns=5)

    # 创建新会话
    state = await ctx.get_or_create("session_001")
    print(f"  新会话: session_id={state.session_id}")
    print(f"  对话历史: {len(state.dialog_history)} 条")

    # 模拟多轮对话
    for i in range(8):
        state.dialog_history.append({"role": "user", "content": f"第{i+1}轮用户输入"})
        state.dialog_history.append({"role": "assistant", "content": f"第{i+1}轮助手回复"})
    state.last_active_at = time.time()
    await ctx.save("session_001", state)
    print(f"  添加 8 轮对话后: {len(state.dialog_history)} 条记录")

    # 对话历史压缩
    ctx.compress_dialog_history(state)
    print(f"  压缩后 (max=5): {len(state.dialog_history)} 条记录")
    print(f"  首条 (摘要): {state.dialog_history[0]['role']} - {state.dialog_history[0]['content'][:60]}...")
    print(f"  末条 (最新): {state.dialog_history[-1]['content']}")
    print()


async def demo_topic_management():
    """演示话题管理。"""
    print("=" * 60)
    print("1.3 话题管理")
    print("=" * 60)

    ctx = SessionContext()
    state = await ctx.get_or_create("session_002")

    # 创建话题
    t1 = ctx.create_topic(state, "基金查询", metadata={"category": "fund"})
    t2 = ctx.create_topic(state, "资产配置", metadata={"category": "asset"})
    print(f"  创建话题: {t1.name} (status={t1.status})")
    print(f"  创建话题: {t2.name} (status={t2.status})")

    # 此时 t2 是 active，t1 被自动 suspended
    for t in state.active_topics:
        print(f"    - {t.name}: {t.status}")

    # 切换话题
    ctx.switch_topic(state, t1.topic_id)
    print(f"  切换到 '{t1.name}' 后:")
    for t in state.active_topics:
        print(f"    - {t.name}: {t.status}")

    # 关闭话题
    ctx.close_topic(state, t2.topic_id)
    print(f"  关闭 '{t2.name}' 后:")
    for t in state.active_topics:
        print(f"    - {t.name}: {t.status}")
    print()


async def demo_session_cleanup():
    """演示会话过期清理。"""
    print("=" * 60)
    print("1.4 会话过期清理")
    print("=" * 60)

    ctx = SessionContext()

    # 创建多个会话
    s1 = await ctx.get_or_create("active_session")
    s2 = await ctx.get_or_create("old_session")

    # 模拟 old_session 已过期
    s2.last_active_at = time.time() - 7200
    await ctx.save("old_session", s2)

    cleaned = await ctx.cleanup_expired(idle_timeout_seconds=3600)
    print(f"  清理过期会话 (idle > 1h): {cleaned}")

    # 验证
    active = await ctx.storage.load("active_session")
    old = await ctx.storage.load("old_session")
    print(f"  active_session 还在: {active is not None}")
    print(f"  old_session 还在: {old is not None}")
    print()


async def main():
    print("\n🔷 Demo 1: Blackboard 共享状态 & SessionContext 会话管理\n")
    await demo_blackboard()
    await demo_session_context()
    await demo_topic_management()
    await demo_session_cleanup()
    print("✅ Demo 1 完成\n")


if __name__ == "__main__":
    asyncio.run(main())
