"""One bounded, disposable Product planning slot over Resource-owned work."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from weakref import ref

from loushang.coding.composition_sets import CodingCompositionSetPlan
from loushang.coding.resume_activation_plan import (
    ActivationOwnerInputRefV1,
    ResumePlanStaleError,
    SessionActivationPlanV1,
    build_session_activation_plan,
    plan_coding_resume_async,
    require_current_resume_plan_inputs,
    require_current_resume_plan_source,
)
from loushang.coding.resume_history import CodingResumeHistoryPreview
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.session.agent_product_runtime import _SessionPlanningSlot


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

        self._on_loop()
        if self._closed:
            raise RuntimeError("coding_resume_planning_closed")
        # Validate all envelope inputs before scheduling. These are dependency
        # observations, without approval/selection meaning.
        baseline = build_session_activation_plan(
            history,
            current_composition,
            workspace_root=workspace_root,
            owner_inputs=(
                ActivationOwnerInputRefV1("coding.policy", policy_digest),
                ActivationOwnerInputRefV1("coding.subject", subject_digest),
            ),
        )
        if type(max_work_units) is not int or max_work_units < 1:
            raise ValueError("invalid Resume planning work budget")
        if (
            type(time_budget_seconds) not in {int, float}
            or not 0 < time_budget_seconds <= 60
        ):
            raise ValueError("invalid Resume planning time budget")
        if not isinstance(resource_loader, ResourceLoader):
            raise TypeError("Resume planning requires the original ResourceLoader")
        key = (
            baseline.plan_id,
            ref(resource_loader),
            max_work_units,
            time_budget_seconds,
        )
        await self._start_work(
            key,
            lambda: plan_coding_resume_async(
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

        self._on_loop()
        if self._closed:
            return None
        plan = self._plan
        if plan is None:
            return None
        try:
            require_current_resume_plan_source(plan, history)
            require_current_resume_plan_inputs(plan, current_owner_inputs)
        except ResumePlanStaleError:
            self._plan = None
            self._key = None
            return None
        return plan
