"""Property-based tests for the BatchSOPRunner module.

Uses Hypothesis to verify correctness properties of the DefaultBatchSOPRunner
across randomized inputs: exception handling strategies and interaction scene
dialog template matching.
"""

import time
from typing import Any, Dict, List, Optional

import pytest
from hypothesis import given, settings, strategies as st

from agentic_bff_sdk.blackboard import Blackboard
from agentic_bff_sdk.config import InteractionScene, SOPDefinition
from agentic_bff_sdk.models import ExecutionPlan, IntentResult, PlanStep
from agentic_bff_sdk.sop_runner import (
    DefaultBatchSOPRunner,
    MAX_RETRY_ATTEMPTS,
)


# ============================================================
# Helpers
# ============================================================


def _make_intent() -> IntentResult:
    return IntentResult(intent_type="test", confidence=0.9)


def _make_plan() -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="prop-plan",
        intent=_make_intent(),
        steps=[],
        created_at=time.time(),
    )


def _make_sop(
    exception_policies: Dict[str, str] | None = None,
    dialog_templates: Dict[InteractionScene, str] | None = None,
    steps: List[Dict[str, Any]] | None = None,
) -> SOPDefinition:
    return SOPDefinition(
        sop_id="prop-sop",
        name="Property Test SOP",
        steps=steps or [{"domain": "d1", "action": "a1", "parameters": {}}],
        exception_policies=exception_policies or {},
        dialog_templates=dialog_templates or {},
    )


# ============================================================
# Strategies
# ============================================================

# Exception policy choices
exception_policy_st = st.sampled_from(["retry", "skip", "rollback"])

# Built-in exception classes suitable for testing
_EXCEPTION_CLASSES: List[type] = [
    ValueError,
    TypeError,
    KeyError,
    RuntimeError,
    IOError,
    AttributeError,
    IndexError,
    OSError,
    LookupError,
    ArithmeticError,
]

exception_class_st = st.sampled_from(_EXCEPTION_CLASSES)

# InteractionScene values
interaction_scene_st = st.sampled_from(list(InteractionScene))

# Safe template text
template_text_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z"), whitelist_characters=".,!?-_ "),
    min_size=1,
    max_size=200,
)

# Dialog template mappings: random subset of scenes mapped to template strings
dialog_templates_st = st.dictionaries(
    keys=interaction_scene_st,
    values=template_text_st,
    min_size=0,
    max_size=3,
)


# ============================================================
# Property 14: SOP 异常处理策略正确执行
# ============================================================


