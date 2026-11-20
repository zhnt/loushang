"""One bounded, disposable Product planning slot over Resource-owned work."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from weakref import ref as ref

from loushang.coding.composition.sets import CodingCompositionSetPlan
from loushang.coding.harness.session import resume_planning as _continuation_programs
from loushang.coding.resume.activation_plan import (
    ActivationOwnerInputRefV1,
    SessionActivationPlanV1,
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

_CONTINUATION_PROGRAM_VALUES = {
    "value_001": "coding_resume_planning_closed",
    "value_002": "invalid Resume planning work budget",
    "value_003": "invalid Resume planning time budget",
    "value_004": "Resume planning requires the original ResourceLoader",
    "value_005": "coding.policy",
    "value_006": "coding.subject",
}


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

        return await _continuation_programs.start_planning(
            self,
            history,
            current_composition,
            workspace_root=workspace_root,
            resource_loader=resource_loader,
            subject_digest=subject_digest,
            policy_digest=policy_digest,
            max_work_units=max_work_units,
            time_budget_seconds=time_budget_seconds,
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

        return _continuation_programs.current_plan(
            self, history, current_owner_inputs=current_owner_inputs
        )
