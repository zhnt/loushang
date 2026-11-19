"""Attachment-local Goal coordination over one borrowed Coding Session."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loushang.ai.model import normalize_model_selection
from loushang.ai.model.selection import is_usable_model_selection
from loushang.appserver.execution.goal_model import (
    ExecutionGoalStatusV1,
    InteractiveGoalCommandV1,
    InteractiveGoalReviewSubmissionV1,
    InteractiveGoalReviewV1,
    InteractiveGoalViewV1,
)
from loushang.appserver.protocol import SessionIdentityV1
from loushang.coding.hosted.goal_commands import HostedGoalCommands
from loushang.coding.hosted.goal_review import summarize_review
from loushang.harness.journal._owned_io import settled_io
from loushang.harness.session.execution_admission import SessionExecutionUnavailable
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.goal.tasks import GoalTask

if TYPE_CHECKING:
    from loushang.coding.adapters.goal import CodingGoal
    from loushang.coding.session.agent_session import AgentSession


@dataclass(frozen=True, slots=True)
class _InteractiveGoalStatus:
    goal_id: str
    status: str
    revision: int
    epoch: int
    execution_unresolved: bool


class HostedSessionGoal:
    def __init__(
        self, session: AgentSession, identity: SessionIdentityV1, workspace: Path,
        *, closing: Callable[[], bool], execution_idle: Callable[[], bool],
        title_pending: Callable[[], bool],
    ) -> None:
        self._session, self.identity, self._workspace = session, identity, workspace
        self._closing, self._execution_idle, self._title_pending = closing, execution_idle, title_pending
        self._interactive_goal_owner: CodingGoal | None = None
        self._interactive_goal_id: str | None = None
        self._interactive_goal_lock = asyncio.Lock()
        self._goal_commands = HostedGoalCommands()

    def _require_interactive_goal_admission(self) -> None:
        session = self._session
        if self._closing() or not session.execution_available:
            raise GoalError("Hosted Session is unavailable for an interactive Goal")
        if not self._execution_idle():
            raise GoalError("Hosted execution is busy, closing, or reserved for a fixed profile")
        if self._title_pending():
            raise GoalError("Hosted Session is finishing title generation")
        if not is_usable_model_selection(normalize_model_selection(session.agent.model)):
            raise GoalError("Interactive Goal requires the current Hosted model")
        manager = session.session_manager
        if not manager.is_persisted():
            raise GoalError("Interactive Goal requires a persistent Transcript")
        if not self._matches_goal_session():
            raise GoalError("Interactive Goal requires the original Hosted Session and Workspace")

    def _matches_goal_session(self) -> bool:
        return (
            self._session.session_id == self.identity.session_id
            and Path(self._session.session_manager.get_cwd()).resolve() == self._workspace
        )

    async def create_interactive_goal(
        self, target: str, *, check_current: Callable[[], None] | None = None,
    ) -> _InteractiveGoalStatus:
        """Bind the current Product Session and record one user target."""
        from loushang.coding.adapters.goal import GoalConstructionError
        from loushang.coding.adapters.interactive_goal import InteractiveGoal

        task = GoalTask(target)
        if self._interactive_goal_lock.locked():
            raise GoalError("Interactive Goal ownership is already changing")
        async with self._interactive_goal_lock:
            self._require_interactive_goal_admission()
            if check_current is not None:
                check_current()
            if self._interactive_goal_owner is not None:
                raise GoalError("Hosted Session already owns an interactive Goal")
            try:
                owner = await InteractiveGoal.attach(session=self._session)
            except GoalConstructionError as error:
                self._interactive_goal_owner = error.owner
                raise
            self._interactive_goal_owner = owner

            def check_publication() -> None:
                self._require_interactive_goal_admission()
                if check_current is not None:
                    check_current()

            try:
                goal_id = await owner.create_task(task, check_current=check_publication)
            except BaseException as error:
                try:
                    await self._close_interactive_goal_locked()
                except BaseException as cleanup:
                    raise GoalConstructionError(owner, error) from cleanup
                raise
            self._interactive_goal_id = goal_id
            return self._interactive_goal_status(owner, goal_id)

    def _attached_interactive_goal_view(self) -> InteractiveGoalViewV1 | None:
        owner, goal_id = self._interactive_goal_owner, self._interactive_goal_id
        if owner is not None and owner._closing:
            return InteractiveGoalViewV1("cleanup_pending")
        if self._interactive_goal_lock.locked() and goal_id is None:
            return InteractiveGoalViewV1("creating")
        if owner is None:
            return None
        if goal_id is None:
            return InteractiveGoalViewV1("cleanup_pending")
        view = self._interactive_goal_status(owner, goal_id)
        return InteractiveGoalViewV1(
            "present", view.goal_id, cast(ExecutionGoalStatusV1, view.status),
            view.revision, view.epoch, view.execution_unresolved, self._goal_commands.latest,
            review_available=self._review_available(owner, goal_id),
        )

    def _review_available(self, owner: CodingGoal, goal_id: str) -> bool:
        state = owner.controller.query(goal_id)
        if (state.status != "paused" or state.reason != "review_required"
                or not self._goal_commands.settled or owner.controller.fenced):
            return False
        facts = owner.controller.facts()
        return not facts.busy and not facts.unresolved

    def _current_goal_owner(self, goal_id: str) -> CodingGoal:
        owner = self._interactive_goal_owner
        if (self._closing() or owner is None or owner._closing
                or goal_id != self._interactive_goal_id):
            raise GoalError("current hosted Goal unavailable")
        return owner

    def _require_goal_idle(self) -> None:
        self._require_interactive_goal_admission()
        admission = self._session.runtime.execution_admission
        admission.require_current()
        if admission.execution_reserved:
            raise GoalError("Session already reserved")

    async def interactive_goal_review(
        self, goal_id: str, *, check_current: Callable[[], None],
    ) -> InteractiveGoalReviewV1:
        from loushang.coding.adapters.interactive_goal import InteractiveGoal

        if self._interactive_goal_lock.locked():
            raise GoalError("current hosted Goal busy")
        async with self._interactive_goal_lock:
            owner = self._current_goal_owner(goal_id)
            self._require_goal_idle()
            if not isinstance(owner, InteractiveGoal) or not self._review_available(owner, goal_id):
                raise GoalError("current hosted Goal is not ready for review")
            check_current()
            result = await summarize_review(owner, goal_id)
            self._current_goal_owner(goal_id)
            check_current()
            return result

    def control_interactive_goal(
        self, command: InteractiveGoalCommandV1 | InteractiveGoalReviewSubmissionV1,
        *, check_current: Callable[[], None],
    ) -> InteractiveGoalViewV1:
        if self._interactive_goal_lock.locked():
            raise GoalError("current hosted Goal busy")
        owner = self._current_goal_owner(command.goal_id)

        def require_idle() -> None:
            self._require_goal_idle()
            if isinstance(command, InteractiveGoalReviewSubmissionV1) and not self._review_available(owner, command.goal_id):
                raise GoalError("current hosted Goal is not ready for review")

        outcome = self._goal_commands.submit(owner, command, check_current=check_current, require_idle=require_idle)
        view = self._attached_interactive_goal_view()
        assert view is not None
        return replace(view, command=outcome)

    async def interactive_goal_view(self) -> InteractiveGoalViewV1:
        from loushang.coding.adapters.interactive_goal import (
            InteractiveGoal,
            read_task_history,
        )

        attached = self._attached_interactive_goal_view()
        if attached is not None:
            return attached
        if not self._matches_goal_session() or not self._session.session_manager.is_persisted():
            return InteractiveGoalViewV1("not_ready")
        try:
            history = await settled_io(read_task_history, self._session, missing_ok=True)
        except (GoalError, OSError):
            # A creator may have acquired the original journal while this read was in flight.
            attached = self._attached_interactive_goal_view()
            if attached is not None:
                return attached
            raise
        attached = self._attached_interactive_goal_view()
        if attached is not None:
            return attached
        if history is not None and history.goals:
            return InteractiveGoalViewV1("historical")
        try:
            self._require_interactive_goal_admission()
            self._session.runtime.execution_admission.require_current()
            InteractiveGoal.require_session_tools(self._session, self._workspace)
        except (GoalError, SessionExecutionUnavailable):
            return InteractiveGoalViewV1("not_ready")
        return InteractiveGoalViewV1("ready")

    def interactive_goal_status(self) -> _InteractiveGoalStatus | None:
        if self._closing() or self._interactive_goal_lock.locked():
            raise GoalError("Hosted interactive Goal is changing ownership or closing")
        owner, goal_id = self._interactive_goal_owner, self._interactive_goal_id
        if owner is None:
            return None
        if goal_id is None:
            raise GoalError("Interactive Goal construction cleanup is pending")
        return self._interactive_goal_status(owner, goal_id)

    @staticmethod
    def _interactive_goal_status(owner: CodingGoal, goal_id: str) -> _InteractiveGoalStatus:
        core = owner.controller
        state = core.query(goal_id)
        return _InteractiveGoalStatus(
            state.id, state.status, state.revision, state.epoch,
            core.fenced or core.facts().unresolved,
        )

    async def close_interactive_goal(self) -> None:
        """Retire the borrowed Goal scope before releasing the original Session."""
        async with self._interactive_goal_lock:
            await self._close_interactive_goal_locked()

    async def _close_interactive_goal_locked(self) -> None:
        owner = self._interactive_goal_owner
        if owner is not None:
            await self._goal_commands.stop()
            await owner.close()
            self._interactive_goal_owner = None
            self._interactive_goal_id = None

    @property
    def goal_command_running(self) -> bool:
        return self._goal_commands.running

    @property
    def execution_available(self) -> bool:
        return not self.goal_command_running and not self._interactive_goal_lock.locked() and self._session.execution_available and (
            self._interactive_goal_owner is None or not self._session.runtime.execution_admission.execution_reserved
        )
