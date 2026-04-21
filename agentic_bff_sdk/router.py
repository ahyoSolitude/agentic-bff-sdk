"""Top Level Router for the Agentic BFF SDK.

Provides intent recognition and routing. The TopLevelRouter abstract base class
defines the interface for intent routing, while DefaultTopLevelRouter implements
LLM-based intent recognition with priority rules, confidence thresholds,
ambiguity detection, and fallback handling.
"""

import re
from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable, Dict, List, Optional, Union

from langchain_core.language_models import BaseLanguageModel

from agentic_bff_sdk.config import SDKConfig
from agentic_bff_sdk.models import (
    ClarificationQuestion,
    IntentResult,
    RouterMode,
    SessionState,
)


class TopLevelRouter(ABC):
    """顶层意图路由器抽象基类。

    负责识别用户意图并将请求分发到对应的处理链路。
    支持优先匹配规则、置信度阈值判断、歧义意图检测和兜底路由。
    """

    @abstractmethod
    async def route(
        self,
        user_input: str,
        session_state: SessionState,
        mode: RouterMode = RouterMode.GENERATE,
    ) -> Union[IntentResult, ClarificationQuestion]:
        """识别意图或生成澄清问题。

        Args:
            user_input: 用户的自然语言输入。
            session_state: 当前会话状态。
            mode: 路由模式。GENERATE 用于首次识别，CONFIRM 用于确认歧义意图。

        Returns:
            IntentResult 表示成功识别的意图，
            ClarificationQuestion 表示需要用户澄清。
        """
        ...

    @abstractmethod
    def register_priority_rule(self, rule: Dict[str, Any]) -> None:
        """注册优先匹配规则。

        优先匹配规则在 LLM 意图识别之前检查。若用户输入匹配了某条规则，
        则直接返回该规则对应的意图，跳过 LLM 调用。

        Args:
            rule: 优先匹配规则字典，包含:
                - "pattern": 正则表达式或关键词字符串
                - "intent_type": 匹配时返回的意图类型
                - 其他可选参数字段
        """
        ...

    @abstractmethod
    def register_fallback_handler(self, handler: Any) -> None:
        """注册兜底处理链路。

        当无法匹配任何已注册意图时，请求将被路由到兜底处理链路。

        Args:
            handler: 兜底处理器。可以是一个可调用对象或处理链路实例。
        """
        ...


