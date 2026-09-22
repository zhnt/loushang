from __future__ import annotations

import asyncio

import pytest

from loushang.harness.workspace.exec._capture_supervision import (
    wait_for_captured_process,
)


def test_completed_reader_failure_wins_over_simultaneous_process_exit():
    asyncio.run(_completed_reader_failure_wins_over_simultaneous_process_exit())


async def _completed_reader_failure_wins_over_simultaneous_process_exit():
    async def complete():
        return None

    async def fail():
        raise ValueError("reader failed before observation")

    stdin, stdout, stderr, exited = [asyncio.create_task(operation()) for operation in
                                    (complete, fail, complete, complete)]
    await asyncio.gather(stdin, stdout, stderr, exited, return_exceptions=True)
    with pytest.raises(ValueError, match="reader failed before observation"):
        await wait_for_captured_process(
            exit_task=exited, stdin_task=stdin, readers=(stdout, stderr),
            abort_task=None, timeout=None,
        )


@pytest.mark.parametrize("failed", ["stdout", "stderr", "stdin"])
def test_io_failure_wakes_before_blocked_stdin_and_process_exit(failed):
    asyncio.run(_io_failure_wakes_before_blocked_stdin_and_process_exit(failed))


async def _io_failure_wakes_before_blocked_stdin_and_process_exit(failed):
    gates = {name: asyncio.Event() for name in ("stdout", "stderr", "stdin", "exit")}

    async def operation(name):
        await gates[name].wait()
        if name == failed:
            raise ValueError("capture contract failure")

    tasks = {name: asyncio.create_task(operation(name)) for name in gates}
    observer = asyncio.create_task(wait_for_captured_process(
        exit_task=tasks["exit"], stdin_task=tasks["stdin"],
        readers=(tasks["stdout"], tasks["stderr"]), abort_task=None, timeout=None,
    ))
    try:
        gates[failed].set()
        with pytest.raises(ValueError, match="capture contract failure"):
            await asyncio.wait_for(observer, 1)
        assert not tasks["exit"].done()
        assert all(not task.cancelled() for task in tasks.values())
    finally:
        observer.cancel()
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(observer, *tasks.values(), return_exceptions=True)


@pytest.mark.parametrize("wake", ["exit", "abort", "timeout", "cancel"])
def test_normal_eof_does_not_end_execution_or_transfer_task_ownership(wake):
    asyncio.run(_normal_eof_does_not_end_execution_or_transfer_task_ownership(wake))


async def _normal_eof_does_not_end_execution_or_transfer_task_ownership(wake):
    exit_gate, abort_gate = asyncio.Event(), asyncio.Event()

    async def complete():
        return None

    io_tasks = [asyncio.create_task(complete()) for _ in range(3)]
    exit_task = asyncio.create_task(exit_gate.wait())
    abort_task = asyncio.create_task(abort_gate.wait())
    observer = asyncio.create_task(wait_for_captured_process(
        exit_task=exit_task, stdin_task=io_tasks[0], readers=tuple(io_tasks[1:]),
        abort_task=abort_task, timeout=0 if wake == "timeout" else None,
    ))
    try:
        await asyncio.gather(*io_tasks)
        if wake != "timeout":
            assert not observer.done()
        if wake == "exit":
            exit_gate.set()
        elif wake == "abort":
            abort_gate.set()
        elif wake == "cancel":
            observer.cancel()
        if wake == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await observer
        else:
            assert await asyncio.wait_for(observer, 1) == wake
        assert not exit_task.cancelled() and not abort_task.cancelled()
    finally:
        observer.cancel()
        exit_task.cancel()
        abort_task.cancel()
        await asyncio.gather(observer, exit_task, abort_task, return_exceptions=True)
