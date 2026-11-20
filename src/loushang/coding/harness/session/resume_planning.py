"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.resume.activation_plan import _resume_domain_input_refs
from loushang.coding.runtime import resume_planning as _binding


async def start_planning(
    self: _binding.ResumePlanningSlot,
    history: _binding.CodingResumeHistoryPreview,
    current_composition: _binding.CodingCompositionSetPlan,
    *,
    workspace_root: _binding.Path,
    resource_loader: _binding.ResourceLoader,
    subject_digest: str,
    policy_digest: str,
    max_work_units: int,
    time_budget_seconds: float,
) -> None:
    """Start background pure-data work; no result admits continuation."""

    self._on_loop()
    if self._closed:
        raise RuntimeError(_binding._CONTINUATION_PROGRAM_VALUES["value_001"])
    # Validate all envelope inputs before scheduling. These are dependency
    # observations, without approval/selection meaning.
    baseline = _binding.build_session_activation_plan(
        history,
        current_composition,
        workspace_root=workspace_root,
        owner_inputs=_resume_domain_input_refs(
            policy_digest=policy_digest, subject_digest=subject_digest
        ),
    )
    if type(max_work_units) is not int or max_work_units < 1:
        raise ValueError(_binding._CONTINUATION_PROGRAM_VALUES["value_002"])
    if (
        type(time_budget_seconds) not in {int, float}
        or not 0 < time_budget_seconds <= 60
    ):
        raise ValueError(_binding._CONTINUATION_PROGRAM_VALUES["value_003"])
    if not isinstance(resource_loader, _binding.ResourceLoader):
        raise TypeError(_binding._CONTINUATION_PROGRAM_VALUES["value_004"])
    key = (
        baseline.plan_id,
        _binding.ref(resource_loader),
        max_work_units,
        time_budget_seconds,
    )
    await self._start_work(
        key,
        lambda: _binding.plan_coding_resume_async(
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


def current_plan(
    self: _binding.ResumePlanningSlot,
    history: _binding.CodingResumeHistoryPreview,
    *,
    current_owner_inputs: _binding.Sequence[_binding.ActivationOwnerInputRefV1],
) -> _binding.SessionActivationPlanV1 | None:
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
        _binding.require_current_resume_plan_source(plan, history)
        _binding.require_current_resume_plan_inputs(plan, current_owner_inputs)
    except _binding.ResumePlanStaleError:
        self._plan = None
        self._key = None
        return None
    return plan
