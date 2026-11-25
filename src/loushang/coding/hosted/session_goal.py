"""Attachment-local Goal coordination over one borrowed Coding Session."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loushang.ai.model import normalize_model_selection
from loushang.ai.model.selection import is_usable_model_selection
from loushang.apphost.integrations._goal_commands import (
    _HostedGoalAttachment,
    _InteractiveGoalStatus,
)
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
    from loushang.coding.adapters.goal import CodingGoal as CodingGoal
    from loushang.coding.session.agent_session import AgentSession


class HostedSessionGoal(_HostedGoalAttachment["CodingGoal"]):
    def __init__(
        self, session: AgentSession, identity: SessionIdentityV1, workspace: Path,
        *, closing: Callable[[], bool], execution_idle: Callable[[], bool],
        title_pending: Callable[[], bool],
    ) -> None:
        self._session, self.identity, self._workspace = session, identity, workspace
        self._execution_idle, self._title_pending = execution_idle, title_pending
        super().__init__(commands=HostedGoalCommands(), closing=closing)


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
        return await self._attach_goal(
            open_owner=lambda: InteractiveGoal.attach(session=self._session),
            create_task=lambda owner, check: cast(InteractiveGoal, owner).create_task(
                task, check_current=check
            ),
            construction_error=GoalConstructionError,
            check_current=check_current,
        )

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

    @property
    def execution_available(self) -> bool:
        return not self.goal_command_running and not self._interactive_goal_lock.locked() and self._session.execution_available and (
            self._interactive_goal_owner is None or not self._session.runtime.execution_admission.execution_reserved
        )
