"""Real borrowed Tasks at original integration names; no live host resources."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from contextlib import suppress
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Original join observations were captured on Linux"
)

HELPERS = (
    ("loushang.hosting._child_session_host", "_await_owned"),
    ("loushang.hosting._endpoint_host", "_await_owned"),
    ("loushang.hosting._process_host", "_await_owned"),
    ("loushang.hosting._launch_preparation", "_await_owned"),
    ("loushang.harness.worker.hosting_adapter", "_await_owned"),
    ("loushang.harness.worker.session", "_await_owned"),
    ("loushang.harness.workspace.process.hosting_compat", "_await_owned"),
    ("loushang.apphost.application", "_join_owned"),
    ("loushang.harness.runtime._owned_tasks", "_await_cancellation_atomic"),
    ("loushang.harness.extensions.runner", "_join_cancellation_atomic"),
    ("loushang.harness.extensions.generation", "_join_cleanup"),
    ("loushang.apphost.continuity", "_join_report"),
    ("loushang.apphost.continuity", "_join_runtime"),
    ("loushang.coding.hosted_continuity", "_join_runtime"),
    ("loushang.appservice.continuity_runtime", "_join_owned"),
)
CASES = (
    "finished_success",
    "finished_failure",
    "finished_cancelled",
    "running_success",
    "running_failure",
    "caller_cancel_success",
    "caller_repeat_cancel_success",
    "caller_cancel_failure",
    "caller_cancel_task_cancel",
    "cleared_repeat_cancel_success",
)
FIXTURE = Path(__file__).with_name("fixtures") / "owned_join_v1.json"


def load_join(module_name, function):
    if module_name == "loushang.harness.extensions.runner":
        # Use the existing canonical facade's import order. Importing its
        # implementation first exposes an unrelated, pre-existing cycle.
        importlib.import_module("loushang.harness.extensions.agent")
    return getattr(importlib.import_module(module_name), function)


async def observe(join, case):
    release, entered = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()

    async def child():
        await release.wait()
        if case.endswith("failure"):
            raise ValueError("child failed")
        if case.endswith("cancelled") or case.endswith("task_cancel"):
            raise asyncio.CancelledError("child cancelled")
        return "child result"

    task = asyncio.create_task(child())
    if case.startswith("finished_"):
        release.set()
        with suppress(ValueError, asyncio.CancelledError):
            await task

    async def waiting():
        entered.set()
        return await join(task)

    async def cancellation_step():
        # call_soon preserves registration order. The waiting task's scheduled
        # cancellation step precedes this barrier; no sleep or elapsed timeout.
        barrier = loop.create_future()
        loop.call_soon(barrier.set_result, None)
        await barrier

    caller = asyncio.create_task(waiting())
    await entered.wait()
    if case.startswith("caller_") or case == "cleared_repeat_cancel_success":
        caller.cancel("first caller cancellation")
        await cancellation_step()
        if case == "caller_repeat_cancel_success":
            caller.cancel("second caller cancellation")
            await cancellation_step()
        if case == "cleared_repeat_cancel_success":
            caller.uncancel()
            release.set()  # Child success precedes the next caller step.
            caller.cancel("second caller cancellation")
            caller.uncancel()
    release.set()
    try:
        value = await caller
        result = {"value": value}
    except (ValueError, asyncio.CancelledError) as error:
        result = {"error": type(error).__name__, "message": str(error)}
        for name in ("__cause__", "__context__"):
            related = getattr(error, name)
            result[name] = (
                None if related is None else [type(related).__name__, str(related)]
            )
    assert task.done() and caller.done()
    return {
        **result,
        "child_cancelled": task.cancelled(),
        "caller_cancelled": caller.cancelled(),
        "caller_cancelling": caller.cancelling(),
    }


@pytest.mark.parametrize("module_name,function", HELPERS)
@pytest.mark.parametrize("case", CASES)
def test_original_integration_join_contract(module_name, function, case):
    join = load_join(module_name, function)
    expected = json.loads(FIXTURE.read_text())[f"{module_name}:{function}"][case]
    assert asyncio.run(observe(join, case)) == expected
