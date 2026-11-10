"""Manual replay of original retained Method Tasks; no automatic PR test route.

Uses real asyncio Tasks and Outcome values with controlled Work/Session ports.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import inspect
import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

from loushang.appserver.protocol import AckV1
from loushang.appservice.execution_guard import ExecutionControlV1
from loushang.coding import _hosted_method_work as code
from loushang.harnesswork.integrations import session as core
from loushang.harnesswork.recording import WorkRecording, WorkRecordingUnavailable
from loushang.harnesswork.types import WorkRun

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "method_plan_custody_v1.json.gz"
CASES = [
    ("success", "success", {}),
    ("failed-run", "failed", {}),
    ("unconfirmed-completed", "mismatch", {}),
    ("completed-looking-active", "active", {}),
    ("cwd-error", "success", {"cwd:1": "value"}),
    ("prepare-value", "success", {"prepare:1": "value"}),
    ("prepare-type", "success", {"prepare:1": "type"}),
    ("prepare-cancel", "success", {"prepare:1": "cancel"}),
    ("factory-reject", "success", {"task_create:1": "value"}),
    ("submit-error", "success", {"submit:1": "value"}),
    ("record-unavailable-latch", "success", {"record:1": "unavailable"}),
    ("record-generic-error", "success", {"record:1": "value"}),
    ("lookup-cleanup-error", "success", {"lookup:1": "value"}),
    ("active-view-error", "success", {"active:1": "value"}),
    ("cancel-error-confirmed", "active", {"cancel:1": "value"}),
    (
        "cancel-error-unconfirmed",
        "active",
        {"record:1": "unavailable", "cancel:1": "value"},
    ),
    ("wait-business-error", "failed", {"wait:1": "value"}),
    ("wait-cancel", "failed", {"wait:1": "cancel"}),
    ("step-retry", "step", {"step:1": "value"}),
    ("session-retry", "step", {"session_settle:1": "value"}),
    (
        "step-then-session-retry",
        "step",
        {"step:1": "value", "session_settle:1": "value"},
    ),
    ("outcome-constructor-error", "success", {"outcome:1": "value"}),
    ("outcome-constructor-unavailable", "success", {"outcome:1": "unavailable"}),
    (
        "preparation-outcome-error",
        "success",
        {"prepare:1": "value", "outcome:1": "value"},
    ),
    ("pre-cancel", "pre-cancel", {}),
    ("submission-checkpoint-cancel", "submit-checkpoint-cancel", {}),
    ("before-turn-checkpoint-cancel", "before-turn-cancel", {}),
    ("child-task-cancel-before-entry", "child-cancel", {}),
    ("outer-task-cancel-retains-child", "outer-cancel", {}),
    ("settle-waiter-cancel-retains-child", "settle-cancel", {}),
]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def observe(case):
    name, mode, requested = case
    trace, counts, fired = [], {}, []
    types = {
        "value": ValueError,
        "type": TypeError,
        "cancel": asyncio.CancelledError,
        "unavailable": WorkRecordingUnavailable,
    }
    errors = {key: types[kind](key) for key, kind in requested.items()}

    def event(key, *values):
        trace.append([key, *values])
        counts[key] = counts.get(key, 0) + 1
        occurrence = f"{key}:{counts[key]}"
        if occurrence in errors:
            fired.append(occurrence)
            raise errors[occurrence]

    def error_data(error, seen=None):
        if error is None:
            return None
        seen = set() if seen is None else seen
        if id(error) in seen:
            return {"cycle": True}
        seen.add(id(error))
        return {
            "type": f"{type(error).__module__}.{type(error).__qualname__}",
            "args": list(error.args),
            "identity": next(
                (key for key, value in errors.items() if value is error), None
            ),
            "suppress": error.__suppress_context__,
            "notes": list(getattr(error, "__notes__", [])),
            "cause": error_data(error.__cause__, seen),
            "context": error_data(error.__context__, seen),
        }

    def result_data(value):
        if value is None:
            return None
        legacy = value.legacy_result
        assert type(legacy) is AckV1
        return {
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "status": value.status.value,
            "error_code": value.error_code,
            "legacy_result": {
                "type": f"{type(legacy).__module__}.{type(legacy).__qualname__}",
                "fields": {f.name: getattr(legacy, f.name) for f in fields(legacy)},
            },
        }

    async def scenario():
        entered, release, cleanup_release, child_cancelled = (
            asyncio.Event() for _ in range(4)
        )
        control = ExecutionControlV1()
        turns = (
            core.SessionWorkTurn("prepared input", plan_id="plan-1", step_id="step-1"),
        )
        run = WorkRun(
            "run-1",
            "execution-1",
            "session-1",
            "coding",
            "failed" if mode in {"failed", "step"} else "completed",
            method_id="method-1",
            plan_id="plan-1",
        )
        present = False
        active = mode == "active"
        created_tasks, created_coroutines = [], []
        loop = asyncio.get_running_loop()
        original_factory = loop.get_task_factory()
        original_init = code.ExecutionOutcomeV1.__init__

        class Session:
            session_id = "session-1"

            def __init__(self):
                self.session_manager = self

            def get_cwd(self):
                event("cwd")
                return "/workspace"

            async def settle_execution(self, *, interrupted):
                event("session_settle", interrupted)

        class Method:
            def prepare(self, text, cwd):
                event("prepare", text, str(cwd))
                return turns

        class Step:
            async def settle(self):
                event("step", invocation.step is step)

        class Native:
            def get_recording(self, run_id):
                event("record", run_id)
                observed = replace(run, status="running") if mode == "mismatch" else run
                return WorkRecording(observed, None, "acknowledged", 1, "event-1")

            def get_run_for_operation(self, operation_id):
                event("lookup", operation_id)
                return run if present else None

            def active_runs(self):
                event("active")
                return (run,) if active else ()

            async def cancel(self, run_id):
                nonlocal active
                event("cancel", run_id)
                active = False
                return run

            async def wait(self, run_id):
                nonlocal active
                event("wait", run_id)
                active = False
                return run

        class Runtime:
            def __init__(self):
                self.work_runtime = Native()

            async def submit_plan(
                self, submitted_turns, *, session_id, operation_id, before_turn
            ):
                nonlocal present, run
                event(
                    "submit",
                    submitted_turns is turns,
                    session_id,
                    operation_id,
                    before_turn.__self__ is invocation,
                )
                present = True
                before_turn(turns[0], 0, 1)
                if mode == "step":
                    invocation.step = step
                entered.set()
                if mode in {"outer-cancel", "settle-cancel"}:
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        event("child_cancelled")
                        child_cancelled.set()
                        await cleanup_release.wait()
                        run = replace(run, status="cancelled")
                        raise
                return run

        def cancellation_requested():
            event("checkpoint")
            return (
                mode == "pre-cancel"
                or mode == "submit-checkpoint-cancel"
                and counts["checkpoint"] == 2
                or mode == "before-turn-cancel"
                and counts["checkpoint"] == 3
            )

        session, runtime, step = Session(), Runtime(), Step()
        invocation = code.MethodInvocation(
            session,
            runtime,
            Method(),
            "execution-1",
            "original input",
            cancellation_requested,
        )

        def factory(selected_loop, coroutine, context=None):
            frame = getattr(coroutine, "cr_frame", None)
            submission = (
                frame is not None
                and frame.f_locals.get("self") is invocation
                and "turns" in frame.f_locals
            )
            if submission:
                created_coroutines.append(coroutine)
                event("task_create", frame.f_locals["turns"] is turns)
            task = (
                asyncio.Task(coroutine, loop=selected_loop, context=context)
                if original_factory is None
                else original_factory(selected_loop, coroutine)
                if context is None
                else original_factory(selected_loop, coroutine, context=context)
            )
            if submission:
                created_tasks.append(task)
                if mode == "child-cancel":
                    task.cancel("child-before-entry")
            return task

        def outcome_init(self, *args, **kwargs):
            event(
                "outcome",
                [value.value if hasattr(value, "value") else value for value in args],
                kwargs,
            )
            original_init(self, *args, **kwargs)

        def state():
            task = invocation.task
            return {
                "cancelled": invocation.cancelled,
                "not_submitted": invocation.not_submitted,
                "submit_started": invocation.submit_started,
                "recording_unavailable": invocation.recording_unavailable,
                "step_retained": invocation.step is step,
                "control_retained": invocation.control is control,
                "present": present,
                "active": active,
                "task": None
                if task is None
                else {
                    "same_created": bool(created_tasks) and task is created_tasks[0],
                    "done": task.done(),
                    "cancelled": task.cancelled(),
                    "cancelling": task.cancelling(),
                },
                "created_coroutine_states": [
                    inspect.getcoroutinestate(value) for value in created_coroutines
                ],
            }

        async def capture(awaitable):
            value, error = None, None
            try:
                value = await awaitable
            except BaseException as caught:
                error = caught
            return {
                "result": result_data(value) if value is not None else None,
                "error": error_data(error),
                "state": state(),
            }

        loop.set_task_factory(factory)
        code.ExecutionOutcomeV1.__init__ = outcome_init
        try:
            runner = asyncio.create_task(invocation.run(control))
            if mode in {"outer-cancel", "settle-cancel"}:
                await asyncio.wait_for(entered.wait(), 2)
                runner.cancel("outer-request")
                running = await capture(runner)
                await asyncio.wait_for(child_cancelled.wait(), 2)
                running["state"] = state()
            else:
                running = await capture(runner)
            settlements = []
            if mode == "settle-cancel":
                settling = asyncio.Event()

                async def first_settle():
                    settling.set()
                    await invocation.settle()

                waiter = asyncio.create_task(first_settle())
                await settling.wait()
                waiter.cancel("settle-request")
                settlements.append(await capture(waiter))
            cleanup_release.set()
            if mode in {"outer-cancel", "settle-cancel"}:
                assert invocation.task is not None
                await asyncio.gather(invocation.task, return_exceptions=True)
            for _ in range(3):
                settlements.append(await capture(invocation.settle()))
            assert sorted(fired) == sorted(requested), (name, fired, requested, trace)
            if requested:
                assert (
                    running["error"] is not None
                    or any(value["error"] is not None for value in settlements)
                    or running["result"]["status"] == "failed"
                ), (name, running, settlements, trace)
            if name == "success":
                assert (
                    running["error"] is None
                    and running["result"]["status"] == "succeeded"
                )
            if name == "factory-reject":
                assert (
                    created_coroutines
                    and inspect.getcoroutinestate(created_coroutines[0])
                    == "CORO_CLOSED"
                    and invocation.task is None
                )
            if mode in {"outer-cancel", "settle-cancel"}:
                assert (
                    running["state"]["task"]["done"] is False
                    and running["state"]["control_retained"]
                )
            if mode == "settle-cancel":
                assert (
                    settlements[0]["error"]["type"]
                    == "asyncio.exceptions.CancelledError"
                    and settlements[0]["state"]["task"]["done"] is False
                )
            assert counts.get("submit", 0) <= 1, (name, trace)
            return {
                "name": name,
                "trace": trace,
                "run": running,
                "settlements": settlements,
                "fired": fired,
            }
        finally:
            code.ExecutionOutcomeV1.__init__ = original_init
            loop.set_task_factory(original_factory)
            cleanup_release.set()
            for task in created_tasks:
                if not task.done():
                    task.cancel()
            if created_tasks:
                await asyncio.gather(*created_tasks, return_exceptions=True)

    return asyncio.run(scenario())


@pytest.mark.parametrize("case", CASES, ids=[value[0] for value in CASES])
def test_original_ordering(case):
    assert canonical(observe(case)) == canonical(
        json.loads(gzip.decompress(FIXTURE.read_bytes()))[case[0]]
    )


def test_fixture_origin():
    """Frozen original behavior, never recaptured from the shared implementation."""
    assert hashlib.sha256(gzip.decompress(FIXTURE.read_bytes())).hexdigest() == (
        "78f0758bc141188088815dee021f5b3fba4f62cc04c74f9557b14851c4dc2b01"
    )
