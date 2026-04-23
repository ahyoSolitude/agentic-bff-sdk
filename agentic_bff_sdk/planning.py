"""Planning and SOP compilation to the unified ExecutionPlan IR."""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod

from agentic_bff_sdk.errors import PlanningError
from agentic_bff_sdk.models import (
    ExecutionPlan,
    ExecutionStep,
    PlanSource,
    RequestContext,
    ResolvedIntent,
    StepKind,
)


class Planner(ABC):
    @abstractmethod
    async def plan(self, intent: ResolvedIntent, context: RequestContext) -> ExecutionPlan:
        ...


class SOPCompiler(ABC):
    @abstractmethod
    async def compile(self, sop_id: str, context: RequestContext) -> ExecutionPlan:
        ...


class DefaultPlanner(Planner):
    async def plan(self, intent: ResolvedIntent, context: RequestContext) -> ExecutionPlan:
        domain = str(intent.parameters.get("domain", "default"))
        action = str(intent.parameters.get("action", intent.intent_name))
        step = ExecutionStep(
            step_id="step_1",
            kind=StepKind.DOMAIN_CALL,
            domain=domain,
            action=action,
            description=f"Execute {action} in {domain}",
            parameters=dict(intent.parameters),
        )
        return ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            source=PlanSource.INTENT,
            intent_name=intent.intent_name,
            steps=[step],
            metadata={"created_at": str(time.time())},
        )


class StaticSOPCompiler(SOPCompiler):
    def __init__(self, sop_definitions: dict[str, list[ExecutionStep]] | None = None) -> None:
        self._sops = sop_definitions or {}

    async def compile(self, sop_id: str, context: RequestContext) -> ExecutionPlan:
        steps = self._sops.get(sop_id)
        if not steps:
            raise PlanningError(f"SOP '{sop_id}' is not registered.")
        return ExecutionPlan(
            plan_id=str(uuid.uuid4()),
            source=PlanSource.SOP,
            intent_name=sop_id,
            steps=steps,
            metadata={"sop_id": sop_id, "created_at": str(time.time())},
        )


def validate_plan(plan: ExecutionPlan) -> None:
    step_ids = {step.step_id for step in plan.steps}
    if not step_ids:
        raise PlanningError("Execution plan must contain at least one step.")
    for step in plan.steps:
        if step.kind in (StepKind.DOMAIN_CALL, StepKind.REACT_AGENT) and (not step.domain or not step.action):
            raise PlanningError(f"Step '{step.step_id}' requires domain and action.")
        for dep in step.dependencies:
            if dep not in step_ids:
                raise PlanningError(f"Step '{step.step_id}' depends on missing step '{dep}'.")
