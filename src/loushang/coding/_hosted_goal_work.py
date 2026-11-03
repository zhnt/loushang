"""One guarded Goal invocation; original Goal/Work remain execution authorities."""
from __future__ import annotations

import asyncio
import time

from loushang.appservice.execution_contract import ExecutionOutcomeV1, ExecutionStatusV1
from loushang.harness.runtime.execution_deadline import ExecutionDeadline


class GoalInvocation(ExecutionDeadline):
    def __init__(self, owner, session, setup, execution_id, cancel_requested):
        super().__init__(clock=lambda: time.monotonic(), cancel_requested=cancel_requested,
                         total_reason="goal_deadline_exceeded",
                         phase_reason="goal_model_stage_deadline_exceeded",
                         phase_active=setup.repository is not None)
        self.owner, self.session, self.setup = owner, session, setup
        self.execution_id, self.cancel_requested = execution_id, cancel_requested
        self.task: asyncio.Task | None = None
        self.initialized = False
        self.initializing = False
        self.initialization_failed = False
        self.advances = 0
        self.pause_attempted = False

    def _bind_budget(self):
        setup = self.setup
        if setup.repository is not None:
            config = setup.config
            setup.allowance.bind_hosted_budget(
                dict(version=1, profile=setup.profile_id, deadline_seconds=config.deadline_seconds,
                     closeout_reserve_seconds=config.closeout_reserve_seconds,
                     max_model_calls=config.max_model_calls, max_output_tokens=config.max_output_tokens,
                     max_advances=config.max_advances, provider_attempts=1),
                self.budget_snapshot, self.checkpoint,
            )

    @property
    def model_deadline(self):
        return self.phase_deadline

    @model_deadline.setter
    def model_deadline(self, value):
        self.phase_deadline = value

    @property
    def model_stage(self):
        return self.phase_active

    @model_stage.setter
    def model_stage(self, value):
        self.phase_active = value

    def budget_snapshot(self):
        now = time.monotonic()
        return dict(advances_including_current_command=self.advances,
                    model_seconds_remaining=max(0, int(self.model_deadline - now)),
                    business_seconds_remaining=max(0, int(self.deadline - now)))

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
            if self.setup.repository is not None:
                task = self.setup.repository.task
                task.read_files(task.allowed, task.config["workspace_start"])
                self.checkpoint()
            await self.owner._initialize_borrowed(self.session, self.setup.allowance, self.setup.policy)
            self.checkpoint()
            self.owner.create(self.setup.goal_id, command_id=f"{self.execution_id}:create")
            self.initialized = True
        finally:
            self.initializing = False
            self.initialization_failed = not self.initialized
        if self.setup.repository is not None:
            from ._hosted_repository_work import drive_repository
            return await drive_repository(self)
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
        self.start_deadlines(self.setup.config.deadline_seconds,
                             getattr(self.setup.config, "closeout_reserve_seconds", 0))
        try:
            self._bind_budget()
            # Deadline bounds business, never the retained settlement task.
            end = self.model_deadline if self.model_stage else self.deadline
            async with asyncio.timeout(max(0, end - time.monotonic())) as timer:
                self._timer = timer
                self.task = asyncio.create_task(self._drive(), name="hosted-goal-drive")
                return await asyncio.shield(self.task)
        except TimeoutError:
            self.cancelled = True
            self._stop_reason = self._stop_reason or self._deadline_reason() or "goal_deadline_exceeded"
            self.reason = self._stop_reason
            self.task.cancel()
            return ExecutionOutcomeV1(ExecutionStatusV1.FAILED, self.reason)
        except asyncio.CancelledError:
            self.cancelled = True
            self.reason = self._stop_reason or "goal_interrupted"
            self.task.cancel()
            raise
        except Exception:
            self.reason = self._stop_reason or "goal_unavailable"
            return ExecutionOutcomeV1(ExecutionStatusV1.FAILED, self.reason)
        finally:
            self._timer = None

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
                state = core.query(self.setup.goal_id)
                if state.status == "active":
                    try:
                        core.control(self.setup.goal_id, "pause", command_id=f"{self.execution_id}:stop",
                                     revision=state.revision, epoch=state.epoch, reason=self.reason)
                    except Exception:
                        # Preserve original fenced/unknown state. Do not invent
                        # paused or turn a record write into physical cleanup debt.
                        self.reason = "goal_recording_unavailable"
