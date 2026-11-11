"""Explicit old-first history task policy observations, outside default discovery."""

import asyncio
import json
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest

import loushang.coding.runtime.agent_session_runtime as coding
import loushang.harness.session.agent_product_runtime as core

ORACLE = Path(__file__).parent / "fixtures" / "resume_history_custody_v1.jsonl"


def error_value(error):
    if error is None:
        return None
    return {
        "type": type(error).__name__,
        "text": str(error),
        "cause": error_value(error.__cause__),
        "context": error_value(error.__context__),
    }


async def read_case(monkeypatch, mode):
    trace, created = [], []
    owner = SimpleNamespace(
        _resume_history_reads=set(),
        _resume_history_loop=None,
        _resume_history_closed=False,
    )
    # Bind existing Core helpers only when the concrete candidate defines them.
    for name in ("_preview_session_history_data", "_drain_session_history_reads"):
        if hasattr(core.AgentProductSessionRuntime, name):
            setattr(
                owner,
                name,
                MethodType(getattr(core.AgentProductSessionRuntime, name), owner),
            )
    if mode == "closed":
        owner._resume_history_closed = True
    if mode == "foreign_loop":
        owner._resume_history_loop = object()
    if mode == "capacity":
        owner._resume_history_reads.update((object(), object()))

    def resolve(reference):
        trace.append("resolve:" + reference)
        if mode == "resolve_fail":
            raise ValueError("resolve failed")
        return SimpleNamespace(path=Path("/history"), authority_fingerprint="current")

    owner.resolve_discovered_session_source = resolve

    class Preview:
        @property
        def source_fingerprint(self):
            trace.append("result.fingerprint")
            return "wrong" if mode == "result_stale" else "current"

    def reader(source):
        assert source.path == Path("/history")
        trace.append("reader")
        if mode == "read_error":
            raise OSError("read failure")
        if mode == "closed_during_read":
            owner._resume_history_closed = True
        return Preview()

    checks = 0

    def fingerprint(path):
        nonlocal checks
        checks += 1
        trace.append("fingerprint:" + str(checks))
        return (
            "wrong"
            if (mode == "pre_stale" and checks == 1)
            or (mode == "post_stale" and checks == 2)
            else "current"
        )

    async def settled(reader, source):
        trace.append("settled_io")
        return reader(source)

    def create(work):
        trace.append("create_task")
        if mode == "create_fail":
            created.append(work)
            raise RuntimeError("create task failure")
        task = asyncio.create_task(work)
        created.append(task)
        return task

    facade = SimpleNamespace(
        get_running_loop=asyncio.get_running_loop,
        create_task=create,
        shield=asyncio.shield,
        CancelledError=asyncio.CancelledError,
        Task=asyncio.Task,
    )
    outcome = None
    with monkeypatch.context() as patch:
        for module in (coding, core):
            patch.setattr(module, "asyncio", facade, raising=False)
            patch.setattr(module, "settled_io", settled, raising=False)
            patch.setattr(
                module, "session_file_authority_fingerprint", fingerprint, raising=False
            )
        try:
            result = await coding.AgentSessionRuntime._preview_resume_data(
                owner, "history", reader
            )
            assert isinstance(result, Preview)
            trace.append("delivered")
        except BaseException as error:
            outcome = error_value(error)
        # Flush registered completion callbacks using the real event loop.
        await asyncio.sleep(0)
    loop = owner._resume_history_loop
    return {
        "trace": trace,
        "error": outcome,
        "retained": len(owner._resume_history_reads),
        "closed": owner._resume_history_closed,
        "loop": "none"
        if loop is None
        else ("current" if loop is asyncio.get_running_loop() else "foreign"),
        "work_closed": created[0].cr_frame is None
        if mode == "create_fail" and created
        else None,
    }


async def drain_case(monkeypatch, mode):
    trace = []

    class Task:
        def __init__(self, name, outcomes, done=False):
            self.name, self.outcomes, self.finished = name, list(outcomes), done

        def done(self):
            trace.append(self.name + ".done:" + str(self.finished))
            return self.finished

        def result(self):
            raise AssertionError("drain must not fetch already-settled result")

    class Snapshot:
        def __iter__(self):
            trace.append("snapshot")
            return iter(tasks)

    async def shield(task):
        item = task.outcomes.pop(0)
        trace.append(task.name + ".shield:" + item)
        if not task.outcomes:
            task.finished = True
        if item.startswith("cancel"):
            raise asyncio.CancelledError(item)
        if item == "failure":
            raise ValueError("native failure")
        if item == "fatal":
            raise KeyboardInterrupt("native fatal")

    cases = {
        "empty": [],
        "already_done": [Task("a", [], True)],
        "success": [Task("a", ["success"])],
        "failure": [Task("a", ["failure"])],
        "cancel": [Task("a", ["cancel1", "success"])],
        "last_cancel": [Task("a", ["cancel1", "cancel2", "success"])],
        "cancel_then_failure": [Task("a", ["cancel1", "failure"])],
        "native_cancelled": [Task("a", ["cancel_native"])],
        "continue_after_failure": [Task("a", ["failure"]), Task("b", ["success"])],
        "fatal": [Task("a", ["fatal"])],
    }
    tasks = cases[mode]
    owner = SimpleNamespace(_resume_history_reads=Snapshot())
    if hasattr(core.AgentProductSessionRuntime, "_drain_session_history_reads"):
        owner._drain_session_history_reads = MethodType(
            core.AgentProductSessionRuntime._drain_session_history_reads, owner
        )
    facade = SimpleNamespace(shield=shield, CancelledError=asyncio.CancelledError)
    outcome = None
    with monkeypatch.context() as patch:
        for module in (coding, core):
            patch.setattr(module, "asyncio", facade, raising=False)
        try:
            await coding.AgentSessionRuntime._drain_resume_history_reads(owner)
        except BaseException as error:
            outcome = error_value(error)
    return {"trace": trace, "error": outcome}


ROWS = [json.loads(line) for line in ORACLE.read_text().splitlines()]


@pytest.mark.parametrize("row", ROWS, ids=lambda r: r["kind"] + ":" + r["mode"])
def test_replay(monkeypatch, row):
    operation = read_case if row["kind"] == "read" else drain_case
    assert asyncio.run(operation(monkeypatch, row["mode"])) == row["expected"]