@pytest.mark.property
class TestProperty14ExceptionHandlingPolicy:
    """Property 14: SOP 异常处理策略正确执行

    *For any* domain call failure and configured exception handling policy
    (retry/skip/rollback), the BatchSOPRunner SHALL execute the recovery
    action matching the policy.

    **Validates: Requirements 5.5**
    """

    @given(
        policy=exception_policy_st,
        error_cls=exception_class_st,
        error_msg=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_retry_policy_retries_up_to_max_attempts(
        self, policy: str, error_cls: type, error_msg: str
    ) -> None:
        """When policy is 'retry', the runner retries up to MAX_RETRY_ATTEMPTS times."""
        if policy != "retry":
            return  # Only test retry in this method

        error_type_name = error_cls.__name__
        call_count = {"n": 0}

        async def always_failing_executor(
            domain: str,
            action: str,
            parameters: Dict[str, Any],
            blackboard: Blackboard,
        ) -> Dict[str, Any]:
            call_count["n"] += 1
            raise error_cls(error_msg)

        runner = DefaultBatchSOPRunner(step_executor=always_failing_executor)
        sop = _make_sop(
            exception_policies={error_type_name: "retry"},
            steps=[{"domain": "test_domain", "action": "test_action", "parameters": {}}],
        )
        bb = Blackboard()
        plan = _make_plan()

        results = await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

        assert len(results) == 1
        result = results[0]
        # After original call fails, retry MAX_RETRY_ATTEMPTS times
        # Total calls = 1 (original) + MAX_RETRY_ATTEMPTS (retries)
        assert call_count["n"] == 1 + MAX_RETRY_ATTEMPTS, (
            f"Expected {1 + MAX_RETRY_ATTEMPTS} total calls, got {call_count['n']}"
        )
        assert result["status"] == "failed"
        assert result["policy_applied"] == "retry_exhausted"

    @given(
        error_cls=exception_class_st,
        error_msg=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_skip_policy_returns_skipped_status(
        self, error_cls: type, error_msg: str
    ) -> None:
        """When policy is 'skip', the runner returns a result with status 'skipped'."""
        error_type_name = error_cls.__name__

        async def failing_executor(
            domain: str,
            action: str,
            parameters: Dict[str, Any],
            blackboard: Blackboard,
        ) -> Dict[str, Any]:
            raise error_cls(error_msg)

        runner = DefaultBatchSOPRunner(step_executor=failing_executor)
        sop = _make_sop(
            exception_policies={error_type_name: "skip"},
            steps=[{"domain": "test_domain", "action": "test_action", "parameters": {}}],
        )
        bb = Blackboard()
        plan = _make_plan()

        results = await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

        assert len(results) == 1
        result = results[0]
        assert result["status"] == "skipped", (
            f"Expected 'skipped' status for skip policy, got '{result['status']}'"
        )
        assert result["policy_applied"] == "skip"
        # The error field contains str(exception). Some exception types like
        # KeyError wrap the message in repr-style quotes, so we check that
        # the error field matches str(error_cls(error_msg)).
        expected_error_str = str(error_cls(error_msg))
        assert result.get("error", "") == expected_error_str

    @given(
        error_cls=exception_class_st,
        error_msg=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_rollback_policy_raises_runtime_error(
        self, error_cls: type, error_msg: str
    ) -> None:
        """When policy is 'rollback', the runner raises RuntimeError."""
        error_type_name = error_cls.__name__

        async def failing_executor(
            domain: str,
            action: str,
            parameters: Dict[str, Any],
            blackboard: Blackboard,
        ) -> Dict[str, Any]:
            raise error_cls(error_msg)

        runner = DefaultBatchSOPRunner(step_executor=failing_executor)
        sop = _make_sop(
            exception_policies={error_type_name: "rollback"},
            steps=[{"domain": "test_domain", "action": "test_action", "parameters": {}}],
        )
        bb = Blackboard()
        plan = _make_plan()

        with pytest.raises(RuntimeError, match="Rollback triggered"):
            await runner.execute(plan, sop, InteractionScene.ONLINE, bb)

    @given(
        policy=exception_policy_st,
        error_cls=exception_class_st,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_policy_matches_error_type_name(
        self, policy: str, error_cls: type
    ) -> None:
        """The exception policy lookup uses the exception class name as key."""
        error_type_name = error_cls.__name__
        call_count = {"n": 0}

        async def failing_executor(
            domain: str,
            action: str,
            parameters: Dict[str, Any],
            blackboard: Blackboard,
        ) -> Dict[str, Any]:
            call_count["n"] += 1
            raise error_cls("test error")

        runner = DefaultBatchSOPRunner(step_executor=failing_executor)
        sop = _make_sop(
            exception_policies={error_type_name: policy},
            steps=[{"domain": "d", "action": "a", "parameters": {}}],
        )
        bb = Blackboard()
        plan = _make_plan()

        if policy == "rollback":
            with pytest.raises(RuntimeError, match="Rollback triggered"):
                await runner.execute(plan, sop, InteractionScene.ONLINE, bb)
        else:
            results = await runner.execute(plan, sop, InteractionScene.ONLINE, bb)
            assert len(results) == 1
            if policy == "skip":
                assert results[0]["status"] == "skipped"
            elif policy == "retry":
                assert results[0]["status"] == "failed"
                assert results[0]["policy_applied"] == "retry_exhausted"


# ============================================================
# Property 15: 交互场景对话模板匹配
# ============================================================


@pytest.mark.property
class TestProperty15DialogTemplateMatching:
    """Property 15: 交互场景对话模板匹配

    *For any* InteractionScene, the BatchSOPRunner SHALL select the
    corresponding dialog template from the SOPDefinition, or return None
    if the scene is not configured.

    **Validates: Requirements 5.2**
    """

    @given(
        scene=interaction_scene_st,
        templates=dialog_templates_st,
    )
    @settings(max_examples=100)
    def test_select_template_matches_scene(
        self, scene: InteractionScene, templates: Dict[InteractionScene, str]
    ) -> None:
        """select_dialog_template returns the correct template for the given scene."""
        sop = _make_sop(dialog_templates=templates)
        runner = DefaultBatchSOPRunner()

        result = runner.select_dialog_template(sop, scene)

        if scene in templates:
            assert result == templates[scene], (
                f"Expected template '{templates[scene]}' for scene {scene}, "
                f"got '{result}'"
            )
        else:
            assert result is None, (
                f"Expected None for unconfigured scene {scene}, got '{result}'"
            )

    @given(
        template_text=template_text_st,
    )
    @settings(max_examples=100)
    def test_all_scenes_with_full_mapping(
        self, template_text: str
    ) -> None:
        """When all scenes are mapped, every scene returns a template."""
        templates = {scene: f"{template_text}_{scene.value}" for scene in InteractionScene}
        sop = _make_sop(dialog_templates=templates)
        runner = DefaultBatchSOPRunner()

        for scene in InteractionScene:
            result = runner.select_dialog_template(sop, scene)
            assert result is not None, f"Expected template for scene {scene}, got None"
            assert result == templates[scene]

    @given(scene=interaction_scene_st)
    @settings(max_examples=100)
    def test_empty_templates_returns_none(
        self, scene: InteractionScene
    ) -> None:
        """When dialog_templates is empty, all scenes return None."""
        sop = _make_sop(dialog_templates={})
        runner = DefaultBatchSOPRunner()

        result = runner.select_dialog_template(sop, scene)
        assert result is None, (
            f"Expected None for empty templates with scene {scene}, got '{result}'"
        )

    @given(
        scene=interaction_scene_st,
        templates=dialog_templates_st,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_execute_writes_template_to_blackboard(
        self, scene: InteractionScene, templates: Dict[InteractionScene, str]
    ) -> None:
        """During execute, the selected template is written to Blackboard if present."""
        sop = _make_sop(
            dialog_templates=templates,
            steps=[{"domain": "d1", "action": "a1", "parameters": {}}],
        )
        runner = DefaultBatchSOPRunner()
        bb = Blackboard()
        plan = _make_plan()

        await runner.execute(plan, sop, scene, bb)

        bb_key = f"sop_{sop.sop_id}_dialog_template"
        stored_template = await bb.get(bb_key)

        if scene in templates:
            assert stored_template == templates[scene], (
                f"Expected Blackboard to contain '{templates[scene]}', "
                f"got '{stored_template}'"
            )
        else:
            assert stored_template is None, (
                f"Expected Blackboard to have None for unconfigured scene, "
                f"got '{stored_template}'"
            )
