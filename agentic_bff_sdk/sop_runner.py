"""Batch SOP Runner for the Agentic BFF SDK.

Provides an abstract base class and default implementation for
cross-domain SOP (Standard Operating Procedure) execution.
The runner orchestrates multi-domain call sequences according to
SOP definitions, handles interaction scene dialog template selection,
implements exception handling strategies (retry/skip/rollback),
and writes step results to the Blackboard.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, Dict, List, Optional

from agentic_bff_sdk.blackboard import Blackboard
from agentic_bff_sdk.config import InteractionScene, SOPDefinition
from agentic_bff_sdk.models import ExecutionPlan

logger = logging.getLogger(__name__)

# Type alias for the step executor callable.
# Signature: async (domain, action, parameters, blackboard) -> Dict[str, Any]
StepExecutor = Callable[
    [str, str, Dict[str, Any], Blackboard],
    Coroutine[Any, Any, Dict[str, Any]],
]

# Maximum number of retry attempts for the "retry" exception policy.
MAX_RETRY_ATTEMPTS = 3


class BatchSOPRunner(ABC):
    """跨领域合并执行器抽象基类。

    按照 SOP 定义编排多个领域的调用序列，管理交互场景对话模板，
    并处理异常恢复策略。
    """

    @abstractmethod
    async def execute(
        self,
        plan: ExecutionPlan,
        sop: SOPDefinition,
        scene: InteractionScene,
        blackboard: Blackboard,
    ) -> List[Dict[str, Any]]:
        """按 SOP 编排执行。

        Args:
            plan: 执行计划。
            sop: SOP 定义，包含步骤、异常策略和对话模板。
            scene: 当前交互场景（电话、面谈、在线）。
            blackboard: 共享状态黑板。

        Returns:
            各步骤执行结果的列表。
        """
        ...


class DefaultBatchSOPRunner(BatchSOPRunner):
    """默认跨领域合并执行器实现。

    按 SOP 定义的步骤顺序依次执行领域调用，支持：
    - 交互场景对话模板选择
    - 异常处理策略（retry/skip/rollback）
    - 步骤结果写入 Blackboard
    """

    def __init__(
        self,
        step_executor: Optional[StepExecutor] = None,
    ) -> None:
        """初始化 DefaultBatchSOPRunner。

        Args:
            step_executor: 可选的步骤执行器回调。签名为
                async (domain, action, parameters, blackboard) -> Dict[str, Any]。
                若未提供，则使用默认的占位执行器。
        """
        self._step_executor = step_executor or self._default_step_executor

    @staticmethod
    async def _default_step_executor(
        domain: str,
        action: str,
        parameters: Dict[str, Any],
        blackboard: Blackboard,
    ) -> Dict[str, Any]:
        """默认步骤执行器（占位实现）。"""
        return {
            "domain": domain,
            "action": action,
            "status": "completed",
            "data": None,
        }

    def select_dialog_template(
        self,
        sop: SOPDefinition,
        scene: InteractionScene,
    ) -> Optional[str]:
        """根据交互场景选择对话模板。

        Args:
            sop: SOP 定义。
            scene: 当前交互场景。

        Returns:
            对应场景的对话模板字符串，若未配置则返回 None。
        """
        return sop.dialog_templates.get(scene)

    async def execute(
        self,
        plan: ExecutionPlan,
        sop: SOPDefinition,
        scene: InteractionScene,
        blackboard: Blackboard,
    ) -> List[Dict[str, Any]]:
        """按 SOP 编排执行。

        流程：
        1. 选择当前交互场景的对话模板
        2. 按 SOP 步骤顺序依次执行
        3. 对每个步骤应用异常处理策略
        4. 将每个步骤结果写入 Blackboard

        Args:
            plan: 执行计划。
            sop: SOP 定义。
            scene: 当前交互场景。
            blackboard: 共享状态黑板。

        Returns:
            各步骤执行结果的列表。

        Raises:
            RuntimeError: 当异常策略为 rollback 时抛出。
        """
        # 1. Select dialog template for the current scene
        dialog_template = self.select_dialog_template(sop, scene)
        if dialog_template is not None:
            await blackboard.set(
                f"sop_{sop.sop_id}_dialog_template",
                dialog_template,
            )

        results: List[Dict[str, Any]] = []

        # 2. Execute each SOP step in order
        for i, step in enumerate(sop.steps):
            domain = step.get("domain", "")
            action = step.get("action", "")
            parameters = step.get("parameters", {})

            step_result = await self._execute_step_with_policy(
                step_index=i,
                domain=domain,
                action=action,
                parameters=parameters,
                sop=sop,
                blackboard=blackboard,
            )

            results.append(step_result)

            # 4. Write step result to Blackboard
            bb_key = f"sop_{sop.sop_id}_step_{i}"
            await blackboard.set(bb_key, step_result)

        return results

    async def _execute_step_with_policy(
        self,
        step_index: int,
        domain: str,
        action: str,
        parameters: Dict[str, Any],
        sop: SOPDefinition,
        blackboard: Blackboard,
    ) -> Dict[str, Any]:
        """执行单个步骤，并在失败时应用异常处理策略。

        Args:
            step_index: 步骤索引。
            domain: 领域标识。
            action: 调用动作。
            parameters: 调用参数。
            sop: SOP 定义（含异常策略）。
            blackboard: 共享状态黑板。

        Returns:
            步骤执行结果。

        Raises:
            RuntimeError: 当异常策略为 rollback 时抛出。
        """
        try:
            return await self._step_executor(domain, action, parameters, blackboard)
        except Exception as exc:
            error_type = type(exc).__name__
            policy = sop.exception_policies.get(error_type, "skip")

            if policy == "retry":
                return await self._handle_retry(
                    domain, action, parameters, blackboard, exc
                )
            elif policy == "rollback":
                return self._handle_rollback(step_index, domain, action, exc)
            else:
                # Default to "skip"
                return self._handle_skip(step_index, domain, action, exc)

    async def _handle_retry(
        self,
        domain: str,
        action: str,
        parameters: Dict[str, Any],
        blackboard: Blackboard,
        original_error: Exception,
    ) -> Dict[str, Any]:
        """处理 retry 策略：最多重试 MAX_RETRY_ATTEMPTS 次。

        Args:
            domain: 领域标识。
            action: 调用动作。
            parameters: 调用参数。
            blackboard: 共享状态黑板。
            original_error: 原始异常。

        Returns:
            重试成功的结果，或最终失败的跳过结果。
        """
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                return await self._step_executor(
                    domain, action, parameters, blackboard
                )
            except Exception as retry_exc:
                logger.warning(
                    "Retry attempt %d/%d failed for %s.%s: %s",
                    attempt + 1,
                    MAX_RETRY_ATTEMPTS,
                    domain,
                    action,
                    retry_exc,
                )
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    # All retries exhausted, fall back to skip
                    logger.error(
                        "All %d retries exhausted for %s.%s, skipping step.",
                        MAX_RETRY_ATTEMPTS,
                        domain,
                        action,
                    )
                    return {
                        "domain": domain,
                        "action": action,
                        "status": "failed",
                        "error": str(retry_exc),
                        "policy_applied": "retry_exhausted",
                    }
        # Should not reach here, but satisfy type checker
        return {
            "domain": domain,
            "action": action,
            "status": "failed",
            "error": str(original_error),
            "policy_applied": "retry_exhausted",
        }

    @staticmethod
    def _handle_rollback(
        step_index: int,
        domain: str,
        action: str,
        exc: Exception,
    ) -> Dict[str, Any]:
        """处理 rollback 策略：抛出 RuntimeError。

        Args:
            step_index: 步骤索引。
            domain: 领域标识。
            action: 调用动作。
            exc: 原始异常。

        Raises:
            RuntimeError: 始终抛出，包含回滚信息。
        """
        raise RuntimeError(
            f"Rollback triggered at step {step_index} ({domain}.{action}): {exc}"
        ) from exc

    @staticmethod
    def _handle_skip(
        step_index: int,
        domain: str,
        action: str,
        exc: Exception,
    ) -> Dict[str, Any]:
        """处理 skip 策略：记录日志并继续。

        Args:
            step_index: 步骤索引。
            domain: 领域标识。
            action: 调用动作。
            exc: 原始异常。

        Returns:
            包含跳过状态的结果字典。
        """
        logger.warning(
            "Skipping step %d (%s.%s) due to error: %s",
            step_index,
            domain,
            action,
            exc,
        )
        return {
            "domain": domain,
            "action": action,
            "status": "skipped",
            "error": str(exc),
            "policy_applied": "skip",
        }
