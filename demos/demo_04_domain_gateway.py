#!/usr/bin/env python3
"""Demo 4: DomainGateway 领域网关

展示能力：
- DomainGateway 抽象与 DefaultDomainGateway
- TaskPackage 注册与领域路由
- 协议转换（DomainRequest → TaskPackage.execute）
- 未注册领域的降级处理
- 审计日志记录（AuditLogger）
"""

import asyncio
import logging
from typing import Any, Dict

from agentic_bff_sdk import DomainRequest, DomainResponse
from agentic_bff_sdk.audit import DefaultAuditLogger
from agentic_bff_sdk.domain_gateway import DefaultDomainGateway, TaskPackage

# 配置日志以便看到审计输出
logging.basicConfig(level=logging.INFO, format="  %(name)s | %(message)s")


# ============================================================
# 自定义 TaskPackage 实现
# ============================================================

class FundTaskPackage:
    """基金领域任务包。"""

    async def execute(self, action: str, parameters: Dict[str, Any]) -> Any:
        if action == "query_nav":
            fund_id = parameters.get("fund_id", "unknown")
            return {"fund_id": fund_id, "fund_name": "成长优选基金", "nav": 1.2580, "date": "2024-12-20"}
        elif action == "query_holdings":
            return {"holdings": [{"stock": "贵州茅台", "weight": 8.5}, {"stock": "宁德时代", "weight": 6.2}]}
        else:
            return {"action": action, "status": "not_implemented"}


class AssetTaskPackage:
    """资产领域任务包。"""

    async def execute(self, action: str, parameters: Dict[str, Any]) -> Any:
        if action == "query_total":
            return {"total_assets": 1_250_000.00, "currency": "CNY", "accounts": 3}
        elif action == "query_allocation":
            return {"equity": 45, "bond": 30, "cash": 15, "alternative": 10}
        else:
            return {"action": action, "status": "not_implemented"}


async def main():
    print("\n🔷 Demo 4: DomainGateway 领域网关\n")

    gw = DefaultDomainGateway()

    # --- 4.1 注册 TaskPackage ---
    print("=" * 60)
    print("4.1 注册 TaskPackage")
    print("=" * 60)
    gw.register_task_package("fund", FundTaskPackage())
    gw.register_task_package("asset", AssetTaskPackage())
    print("  已注册: fund, asset")
    print()

    # --- 4.2 领域路由与协议转换 ---
    print("=" * 60)
    print("4.2 领域路由与协议转换")
    print("=" * 60)

    # 基金查询
    resp = await gw.invoke(DomainRequest(
        domain="fund", action="query_nav", parameters={"fund_id": "F001"}, request_id="req-001",
    ))
    print(f"  fund.query_nav → success={resp.success}, data={resp.data}")

    # 资产查询
    resp = await gw.invoke(DomainRequest(
        domain="asset", action="query_allocation", parameters={}, request_id="req-002",
    ))
    print(f"  asset.query_allocation → success={resp.success}, data={resp.data}")
    print()

    # --- 4.3 未注册领域降级 ---
    print("=" * 60)
    print("4.3 未注册领域降级")
    print("=" * 60)
    resp = await gw.invoke(DomainRequest(
        domain="insurance", action="query", parameters={}, request_id="req-003",
    ))
    print(f"  insurance.query → success={resp.success}")
    print(f"  错误信息: {resp.error}")
    print()

    # --- 4.4 审计日志 ---
    print("=" * 60)
    print("4.4 审计日志记录")
    print("=" * 60)
    audit = DefaultAuditLogger()
    await audit.log_invocation(
        domain="fund", action="query_nav",
        request_summary="fund_id=F001",
        response_summary="nav=1.258",
        success=True, duration_ms=45.2,
    )
    await audit.log_invocation(
        domain="insurance", action="query",
        request_summary="policy_id=P001",
        response_summary="error: not registered",
        success=False, duration_ms=2.1,
    )
    print("  (审计日志已通过 Python logging 输出，见上方 INFO/WARNING 行)")
    print()

    print("✅ Demo 4 完成\n")


if __name__ == "__main__":
    asyncio.run(main())
