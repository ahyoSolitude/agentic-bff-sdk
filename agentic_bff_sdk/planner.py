"""IMC Planner for the Agentic BFF SDK.

Provides execution plan generation based on Chain-of-Thought (CoT) reasoning.
The IMCPlanner abstract base class defines the interface for plan generation
and persistence, while DefaultIMCPlanner implements LLM-based CoT planning
with timeout control, step dependency annotation, and ReAct node embedding.
"""

import asyncio
import json
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, List, Optional

from langchain_core.language_models import BaseLanguageModel

from agentic_bff_sdk.config import SDKConfig
from agentic_bff_sdk.models import (
    ExecutionPlan,
    IntentResult,
    PlanStep,
    SessionState,
)


class IMCPlanner(ABC):
    """一次开发完成器抽象基类。

    负责基于 CoT 推理链生成包含所有必要步骤的执行计划，
    并支持执行计划的持久化（离线场景）。
    """

    @abstractmethod
    async def generate_plan(
        self,
        intent: IntentResult,
        session_state: SessionState,
        timeout_seconds: Optional[float] = None,
    ) -> ExecutionPlan:
        """基于 CoT 生成执行计划。

        Args:
            intent: 已确认的用户意图。
            session_state: 当前会话状态。
            timeout_seconds: 计划生成超时时间（秒）。若为 None 则使用配置默认值。

        Returns:
            包含步骤列表、依赖关系和 ReAct 节点标注的 ExecutionPlan。

        Raises:
            asyncio.TimeoutError: 若计划生成超过超时时间。
        """
        ...

    @abstractmethod
    async def persist_plan(self, plan: ExecutionPlan) -> str:
        """持久化执行计划（离线场景）。

        Args:
            plan: 要持久化的执行计划。

        Returns:
            持久化后的 plan_id。
        """
        ...


