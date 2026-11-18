"""The Hosted Product's finite invocation of its existing Goal advance port."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import uuid4

from loushang.appserver.execution.model import (
    InteractiveGoalCommandStatusV1,
    InteractiveGoalCommandV1,
    InteractiveGoalCommandViewV1,
    InteractiveGoalReviewSubmissionV1,
)
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.integrations.goal_run import run_goal

from .hosted_goal_review import execute_review

if TYPE_CHECKING:
    from .adapters.goal import CodingGoal


_COMMAND_LIMIT = 256
_Command = InteractiveGoalCommandV1 | InteractiveGoalReviewSubmissionV1


class HostedGoalCommands:
    def __init__(self) -> None:
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
        owner: CodingGoal,
        command: _Command,
        *,
        check_current: Callable[[], None],
        require_idle: Callable[[], None],
    ) -> InteractiveGoalCommandViewV1:
        prior = self._commands.get(command.command_id)
        if prior is not None:
            check_current()
            if self._requests[command.command_id] != command:
                raise GoalError("Goal command identity conflict")
            return prior

        controls = command.action in {"pause", "cancel"}
        # Keep space for both controls after accepting the final runnable command.
        if len(self._commands) >= _COMMAND_LIMIT - (0 if controls else 2):
            raise GoalError("Hosted Goal command capacity reached")
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
        self, owner: CodingGoal, command: _Command, check_current: Callable[[], None],
    ) -> InteractiveGoalCommandViewV1:
        if command.action == "cancel":
            if not self.running or self._cancel_requested:
                raise GoalError("No cancellable Hosted Goal command")
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
            raise GoalError("Goal cannot pause")
        check_current()
        self._change_state(owner, command.goal_id, "pause", "user_pause")
        return self._record(command, "settling" if self.running else "finished")

    def _start(
        self, owner: CodingGoal, command: _Command,
        check_current: Callable[[], None], require_idle: Callable[[], None],
    ) -> InteractiveGoalCommandViewV1:
        if self.running or self._unknown or owner.controller.fenced:
            raise GoalError("Hosted Goal command unavailable")
        required = "paused" if command.action in {"resume", "accept", "reject"} else "active"
        if owner.controller.query(command.goal_id).status != required:
            raise GoalError("Hosted Goal has the wrong state")
        facts = owner.controller.facts()
        if facts.busy or facts.unresolved:
            raise GoalError("Original Goal Work is still unsettled")
        require_idle()
        check_current()
        if command.action == "resume":
            self._change_state(owner, command.goal_id, "resume", "user_resume")
        # The journal mutation, task publication and receipt share this no-await cut.
        self._started = self._cancel_requested = False
        published: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        runner = self._run(owner, command, published)
        try:
            self._task = asyncio.create_task(runner, name="coding-hosted-goal-command")
        except Exception:
            runner.close()
            return self._record(command, "failed")
        result = self._record(command, "running")
        published.set_result(None)
        return result

    @staticmethod
    def _change_state(owner: CodingGoal, goal_id: str, action: str, reason: str) -> None:
        state = owner.controller.query(goal_id)
        owner.controller.control(
            goal_id, action, command_id=f"hosted-{uuid4().hex}",
            revision=state.revision, epoch=state.epoch, reason=reason,
        )

    async def _run(
        self, owner: CodingGoal, command: _Command, published: asyncio.Future[None],
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

    @staticmethod
    async def _execute(owner: CodingGoal, command: _Command) -> None:
        if isinstance(command, InteractiveGoalReviewSubmissionV1):
            from .adapters.interactive_goal import InteractiveGoal

            if not isinstance(owner, InteractiveGoal):
                raise GoalError("current Goal cannot be reviewed")
            await execute_review(owner, command)
        else:
            await run_goal(owner, command.goal_id, steps=1 if command.action == "step" else 24, seconds=600)

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
