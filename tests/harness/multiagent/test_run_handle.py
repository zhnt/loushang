from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from loushang.harness.multiagent import (
    AgentInputMessage,
    AgentPath,
    AgentRecord,
    AgentTypeRegistry,
    AgentTypeSpec,
    HostCaller,
    MultiAgentControl,
    SubagentDisposeResult,
    SubagentRoundResult,
    SubagentRunHandle,
    WorkspaceLeaseSnapshot,
)
from loushang.harness.multiagent.run_handle import RoundMode

NOW = datetime(2026, 7, 26, tzinfo=UTC)
HOST = HostCaller()


class _Driver:
    def __init__(self) -> None:
        self.messages: list[AgentInputMessage] = []
        self.calls: list[tuple[int, RoundMode]] = []
        self.pending: list[asyncio.Future[SubagentRoundResult]] = []
        self.abort_calls = 0
        self.abort_error: Exception | None = None
        self.dispose_calls = 0
        self.dispose_error: Exception | None = None
        self.dispose_result = SubagentDisposeResult()

    def deliver(self, message: AgentInputMessage) -> None:
        self.messages.append(message)

    async def run_round(
        self,
        *,
        round_id: int,
        mode: RoundMode,
    ) -> SubagentRoundResult:
        self.calls.append((round_id, mode))
        future = asyncio.get_running_loop().create_future()
        self.pending.append(future)
        return await future

    def abort(self) -> None:
        self.abort_calls += 1
        if self.abort_error is not None:
            raise self.abort_error

    async def dispose(self) -> SubagentDisposeResult:
        self.dispose_calls += 1
        if self.dispose_error is not None:
            raise self.dispose_error
        return self.dispose_result

    def complete(
        self,
        result: SubagentRoundResult,
        *,
        index: int = -1,
    ) -> None:
        self.pending[index].set_result(result)

    def fail(self, error: Exception, *, index: int = -1) -> None:
        self.pending[index].set_exception(error)


def _control() -> MultiAgentControl:
    return MultiAgentControl(
        agent_types=AgentTypeRegistry(
            (AgentTypeSpec(name="reviewer", maximum_children=3),)
        ),
        clock=lambda: NOW,
    )


def _record(control: MultiAgentControl, name: str = "reviewer") -> AgentRecord:
    return control.spawn(
        caller=HOST,
        parent_path=AgentPath.root(),
        name=name,
        agent_type="reviewer",
    )


def _message(
    control: MultiAgentControl, path: AgentPath, text: str
) -> AgentInputMessage:
    return control.route_message(caller=HOST, target=path, text=text).message


async def _yield_until(predicate: Callable[[], bool]) -> None:
    for _ in range(20):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition was not reached")


def test_first_and_follow_up_rounds_share_one_owned_path() -> None:
    async def scenario() -> None:
        control = _control()
        record = _record(control)
        driver = _Driver()
        handle = SubagentRunHandle(ref=record.ref, control=control, driver=driver)

        first = await handle.deliver(_message(control, record.path, "Review this."))
        await _yield_until(lambda: len(driver.calls) == 1)
        driver.complete(
            SubagentRoundResult(
                status="completed",
                final_message="First review.",
                summary="Round one",
                latest_input_tokens=100,
                output_tokens=10,
            )
        )
        first_terminal = await handle.await_terminal()

        second = await handle.deliver(
            _message(control, record.path, "Check the follow-up.")
        )
        await _yield_until(lambda: len(driver.calls) == 2)
        driver.complete(
            SubagentRoundResult(
                status="completed",
                final_message="Follow-up review.",
                latest_input_tokens=125,
                output_tokens=5,
            )
        )
        second_terminal = await handle.await_terminal()

        assert first.triggered_new_round is True
        assert second.triggered_new_round is True
        assert driver.calls == [(1, "prompt"), (2, "continue")]
        assert first_terminal.status == "completed"
        assert second_terminal.status == "completed"
        assert second_terminal.progress.usage.latest_input_tokens == 125
        assert second_terminal.progress.usage.cumulative_output_tokens == 15
        assert [notice.round_id for notice in control.notices()] == [1, 2]

    asyncio.run(scenario())


def test_delivery_during_a_round_is_queued_without_starting_an_untracked_task() -> None:
    async def scenario() -> None:
        control = _control()
        record = _record(control)
        driver = _Driver()
        handle = SubagentRunHandle(ref=record.ref, control=control, driver=driver)

        await handle.deliver(_message(control, record.path, "Start."))
        await _yield_until(lambda: len(driver.calls) == 1)
        queued = await handle.deliver(
            _message(control, record.path, "Queued follow-up.")
        )

        assert queued.triggered_new_round is False
        assert queued.round_id == 1
        assert len(driver.calls) == 1
        assert len(driver.messages) == 2

        driver.complete(SubagentRoundResult(status="completed", final_message="Done."))
        await handle.await_terminal()

    asyncio.run(scenario())


def test_interrupt_aborts_and_awaits_the_owned_task() -> None:
    async def scenario() -> None:
        control = _control()
        record = _record(control)
        driver = _Driver()
        handle = SubagentRunHandle(ref=record.ref, control=control, driver=driver)

        await handle.deliver(_message(control, record.path, "Start."))
        await _yield_until(lambda: len(driver.calls) == 1)
        interrupt = asyncio.create_task(handle.interrupt())
        await asyncio.sleep(0)

        assert driver.abort_calls == 1
        assert interrupt.done() is False
        driver.complete(
            SubagentRoundResult(
                status="completed",
                final_message="Driver returned after abort.",
            )
        )
        interrupted = await interrupt

        assert interrupted.status == "interrupted"
        assert control.notices()[0].terminal.status == "interrupted"
        assert handle.is_running is False

    asyncio.run(scenario())