class DefaultIMCPlanner(IMCPlanner):
    """基于 LLM CoT 推理的默认执行计划生成器。

    实现流程：
    1. 构建 CoT 提示词，包含意图信息和会话上下文
    2. 调用 LLM 生成执行计划（JSON 格式）
    3. 解析 LLM 输出为 PlanStep 列表
    4. 标注步骤间依赖关系和 ReAct 循环节点
    5. 使用 asyncio.wait_for 实现超时控制
    6. 支持将计划持久化到内存存储（可扩展为数据库/文件）
    """

    def __init__(
        self,
        llm: BaseLanguageModel,
        config: Optional[SDKConfig] = None,
        plan_generator: Optional[
            Callable[
                [BaseLanguageModel, IntentResult, SessionState],
                Awaitable[List[PlanStep]],
            ]
        ] = None,
    ) -> None:
        """初始化 DefaultIMCPlanner。

        Args:
            llm: LangChain BaseLanguageModel 实例，用于 CoT 推理。
            config: SDK 全局配置。若为 None 则使用默认配置。
            plan_generator: 可选的自定义计划生成函数。接收 (llm, intent,
                session_state) 并返回 PlanStep 列表。
                若为 None 则使用内置的默认 CoT 推理逻辑。
        """
        self._llm = llm
        self._config = config or SDKConfig()
        self._plan_generator = plan_generator
        self._persisted_plans: Dict[str, ExecutionPlan] = {}

    @property
    def llm(self) -> BaseLanguageModel:
        """获取 LLM 实例。"""
        return self._llm

    @property
    def config(self) -> SDKConfig:
        """获取 SDK 配置。"""
        return self._config

    @property
    def persisted_plans(self) -> Dict[str, ExecutionPlan]:
        """获取已持久化的执行计划（只读副本）。"""
        return dict(self._persisted_plans)

    async def generate_plan(
        self,
        intent: IntentResult,
        session_state: SessionState,
        timeout_seconds: Optional[float] = None,
    ) -> ExecutionPlan:
        """基于 CoT 生成执行计划，带超时控制。

        使用 asyncio.wait_for 在可配置的超时时间内完成计划生成。
        若超时则抛出 asyncio.TimeoutError。

        Args:
            intent: 已确认的用户意图。
            session_state: 当前会话状态。
            timeout_seconds: 计划生成超时时间（秒）。若为 None 则使用
                config.plan_generation_timeout_seconds。

        Returns:
            ExecutionPlan 实例。

        Raises:
            asyncio.TimeoutError: 若计划生成超过超时时间。
        """
        effective_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self._config.plan_generation_timeout_seconds
        )

        return await asyncio.wait_for(
            self._generate_plan_internal(intent, session_state),
            timeout=effective_timeout,
        )

    async def _generate_plan_internal(
        self,
        intent: IntentResult,
        session_state: SessionState,
    ) -> ExecutionPlan:
        """内部计划生成逻辑（无超时包装）。

        Args:
            intent: 已确认的用户意图。
            session_state: 当前会话状态。

        Returns:
            ExecutionPlan 实例。
        """
        steps = await self._generate_steps(intent, session_state)

        plan_id = str(uuid.uuid4())
        return ExecutionPlan(
            plan_id=plan_id,
            intent=intent,
            steps=steps,
            created_at=time.time(),
            timeout_seconds=self._config.plan_generation_timeout_seconds,
        )

    async def _generate_steps(
        self,
        intent: IntentResult,
        session_state: SessionState,
    ) -> List[PlanStep]:
        """生成执行步骤列表。

        若提供了自定义 plan_generator，则使用它；否则使用内置的 CoT 推理逻辑。

        Args:
            intent: 已确认的用户意图。
            session_state: 当前会话状态。

        Returns:
            PlanStep 列表。
        """
        if self._plan_generator is not None:
            return await self._plan_generator(self._llm, intent, session_state)

        return await self._default_plan_generator(intent, session_state)

    async def _default_plan_generator(
        self,
        intent: IntentResult,
        session_state: SessionState,
    ) -> List[PlanStep]:
        """内置的默认 CoT 计划生成逻辑。

        构建 CoT 提示词，调用 LLM 生成执行计划 JSON，然后解析为 PlanStep 列表。

        Args:
            intent: 已确认的用户意图。
            session_state: 当前会话状态。

        Returns:
            PlanStep 列表。
        """
        prompt = (
            "You are an execution planner. Based on the user's intent, generate "
            "a step-by-step execution plan using Chain-of-Thought reasoning.\n\n"
            "Return a JSON array of step objects. Each step must have:\n"
            '- "step_id": unique string identifier (e.g., "step_1")\n'
            '- "domain": the business domain this step targets\n'
            '- "action": the specific action to perform\n'
            '- "parameters": object with action parameters\n'
            '- "dependencies": array of step_ids this step depends on\n'
            '- "is_react_node": boolean, true if this step requires a '
            "ReAct reasoning loop\n\n"
            "Think step by step:\n"
            "1. What domains are involved?\n"
            "2. What actions are needed in each domain?\n"
            "3. What are the dependencies between steps?\n"
            "4. Which steps need dynamic ReAct reasoning?\n\n"
            f"Intent type: {intent.intent_type}\n"
            f"Intent parameters: {json.dumps(intent.parameters)}\n"
            f"Session ID: {session_state.session_id}\n"
        )

        response = await self._llm.ainvoke(prompt)

        response_text = (
            response.content
            if hasattr(response, "content")
            else str(response)
        )

        return self._parse_steps(response_text)

    @staticmethod
    def _parse_steps(response_text: str) -> List[PlanStep]:
        """解析 LLM 响应文本为 PlanStep 列表。

        尝试从响应中提取 JSON 数组并转换为 PlanStep 对象。
        若解析失败则返回空列表。

        Args:
            response_text: LLM 的原始响应文本。

        Returns:
            PlanStep 列表。
        """
        try:
            parsed = json.loads(response_text)
            if isinstance(parsed, list):
                return [
                    PlanStep(
                        step_id=item.get("step_id", f"step_{i}"),
                        domain=item.get("domain", ""),
                        action=item.get("action", ""),
                        parameters=item.get("parameters", {}),
                        dependencies=item.get("dependencies", []),
                        is_react_node=bool(item.get("is_react_node", False)),
                    )
                    for i, item in enumerate(parsed)
                    if isinstance(item, dict)
                ]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        return []

    async def persist_plan(self, plan: ExecutionPlan) -> str:
        """持久化执行计划到内存存储。

        将执行计划存储在内部字典中，以 plan_id 为键。
        可扩展为数据库或文件存储。

        Args:
            plan: 要持久化的执行计划。

        Returns:
            持久化后的 plan_id。
        """
        self._persisted_plans[plan.plan_id] = plan
        return plan.plan_id

    async def load_plan(self, plan_id: str) -> Optional[ExecutionPlan]:
        """从内存存储加载执行计划。

        Args:
            plan_id: 要加载的执行计划 ID。

        Returns:
            ExecutionPlan 实例，若不存在则返回 None。
        """
        return self._persisted_plans.get(plan_id)
