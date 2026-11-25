"""Retain hosted Goal command receipts and tasks with the original Goal owner."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar, cast
from uuid import uuid4

from loushang.appserver.execution.goal_model import (
    InteractiveGoalCommandStatusV1,
    InteractiveGoalCommandV1,
    InteractiveGoalCommandViewV1,
    InteractiveGoalReviewSubmissionV1,
)

if TYPE_CHECKING:
    from loushang.harnesswork.goal.controller import GoalController


_COMMAND_LIMIT = 256
_Command = InteractiveGoalCommandV1 | InteractiveGoalReviewSubmissionV1


class _GoalOwner(Protocol):
    @property
    def controller(self) -> GoalController: ...


OwnerT = TypeVar("OwnerT", bound=_GoalOwner)


class HostedGoalCommands(Generic[OwnerT]):
    def __init__(
        self, *,
        execute: Callable[[OwnerT, _Command], Awaitable[None]],
        error: type[Exception],
        task_name: str,
    ) -> None:
        self._execute = execute
        self._error = error
        self._task_name = task_name
        self._commands: dict[str, InteractiveGoalCommandViewV1] = {}
        self._requests: dict[str, _Command] = {}
        self._latest: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._started = False
        self._cancel_requested = False
        self._unknown = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def settled(self) -> bool:
        return not self.running and not self._unknown

    @property
    def latest(self) -> InteractiveGoalCommandViewV1 | None:
        return self._commands[self._latest] if self._latest is not None else None

    def submit(
        self,
        owner: OwnerT,
        command: _Command,
        *,
        check_current: Callable[[], None],
        require_idle: Callable[[], None],
    ) -> InteractiveGoalCommandViewV1:
        prior = self._commands.get(command.command_id)
        if prior is not None:
            check_current()
            if self._requests[command.command_id] != command:
                raise self._error("Goal command identity conflict")
            return prior

        controls = command.action in {"pause", "cancel"}
        # Keep space for both controls after accepting the final runnable command.
        if len(self._commands) >= _COMMAND_LIMIT - (0 if controls else 2):
            raise self._error("Hosted Goal command capacity reached")
        if controls:
            return self._control(owner, command, check_current)
        return self._start(owner, command, check_current, require_idle)

    def _record(
        self, command: _Command, status: InteractiveGoalCommandStatusV1,
    ) -> InteractiveGoalCommandViewV1:
        view = InteractiveGoalCommandViewV1(command.command_id, command.action, status)
        self._commands[command.command_id] = view
        self._requests[command.command_id] = command
        self._latest = command.command_id
        return view

    def _control(
        self, owner: OwnerT, command: _Command, check_current: Callable[[], None],
    ) -> InteractiveGoalCommandViewV1:
        if command.action == "cancel":
            if not self.running or self._cancel_requested:
                raise self._error("No cancellable Hosted Goal command")
            check_current()
            # A coroutine cancelled before its first instruction cannot run
            # run_goal's cancellation handler. There is no Work to cancel yet.
            if not self._started and owner.controller.query(command.goal_id).status == "active":
                self._change_state(owner, command.goal_id, "pause", "user_cancel")
            result = self._record(command, "settling")
            self._request_stop()
            return result

        if owner.controller.query(command.goal_id).status != "active" or (
            self.running and (self._cancel_requested or self.latest is not None and self.latest.action in {"accept", "reject"})
        ):
            raise self._error("Goal cannot pause")
        check_current()
        self._change_state(owner, command.goal_id, "pause", "user_pause")
        return self._record(command, "settling" if self.running else "finished")

    def _start(
        self, owner: OwnerT, command: _Command,
        check_current: Callable[[], None], require_idle: Callable[[], None],
    ) -> InteractiveGoalCommandViewV1:
        if self.running or self._unknown or owner.controller.fenced:
            raise self._error("Hosted Goal command unavailable")
        required = "paused" if command.action in {"resume", "accept", "reject"} else "active"
        if owner.controller.query(command.goal_id).status != required:
            raise self._error("Hosted Goal has the wrong state")
        facts = owner.controller.facts()
        if facts.busy or facts.unresolved:
            raise self._error("Original Goal Work is still unsettled")
        require_idle()
        check_current()
        if command.action == "resume":
            self._change_state(owner, command.goal_id, "resume", "user_resume")
        # The journal mutation, task publication and receipt share this no-await cut.
        self._started = self._cancel_requested = False
        published: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        runner = self._run(owner, command, published)
        try:
            self._task = asyncio.create_task(runner, name=self._task_name)
        except Exception:
            runner.close()
            return self._record(command, "failed")
        result = self._record(command, "running")
        published.set_result(None)
        return result

    @staticmethod
    def _change_state(owner: OwnerT, goal_id: str, action: str, reason: str) -> None:
        state = owner.controller.query(goal_id)
        owner.controller.control(
            goal_id, action, command_id=f"hosted-{uuid4().hex}",
            revision=state.revision, epoch=state.epoch, reason=reason,
        )

    async def _run(
        self, owner: OwnerT, command: _Command, published: asyncio.Future[None],
    ) -> None:
        await published
        self._started = True
        status: InteractiveGoalCommandStatusV1 = "finished"
        try:
            if not self._cancel_requested:
                await self._execute(owner, command)
        except asyncio.CancelledError:
            if not self._cancel_requested:
                status = "unknown"
        except Exception:
            status = "failed"
        try:
            facts = owner.controller.facts()
            if owner.controller.fenced or facts.busy or facts.unresolved:
                status = "unknown"
        except Exception:
            status = "unknown"
        self._unknown = status == "unknown"
        for key, view in self._commands.items():
            if view.status in {"running", "settling"}:
                self._commands[key] = replace(view, status=status)

    def _request_stop(self) -> None:
        if self._cancel_requested:
            return
        self._cancel_requested = True
        if self._started and self._task is not None:
            self._task.cancel()

    async def stop(self) -> None:
        task = self._task
        if task is not None and not task.done():
            self._request_stop()
            await asyncio.shield(task)


class _AttachedGoalOwner(_GoalOwner, Protocol):
    @property
    def _closing(self) -> bool: ...

    async def close(self) -> None: ...


AttachedOwnerT = TypeVar("AttachedOwnerT", bound=_AttachedGoalOwner)


@dataclass(frozen=True, slots=True)
class _InteractiveGoalStatus:
    goal_id: str
    status: str
    revision: int
    epoch: int
    execution_unresolved: bool


class _HostedGoalAttachment(Generic[AttachedOwnerT]):
    """Own a Goal attachment from construction through same-owner close retry."""

    def __init__(
        self,
        *,
        commands: HostedGoalCommands[AttachedOwnerT],
        closing: Callable[[], bool],
    ) -> None:
        self._goal_commands = commands
        self._closing = closing
        self._interactive_goal_owner: AttachedOwnerT | None = None
        self._interactive_goal_id: str | None = None
        self._interactive_goal_lock = asyncio.Lock()

    def _require_interactive_goal_admission(self) -> None:
        raise NotImplementedError

    async def _attach_goal(
        self,
        *,
        open_owner: Callable[[], Awaitable[AttachedOwnerT]],
        create_task: Callable[[AttachedOwnerT, Callable[[], None]], Awaitable[str]],
        construction_error: type[RuntimeError],
        check_current: Callable[[], None] | None,
    ) -> _InteractiveGoalStatus:
        if self._interactive_goal_lock.locked():
            raise self._goal_commands._error("Interactive Goal ownership is already changing")
        async with self._interactive_goal_lock:
            self._require_interactive_goal_admission()
            if check_current is not None:
                check_current()
            if self._interactive_goal_owner is not None:
                raise self._goal_commands._error("Hosted Session already owns an interactive Goal")
            try:
                owner = await open_owner()
            except construction_error as error:
                # The construction error carries the original owner for a close retry.
                self._interactive_goal_owner = cast(
                    AttachedOwnerT, getattr(error, "owner")
                )
                raise
            self._interactive_goal_owner = owner

            def check_publication() -> None:
                self._require_interactive_goal_admission()
                if check_current is not None:
                    check_current()

            try:
                goal_id = await create_task(owner, check_publication)
            except BaseException as error:
                try:
                    await self._close_interactive_goal_locked()
                except BaseException as cleanup:
                    raise construction_error(owner, error) from cleanup
                raise
            self._interactive_goal_id = goal_id
            return self._interactive_goal_status(owner, goal_id)

    def _review_available(self, owner: AttachedOwnerT, goal_id: str) -> bool:
        state = owner.controller.query(goal_id)
        if (
            state.status != "paused"
            or state.reason != "review_required"
            or not self._goal_commands.settled
            or owner.controller.fenced
        ):
            return False
        facts = owner.controller.facts()
        return not facts.busy and not facts.unresolved

    def _current_goal_owner(self, goal_id: str) -> AttachedOwnerT:
        owner = self._interactive_goal_owner
        if (
            self._closing()
            or owner is None
            or owner._closing
            or goal_id != self._interactive_goal_id
        ):
            raise self._goal_commands._error("current hosted Goal unavailable")
        return owner

    def interactive_goal_status(self) -> _InteractiveGoalStatus | None:
        if self._closing() or self._interactive_goal_lock.locked():
            raise self._goal_commands._error("Hosted interactive Goal is changing ownership or closing")
        owner, goal_id = self._interactive_goal_owner, self._interactive_goal_id
        if owner is None:
            return None
        if goal_id is None:
            raise self._goal_commands._error("Interactive Goal construction cleanup is pending")
        return self._interactive_goal_status(owner, goal_id)

    @staticmethod
    def _interactive_goal_status(owner: AttachedOwnerT, goal_id: str) -> _InteractiveGoalStatus:
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
