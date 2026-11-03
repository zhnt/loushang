"""One bounded, disposable Product planning slot over Resource-owned work."""

from __future__ import annotations

import asyncio
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


class ResumePlanningSlot:
    """Retain at most one waiter and one completed data-only Plan.

    Resource retains native work and capacity after a waiter leaves. This slot
    owns only its reference; it never closes a shared ResourceLoader or retains
    selected Packages, receipts, journals, approval facts or Runtime authority.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[SessionActivationPlanV1] | None = None
        self._key: tuple[object, ...] | None = None
        self._plan: SessionActivationPlanV1 | None = None
        self._closed = False
        self._transition = asyncio.Lock()

    def _on_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("coding_resume_planning_loop_changed")

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
        async with self._transition:
            if self._closed:
                raise RuntimeError("coding_resume_planning_closed")
            if key == self._key and (self._task is not None or self._plan is not None):
                return
            await self._discard_reference()
            self._key = key
            work = plan_coding_resume_async(
                history,
                current_composition,
                workspace_root=workspace_root,
                resource_loader=resource_loader,
                subject_digest=subject_digest,
                policy_digest=policy_digest,
                max_work_units=max_work_units,
                time_budget_seconds=time_budget_seconds,
                priority="background",
            )
            try:
                task = asyncio.create_task(work)
            except BaseException:
                work.close()
                raise
            self._task = task

            def complete(done: asyncio.Task[SessionActivationPlanV1]) -> None:
                if done.cancelled():
                    result = None
                else:
                    # Observe errors without a foreground waiter.
                    error = done.exception()
                    result = done.result() if error is None else None
                if self._task is done:
                    self._task = None
                    if not self._closed and self._key == key:
                        self._plan = result

            task.add_done_callback(complete)

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

    async def discard(self) -> None:
        """Drop cached data and settle this slot's Resource waiter reference."""

        self._on_loop()
        async with self._transition:
            await self._discard_reference()

    async def _discard_reference(self) -> None:
        self._plan = None
        self._key = None
        task = self._task
        if task is None:
            return
        task.cancel()
        cancellation = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as error:
                caller = asyncio.current_task()
                if caller is not None and caller.cancelling():
                    cancellation = error
            except Exception:
                break
        if self._task is task:
            self._task = None
        if cancellation is not None:
            raise cancellation

    async def close(self) -> None:
        if self._closed and self._task is None:
            return
        if self._loop is None:
            self._closed = True
            return
        self._on_loop()
        async with self._transition:
            self._closed = True
            await self._discard_reference()
