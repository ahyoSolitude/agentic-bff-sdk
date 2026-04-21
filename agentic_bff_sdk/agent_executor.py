"""Agent Executor for the Agentic BFF SDK.

Provides a ReAct-based agent execution framework with custom tool registration,
input validation, max reasoning step limits, Blackboard context passing,
tool error feedback, and rule engine degradation strategies.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, Dict, List, Optional

import jsonschema
from langchain_core.tools import BaseTool

from agentic_bff_sdk.blackboard import Blackboard
from agentic_bff_sdk.config import AgentExecutorConfig, SDKConfig

logger = logging.getLogger(__name__)


# ============================================================
# AgentExecutor ABC
# ============================================================


class AgentExecutor(ABC):
    """Agent 执行代理抽象基类。

    基于 ReAct 模式定义执行链，交替进行推理和工具调用。
    """

    @abstractmethod
    async def execute(
        self,
        action: str,
        parameters: Dict[str, Any],
        blackboard: Blackboard,
        config: AgentExecutorConfig,
    ) -> Any:
        """基于 ReAct 模式执行领域任务。

        Args:
            action: 要执行的动作名称。
            parameters: 动作参数。
            blackboard: 共享状态黑板，用于跨 Agent 数据共享。
            config: Agent 执行器配置，包含最大推理步数和工具定义。

        Returns:
            执行结果。
        """
        ...  # pragma: no cover

    @abstractmethod
    def register_tool(self, tool: BaseTool) -> None:
        """注册自定义工具。

        Args:
            tool: LangChain BaseTool 实例。
        """
        ...  # pragma: no cover


# ============================================================
# Tool Input Validation
# ============================================================


def validate_tool_input(
    tool_name: str,
    input_params: Dict[str, Any],
    input_schema: Dict[str, Any],
) -> None:
    """验证工具输入参数是否符合 input_schema。

    Args:
        tool_name: 工具名称（用于错误消息）。
        input_params: 实际输入参数。
        input_schema: JSON Schema 格式的输入模式定义。

    Raises:
        ValueError: 当输入参数不符合 schema 时。
    """
    try:
        jsonschema.validate(instance=input_params, schema=input_schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(
            f"Tool '{tool_name}' input validation failed: {exc.message}"
        ) from exc


# ============================================================
# Rule Engine Degradation
# ============================================================


async def handle_rule_engine_call(
    rule_engine_callable: Callable[..., Coroutine[Any, Any, Any]],
    rule_set_id: str,
    params: Dict[str, Any],
    fallback_value: Optional[Any] = None,
) -> Any:
    """调用规则引擎，并在超时/错误时执行降级策略。

    Args:
        rule_engine_callable: 异步规则引擎调用函数。
        rule_set_id: 规则集标识。
        params: 规则引擎输入参数。
        fallback_value: 降级默认值。若为 None 表示未配置降级策略。

    Returns:
        规则引擎计算结果，或降级默认值。

    Raises:
        RuntimeError: 当规则引擎调用失败且未配置降级策略时。
    """
    try:
        return await rule_engine_callable(rule_set_id, params)
    except Exception as exc:
        if fallback_value is not None:
            logger.warning(
                "Rule engine call failed for rule_set_id='%s': %s. "
                "Using fallback value.",
                rule_set_id,
                exc,
            )
            return fallback_value
        raise RuntimeError(
            f"Rule engine call failed for rule_set_id='{rule_set_id}': {exc}"
        ) from exc


# ============================================================
# Reasoning Loop Types
# ============================================================

# Type alias for the reasoning loop callable.
# Signature: (action, parameters, tools, blackboard_context, max_steps) -> result
ReasoningLoop = Callable[
    [str, Dict[str, Any], List[BaseTool], Dict[str, Any], int],
    Coroutine[Any, Any, Any],
]


# ============================================================
# DefaultAgentExecutor
# ============================================================


class DefaultAgentExecutor(AgentExecutor):
    """默认 Agent 执行代理实现。

    基于 LangChain ReAct Agent 构建，支持：
    - 自定义工具注册与输入参数验证
    - 最大推理步数限制
    - Blackboard 上下文传递给 LLM
    - 工具调用错误反馈给 LLM 决策
    - 规则引擎降级策略

    For testability, accepts an optional ``reasoning_loop`` callable that
    simulates the ReAct loop. The default implementation uses LangChain's
    ReAct pattern.

    Args:
        llm: LangChain BaseLanguageModel 实例。
        config: SDK 全局配置（可选）。
        reasoning_loop: 可选的推理循环函数，用于测试注入。
    """

    def __init__(
        self,
        llm: Any = None,
        config: Optional[SDKConfig] = None,
        reasoning_loop: Optional[ReasoningLoop] = None,
    ) -> None:
        self._llm = llm
        self._config = config or SDKConfig()
        self._tools: List[BaseTool] = []
        self._reasoning_loop = reasoning_loop

    # ----------------------------------------------------------
    # Tool registration
    # ----------------------------------------------------------

    def register_tool(self, tool: BaseTool) -> None:
        """注册自定义工具。

        Args:
            tool: LangChain BaseTool 实例。
        """
        self._tools.append(tool)
        logger.info("Registered tool '%s'", tool.name)

    @property
    def tools(self) -> List[BaseTool]:
        """返回已注册的工具列表。"""
        return list(self._tools)

    # ----------------------------------------------------------
    # Blackboard context extraction
    # ----------------------------------------------------------

    @staticmethod
    async def _extract_blackboard_context(
        blackboard: Blackboard,
    ) -> Dict[str, Any]:
        """从 Blackboard 中提取所有键值作为上下文。

        Args:
            blackboard: 共享状态黑板。

        Returns:
            包含所有 Blackboard 键值的字典。
        """
        context: Dict[str, Any] = {}
        # Access the internal store under lock for a consistent snapshot
        async with blackboard._lock:
            for key, value in blackboard._store.items():
                context[key] = value
        return context

    # ----------------------------------------------------------
    # Tool input validation
    # ----------------------------------------------------------

    def _validate_tool_inputs(
        self,
        tool_name: str,
        input_params: Dict[str, Any],
        config: AgentExecutorConfig,
    ) -> None:
        """验证工具输入参数是否符合配置中定义的 input_schema。

        Args:
            tool_name: 工具名称。
            input_params: 实际输入参数。
            config: Agent 执行器配置。

        Raises:
            ValueError: 当输入参数不符合 schema 时。
        """
        for tool_def in config.tools:
            if tool_def.name == tool_name and tool_def.input_schema:
                validate_tool_input(
                    tool_name, input_params, tool_def.input_schema
                )
                return

    # ----------------------------------------------------------
    # Default reasoning loop (LangChain ReAct)
    # ----------------------------------------------------------

    async def _default_reasoning_loop(
        self,
        action: str,
        parameters: Dict[str, Any],
        tools: List[BaseTool],
        blackboard_context: Dict[str, Any],
        max_steps: int,
    ) -> Any:
        """默认推理循环，基于 LangChain ReAct Agent。

        This is a simplified implementation that demonstrates the ReAct
        pattern. In production, this would use ``create_react_agent`` from
        LangChain.

        Args:
            action: 要执行的动作名称。
            parameters: 动作参数。
            tools: 可用工具列表。
            blackboard_context: Blackboard 上下文数据。
            max_steps: 最大推理步数。

        Returns:
            执行结果。
        """
        if self._llm is None:
            raise RuntimeError(
                "No LLM configured for DefaultAgentExecutor. "
                "Provide an LLM or a custom reasoning_loop."
            )

        # Build the prompt context
        context_str = ""
        if blackboard_context:
            context_str = (
                "Blackboard context:\n"
                + "\n".join(
                    f"  {k}: {v}" for k, v in blackboard_context.items()
                )
                + "\n\n"
            )

        tool_descriptions = "\n".join(
            f"- {t.name}: {t.description}" for t in tools
        )

        current_input = (
            f"{context_str}"
            f"Available tools:\n{tool_descriptions}\n\n"
            f"Action: {action}\n"
            f"Parameters: {parameters}\n\n"
            f"Think step by step and use tools as needed."
        )

        steps_taken = 0
        last_result: Any = None

        while steps_taken < max_steps:
            steps_taken += 1

            # Invoke LLM for reasoning
            try:
                llm_response = await self._llm.ainvoke(current_input)
            except Exception as exc:
                logger.error("LLM invocation failed at step %d: %s", steps_taken, exc)
                raise

            # Extract response content
            response_text = (
                llm_response.content
                if hasattr(llm_response, "content")
                else str(llm_response)
            )

            # Check if LLM wants to call a tool
            tool_call = self._parse_tool_call(response_text, tools)

            if tool_call is None:
                # LLM produced a final answer
                last_result = response_text
                break

            tool_name, tool_input = tool_call

            # Execute tool with error feedback
            try:
                tool_obj = next(t for t in tools if t.name == tool_name)
                tool_result = await tool_obj.ainvoke(tool_input)
                last_result = tool_result

                # Feed result back to LLM
                current_input = (
                    f"{current_input}\n\n"
                    f"Tool '{tool_name}' returned: {tool_result}\n\n"
                    f"Continue reasoning or provide final answer."
                )
            except Exception as tool_exc:
                # Feed error back to LLM for retry/alternative
                logger.warning(
                    "Tool '%s' call failed at step %d: %s",
                    tool_name,
                    steps_taken,
                    tool_exc,
                )
                current_input = (
                    f"{current_input}\n\n"
                    f"Tool '{tool_name}' failed with error: {tool_exc}\n\n"
                    f"Decide whether to retry, use an alternative tool, "
                    f"or provide a final answer."
                )

        return last_result

    @staticmethod
    def _parse_tool_call(
        response_text: str,
        tools: List[BaseTool],
    ) -> Optional[tuple]:
        """Parse a tool call from LLM response text.

        Looks for patterns like ``TOOL: tool_name`` or ``Action: tool_name``
        in the response. Returns ``(tool_name, input_dict)`` or ``None``.
        """
        import re

        # Look for tool call patterns
        for tool in tools:
            pattern = rf"(?:TOOL|Action|Tool):\s*{re.escape(tool.name)}"
            if re.search(pattern, response_text, re.IGNORECASE):
                # Try to extract input from Action Input line
                input_match = re.search(
                    r"(?:Action Input|Input|TOOL_INPUT):\s*(.+)",
                    response_text,
                    re.IGNORECASE,
                )
                tool_input = {}
                if input_match:
                    try:
                        import json

                        tool_input = json.loads(input_match.group(1).strip())
                    except (json.JSONDecodeError, ValueError):
                        tool_input = {"input": input_match.group(1).strip()}
                return (tool.name, tool_input)

        return None

    # ----------------------------------------------------------
    # execute
    # ----------------------------------------------------------

    async def execute(
        self,
        action: str,
        parameters: Dict[str, Any],
        blackboard: Blackboard,
        config: AgentExecutorConfig,
    ) -> Any:
        """基于 ReAct 模式执行领域任务。

        流程：
        1. 从 Blackboard 提取上下文
        2. 合并已注册工具与配置中的工具定义
        3. 调用推理循环（可注入自定义实现）
        4. 返回执行结果

        Args:
            action: 要执行的动作名称。
            parameters: 动作参数。
            blackboard: 共享状态黑板。
            config: Agent 执行器配置。

        Returns:
            执行结果。
        """
        # 1. Extract Blackboard context
        blackboard_context = await self._extract_blackboard_context(blackboard)

        # 2. Determine max reasoning steps
        max_steps = config.max_reasoning_steps

        # 3. Use injected reasoning loop or default
        reasoning_loop = self._reasoning_loop or self._default_reasoning_loop

        # 4. Execute reasoning loop
        result = await reasoning_loop(
            action,
            parameters,
            self._tools,
            blackboard_context,
            max_steps,
        )

        return result
