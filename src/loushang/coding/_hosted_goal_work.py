"""One guarded Goal invocation; original Goal/Work remain execution authorities."""
from __future__ import annotations

import asyncio

from loushang.appservice.execution_contract import ExecutionOutcomeV1, ExecutionStatusV1


class GoalInvocation:
    def __init__(self, owner, session, setup, execution_id, cancel_requested):
        self.owner, self.session, self.setup = owner, session, setup
        self.execution_id, self.cancel_requested = execution_id, cancel_requested
        self.task: asyncio.Task | None = None
        self.cancelled = False
        self.initialized = False
        self.initializing = False
        self.initialization_failed = False
        self.advances = 0
        self.reason = "not_started"
        self.pause_attempted = False

    def checkpoint(self):
        if self.cancelled or self.cancel_requested():
            raise asyncio.CancelledError

    def _recording_available(self):
        try:
            for batch in self.owner.controller.history.batches:
                if batch.not_submitted:
                    continue
                run = self.owner._work.get_run_for_operation(batch.operation_id)
                if run is None:
                    return False
                record = self.owner._work.get_recording(run.run_id)
                if record.contract is None or record.run.status != run.status:
                    return False
            return True
        except Exception:
            return False

    async def _drive(self):
        self.checkpoint()
        self.initializing = True
        self.reason = "initializing"
        try:
            await self.owner._initialize_borrowed(self.session, self.setup.allowance, self.setup.policy)
            self.checkpoint()
            self.owner.create("calculator", command_id=f"{self.execution_id}:create")
            self.initialized = True
        finally:
            self.initializing = False
            self.initialization_failed = not self.initialized
        for index in range(self.setup.config.max_advances):
            self.checkpoint()
            if not self._recording_available():
                self.reason = "work_recording_unavailable"
                return ExecutionOutcomeV1(ExecutionStatusV1.FAILED, self.reason)
            state = self.owner.controller.query("calculator")
            if state.status != "active":
                break
            self.reason = "advancing"
            self.advances += 1
            await self.owner.advance("calculator", command_id=f"{self.execution_id}:{index}",
                                     revision=state.revision, epoch=state.epoch)
            self.checkpoint()
            view = await self.owner.query("calculator")
            if not self._recording_available():
                self.reason = "work_recording_unavailable"
                return ExecutionOutcomeV1(ExecutionStatusV1.FAILED, self.reason)
            if view.goal.status == "completed":
                if view.validity == "current" and not view.execution_unresolved:
                    self.reason = "goal_completed"
                    return ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED)
                self.reason = "goal_evidence_unavailable"
                return ExecutionOutcomeV1(ExecutionStatusV1.FAILED, self.reason)
            if self.owner.controller.fenced or self.setup.allowance.fenced:
                break
        self.reason = "goal_stopped" if self.advances < self.setup.config.max_advances else "advance_budget_exhausted"
        return ExecutionOutcomeV1(ExecutionStatusV1.FAILED, self.reason)

    async def run(self, control):
        self.task = asyncio.create_task(self._drive(), name="hosted-goal-drive")
        try:
            # Deadline bounds business, never the retained settlement task.
            async with asyncio.timeout(self.setup.config.deadline_seconds):
                return await asyncio.shield(self.task)
        except TimeoutError:
            self.cancelled = True
            self.reason = "goal_deadline_exceeded"
            self.task.cancel()
            return ExecutionOutcomeV1(ExecutionStatusV1.FAILED, self.reason)
        except asyncio.CancelledError:
            self.cancelled = True
            self.reason = "goal_interrupted"
            self.task.cancel()
            raise
        except Exception:
            self.reason = "goal_unavailable"
            return ExecutionOutcomeV1(ExecutionStatusV1.FAILED, self.reason)

    async def settle(self):
        if self.task is not None:
            try:
                await asyncio.shield(self.task)
            except asyncio.CancelledError:
                if not self.task.done():
                    raise
            except Exception:
                pass  # Business failure is not itself physical cleanup debt.
        failure = None
        try:
            if self.initialization_failed:
                await self.owner.close()
            elif self.initialized:
                await self.owner.controller.settle_work()
        except Exception as error:
            failure = error
        # Even when the Goal record is unavailable, settle the original Session.
        await self.session.settle_execution(interrupted=self.cancelled)
        if failure is not None:
            raise failure
        if self.initialized and not self.pause_attempted:
            self.pause_attempted = True
            core = self.owner.controller
            if not core.fenced:
                state = core.query("calculator")
                if state.status == "active":
                    try:
                        core.control("calculator", "pause", command_id=f"{self.execution_id}:stop",
                                     revision=state.revision, epoch=state.epoch, reason=self.reason)
                    except Exception:
                        # Preserve original fenced/unknown state. Do not invent
                        # paused or turn a record write into physical cleanup debt.
                        self.reason = "goal_recording_unavailable"