class DefaultTopLevelRouter(TopLevelRouter):
    """基于 LLM 的默认顶层意图路由器。

    实现流程：
    1. 优先匹配规则检查：遍历已注册的优先规则，若匹配则直接返回对应意图
    2. LLM 意图识别：调用 LLM 获取候选意图列表及置信度分数
    3. 歧义检测：若前两个候选意图置信度差值在 intent_ambiguity_range 内，
       返回 ClarificationQuestion 包含候选列表
    4. 置信度阈值判断：若最高置信度低于 intent_confidence_threshold，
       返回 ClarificationQuestion
    5. 兜底路由：若无匹配意图且已注册 fallback handler，路由到兜底链路
    """

    def __init__(
        self,
        llm: BaseLanguageModel,
        config: Optional[SDKConfig] = None,
        intent_recognizer: Optional[
            Callable[
                [BaseLanguageModel, str, SessionState],
                Awaitable[List[IntentResult]],
            ]
        ] = None,
    ) -> None:
        """初始化 DefaultTopLevelRouter。

        Args:
            llm: LangChain BaseLanguageModel 实例，用于意图识别。
            config: SDK 全局配置。若为 None 则使用默认配置。
            intent_recognizer: 可选的自定义意图识别函数。接收 (llm, user_input,
                session_state) 并返回候选 IntentResult 列表（按置信度降序排列）。
                若为 None 则使用内置的默认识别逻辑。
        """
        self._llm = llm
        self._config = config or SDKConfig()
        self._priority_rules: List[Dict[str, Any]] = []
        self._fallback_handler: Optional[Any] = None
        self._intent_recognizer = intent_recognizer

    @property
    def llm(self) -> BaseLanguageModel:
        """获取 LLM 实例。"""
        return self._llm

    @property
    def config(self) -> SDKConfig:
        """获取 SDK 配置。"""
        return self._config

    @property
    def priority_rules(self) -> List[Dict[str, Any]]:
        """获取已注册的优先匹配规则列表。"""
        return list(self._priority_rules)

    @property
    def fallback_handler(self) -> Optional[Any]:
        """获取已注册的兜底处理器。"""
        return self._fallback_handler

    def register_priority_rule(self, rule: Dict[str, Any]) -> None:
        """注册优先匹配规则。

        Args:
            rule: 优先匹配规则字典，必须包含 "pattern" 和 "intent_type" 字段。
                - "pattern": 正则表达式或关键词字符串
                - "intent_type": 匹配时返回的意图类型
                - 其他键值对将作为 IntentResult.parameters

        Raises:
            ValueError: 若规则缺少 "pattern" 或 "intent_type" 字段。
        """
        if "pattern" not in rule or "intent_type" not in rule:
            raise ValueError(
                "Priority rule must contain 'pattern' and 'intent_type' fields."
            )
        self._priority_rules.append(rule)

    def register_fallback_handler(self, handler: Any) -> None:
        """注册兜底处理链路。

        Args:
            handler: 兜底处理器。
        """
        self._fallback_handler = handler

    def _match_priority_rule(
        self, user_input: str
    ) -> Optional[IntentResult]:
        """检查用户输入是否匹配任何优先规则。

        按注册顺序遍历规则，首个匹配的规则生效。
        匹配方式：先尝试正则匹配，若正则无效则进行关键词包含匹配。

        Args:
            user_input: 用户输入文本。

        Returns:
            匹配的 IntentResult（置信度 1.0），若无匹配则返回 None。
        """
        for rule in self._priority_rules:
            pattern = rule["pattern"]
            intent_type = rule["intent_type"]

            matched = False
            try:
                if re.search(pattern, user_input, re.IGNORECASE):
                    matched = True
            except re.error:
                # If pattern is not a valid regex, fall back to keyword match
                if pattern.lower() in user_input.lower():
                    matched = True

            if matched:
                # Extract extra parameters (everything except pattern and intent_type)
                params = {
                    k: v
                    for k, v in rule.items()
                    if k not in ("pattern", "intent_type")
                }
                return IntentResult(
                    intent_type=intent_type,
                    confidence=1.0,
                    parameters=params,
                )

        return None

    async def _recognize_intents(
        self, user_input: str, session_state: SessionState
    ) -> List[IntentResult]:
        """通过 LLM 识别用户意图。

        若提供了自定义 intent_recognizer，则使用它；否则使用内置的默认逻辑。
        返回的候选列表按置信度降序排列。

        Args:
            user_input: 用户输入文本。
            session_state: 当前会话状态。

        Returns:
            候选 IntentResult 列表，按置信度降序排列。
        """
        if self._intent_recognizer is not None:
            candidates = await self._intent_recognizer(
                self._llm, user_input, session_state
            )
        else:
            candidates = await self._default_intent_recognizer(
                user_input, session_state
            )

        # Sort by confidence descending
        candidates.sort(key=lambda x: x.confidence, reverse=True)
        return candidates

    async def _default_intent_recognizer(
        self, user_input: str, session_state: SessionState
    ) -> List[IntentResult]:
        """内置的默认意图识别逻辑。

        使用 LLM 的 ainvoke 方法进行意图识别。子类或使用者可通过
        intent_recognizer 参数替换此逻辑。

        Args:
            user_input: 用户输入文本。
            session_state: 当前会话状态。

        Returns:
            候选 IntentResult 列表。
        """
        prompt = (
            "Identify the user's intent from the following input. "
            "Return a JSON array of objects with 'intent_type' (string), "
            "'confidence' (float 0-1), and 'parameters' (object) fields. "
            "Sort by confidence descending.\n\n"
            f"User input: {user_input}\n"
            f"Session context: {session_state.session_id}"
        )

        response = await self._llm.ainvoke(prompt)

        # Parse the LLM response - the actual parsing depends on the LLM output format.
        # For robustness, we attempt JSON parsing; if it fails, return empty list.
        import json

        response_text = (
            response.content
            if hasattr(response, "content")
            else str(response)
        )

        try:
            parsed = json.loads(response_text)
            if isinstance(parsed, list):
                return [
                    IntentResult(
                        intent_type=item.get("intent_type", "unknown"),
                        confidence=float(item.get("confidence", 0.0)),
                        parameters=item.get("parameters", {}),
                    )
                    for item in parsed
                    if isinstance(item, dict)
                ]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        return []

    async def route(
        self,
        user_input: str,
        session_state: SessionState,
        mode: RouterMode = RouterMode.GENERATE,
    ) -> Union[IntentResult, ClarificationQuestion]:
        """识别意图或生成澄清问题。

        处理流程：
        1. 检查优先匹配规则（仅 GENERATE 模式）
        2. 调用 LLM 进行意图识别
        3. 若无候选意图，路由到兜底链路或返回澄清问题
        4. 检查歧义（前两个候选置信度差值在 ambiguity_range 内）
        5. 检查置信度阈值
        6. 返回最高置信度的意图

        Args:
            user_input: 用户的自然语言输入。
            session_state: 当前会话状态。
            mode: 路由模式。

        Returns:
            IntentResult 或 ClarificationQuestion。
        """
        # Step 1: Check priority rules first (only in GENERATE mode)
        if mode == RouterMode.GENERATE:
            priority_match = self._match_priority_rule(user_input)
            if priority_match is not None:
                return priority_match

        # Step 2: LLM intent recognition
        candidates = await self._recognize_intents(user_input, session_state)

        # Step 3: No candidates — fallback or clarification
        if not candidates:
            return await self._handle_no_candidates(user_input, session_state)

        # Step 4: Ambiguity detection (GENERATE mode only)
        if mode == RouterMode.GENERATE and len(candidates) >= 2:
            top = candidates[0]
            second = candidates[1]
            confidence_diff = abs(top.confidence - second.confidence)
            if confidence_diff < self._config.intent_ambiguity_range:
                return ClarificationQuestion(
                    question=(
                        "Multiple intents detected with similar confidence. "
                        "Please clarify your intent."
                    ),
                    candidates=candidates,
                )

        # Step 5: Confidence threshold check
        best = candidates[0]
        if best.confidence < self._config.intent_confidence_threshold:
            return ClarificationQuestion(
                question=(
                    "The identified intent has low confidence. "
                    "Could you please provide more details?"
                ),
                candidates=candidates,
            )

        # Step 6: Return the best intent
        return best

    async def _handle_no_candidates(
        self, user_input: str, session_state: SessionState
    ) -> Union[IntentResult, ClarificationQuestion]:
        """处理无候选意图的情况。

        若已注册 fallback handler，调用它获取结果；
        否则返回一个通用的 ClarificationQuestion。

        Args:
            user_input: 用户输入文本。
            session_state: 当前会话状态。

        Returns:
            IntentResult（来自 fallback handler）或 ClarificationQuestion。
        """
        if self._fallback_handler is not None:
            # If fallback handler is an async callable, await it
            if callable(self._fallback_handler):
                result = self._fallback_handler(user_input, session_state)
                if hasattr(result, "__await__"):
                    result = await result
                if isinstance(result, (IntentResult, ClarificationQuestion)):
                    return result
                # If fallback returns something else, wrap it as IntentResult
                return IntentResult(
                    intent_type="fallback",
                    confidence=0.0,
                    parameters={"fallback_result": result},
                )
            # If fallback handler is not callable, return a default fallback intent
            return IntentResult(
                intent_type="fallback",
                confidence=0.0,
                parameters={"handler": str(self._fallback_handler)},
            )

        return ClarificationQuestion(
            question=(
                "I couldn't identify your intent. "
                "Could you please rephrase your request?"
            ),
            candidates=[],
        )