def test_close_waits_for_terminal_then_disposes_before_committing_closed() -> None:
    async def scenario() -> None:
        control = _control()
        record = _record(control)
        driver = _Driver()
        handle = SubagentRunHandle(ref=record.ref, control=control, driver=driver)

        await handle.deliver(_message(control, record.path, "Start."))
        await _yield_until(lambda: len(driver.calls) == 1)
        close = asyncio.create_task(handle.close())
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert close.done() is False
        assert driver.abort_calls == 1
        assert driver.dispose_calls == 0
        assert control.registry.get(record.ref).status == "running"

        driver.complete(
            SubagentRoundResult(status="completed", final_message="Late result.")
        )
        closed = await close
        again = await handle.close()

        assert driver.dispose_calls == 1
        assert closed.record.status == "closed"
        assert again == closed
        assert [fact.kind for fact in control.facts()][-2:] == [
            "terminal",
            "closed",
        ]
        assert len(control.notices()) == 1

    asyncio.run(scenario())


def test_close_projects_the_released_workspace_before_closing_the_record() -> None:
    async def scenario() -> None:
        control = _control()
        record = _record(control)
        driver = _Driver()
        driver.dispose_result = SubagentDisposeResult(
            released_workspace=WorkspaceLeaseSnapshot(
                workspace_ref="coding-worktree:worker",
                artifact_refs=("git-artifact:worker",),
                change_set_ref="git-branch:worker",
                changed=True,
                retained=True,
            )
        )
        handle = SubagentRunHandle(ref=record.ref, control=control, driver=driver)

        closed = await handle.close()

        assert closed.record.workspace_ref == "coding-worktree:worker"
        assert closed.record.artifact_refs == ("git-artifact:worker",)
        assert closed.record.change_set_ref == "git-branch:worker"
        assert [fact.kind for fact in control.facts()][-2:] == [
            "workspace",
            "closed",
        ]

    asyncio.run(scenario())


def test_close_survives_cancellation_of_one_waiting_caller() -> None:
    async def scenario() -> None:
        control = _control()
        record = _record(control)
        driver = _Driver()
        handle = SubagentRunHandle(ref=record.ref, control=control, driver=driver)

        await handle.deliver(_message(control, record.path, "Start."))
        await _yield_until(lambda: len(driver.calls) == 1)
        caller = asyncio.create_task(handle.close())
        await asyncio.sleep(0)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller

        driver.complete(
            SubagentRoundResult(status="completed", final_message="Stopped.")
        )
        closed = await handle.close()

        assert closed.record.status == "closed"
        assert driver.dispose_calls == 1

    asyncio.run(scenario())


def test_dispose_failure_is_reported_but_does_not_leave_the_path_open() -> None:
    async def scenario() -> None:
        control = _control()
        record = _record(control)
        driver = _Driver()
        driver.dispose_error = RuntimeError("dispose failed")
        handle = SubagentRunHandle(ref=record.ref, control=control, driver=driver)

        closed = await handle.close()

        assert closed.record.status == "closed"
        assert isinstance(closed.dispose_error, RuntimeError)
        assert str(closed.dispose_error) == "dispose failed"

    asyncio.run(scenario())


def test_abort_failure_still_waits_for_the_round_before_dispose() -> None:
    async def scenario() -> None:
        control = _control()
        record = _record(control)
        driver = _Driver()
        driver.abort_error = RuntimeError("abort failed")
        handle = SubagentRunHandle(ref=record.ref, control=control, driver=driver)

        await handle.deliver(_message(control, record.path, "Start."))
        await _yield_until(lambda: len(driver.calls) == 1)
        close = asyncio.create_task(handle.close())
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert close.done() is False
        assert driver.dispose_calls == 0
        driver.complete(SubagentRoundResult(status="completed", final_message="Done."))
        result = await close

        assert driver.dispose_calls == 1
        assert str(result.dispose_error) == "abort failed"
        assert result.record.status == "closed"

    asyncio.run(scenario())


def test_driver_failure_becomes_a_terminal_failure_notice() -> None:
    async def scenario() -> None:
        control = _control()
        record = _record(control)
        driver = _Driver()
        handle = SubagentRunHandle(ref=record.ref, control=control, driver=driver)

        await handle.deliver(_message(control, record.path, "Start."))
        await _yield_until(lambda: len(driver.calls) == 1)
        driver.fail(RuntimeError("model failed"))
        terminal = await handle.await_terminal()

        assert terminal.status == "failed"
        assert control.notices()[0].terminal.final_message == "model failed"

    asyncio.run(scenario())


def test_terminal_timeout_does_not_cancel_the_owned_round() -> None:
    async def scenario() -> None:
        control = _control()
        record = _record(control)
        driver = _Driver()
        handle = SubagentRunHandle(ref=record.ref, control=control, driver=driver)

        await handle.deliver(_message(control, record.path, "Start."))
        await _yield_until(lambda: len(driver.calls) == 1)
        with pytest.raises(TimeoutError):
            await handle.await_terminal(timeout=0)

        assert handle.is_running is True
        driver.complete(SubagentRoundResult(status="completed", final_message="Done."))
        terminal = await handle.await_terminal()
        assert terminal.status == "completed"

    asyncio.run(scenario())
