"""One bounded, disposable Product planning slot over Resource-owned work."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TypeVar
from weakref import ref as ref

from loushang.coding.composition.sets import CodingCompositionSetPlan
from loushang.coding.resume.activation_plan import (
    ActivationOwnerInputRefV1,
    SessionActivationPlanV1,
    _resume_domain_input_refs,
)
from loushang.coding.resume.activation_plan import (
    ResumePlanStaleError as ResumePlanStaleError,
)
from loushang.coding.resume.activation_plan import (
    build_session_activation_plan as build_session_activation_plan,
)
from loushang.coding.resume.activation_plan import (
    plan_coding_resume_async as plan_coding_resume_async,
)
from loushang.coding.resume.activation_plan import (
    require_current_resume_plan_inputs as require_current_resume_plan_inputs,
)
from loushang.coding.resume.activation_plan import (
    require_current_resume_plan_source as require_current_resume_plan_source,
)
from loushang.coding.resume.history import CodingResumeHistoryPreview
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.session.agent_product_runtime import _SessionPlanningSlot

_PlanningResultT = TypeVar("_PlanningResultT")


@dataclass(frozen=True, slots=True)
class ResumePlanningConfiguration:
    """Observe the same Product-owned inputs for background and foreground planning."""

    current_composition: CodingCompositionSetPlan
    workspace_root: Path
    resource_loader: ResourceLoader
    subject_digest: Callable[[], str]
    policy_digest: Callable[[], str]
    max_work_units: int = 200
    time_budget_seconds: float = 5.0

    def plan(
        self, operation: Callable[..., _PlanningResultT], history: CodingResumeHistoryPreview,
    ) -> _PlanningResultT:
        return operation(
            history, self.current_composition,
            workspace_root=self.workspace_root,
            resource_loader=self.resource_loader,
            subject_digest=self.subject_digest(),
            policy_digest=self.policy_digest(),
            max_work_units=self.max_work_units,
            time_budget_seconds=self.time_budget_seconds,
        )

    async def foreground(self, history: CodingResumeHistoryPreview) -> SessionActivationPlanV1:
        from loushang.coding.resume.activation_plan import plan_coding_resume_async

        return await self.plan(partial(plan_coding_resume_async, priority="foreground"), history)


class ResumePlanningSlot(_SessionPlanningSlot[SessionActivationPlanV1]):
    """Retain at most one waiter and one completed data-only Plan.

    Resource retains native work and capacity after a waiter leaves. This slot
    owns only its reference; it never closes a shared ResourceLoader or retains
    selected Packages, receipts, journals, approval facts or Runtime authority.
    """

    _error_prefix = "coding_resume_planning"

    async def start(
        self,
        history: CodingResumeHistoryPreview,
        current_composition: CodingCompositionSetPlan,
        *,
        workspace_root: Path,
        resource_loader: ResourceLoader,
        subject_digest: str,
        policy_digest: str,
        max_work_units: int,
        time_budget_seconds: float,
    ) -> None:
        """Start background pure-data work; no result admits continuation."""

        await self._start_validated_planning(
            lambda: build_session_activation_plan(
                history,
                current_composition,
                workspace_root=workspace_root,
                owner_inputs=_resume_domain_input_refs(
                    policy_digest=policy_digest, subject_digest=subject_digest
                ),
            ),
            resource_loader,
            max_work_units=max_work_units,
            time_budget_seconds=time_budget_seconds,
            work_factory=lambda: plan_coding_resume_async(
                history,
                current_composition,
                workspace_root=workspace_root,
                resource_loader=resource_loader,
                subject_digest=subject_digest,
                policy_digest=policy_digest,
                max_work_units=max_work_units,
                time_budget_seconds=time_budget_seconds,
                priority="background",
            ),
        )

    def current(
        self,
        history: CodingResumeHistoryPreview,
        *,
        current_owner_inputs: Sequence[ActivationOwnerInputRefV1],
    ) -> SessionActivationPlanV1 | None:
        """Return only after source and fresh owner dependency comparisons.

        The caller obtains these current observations from their original
        owners. A match grants neither Writer access nor executable authority.
        """

        def require_current(plan: SessionActivationPlanV1) -> None:
            require_current_resume_plan_source(plan, history)
            require_current_resume_plan_inputs(plan, current_owner_inputs)

        return self._current_validated_plan(
            require_current, stale_error=ResumePlanStaleError
        )
