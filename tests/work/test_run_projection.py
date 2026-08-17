from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest


def _clock():
    return datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def test_project_work_runs_rebuilds_historical_run_after_runtime_restart() -> None:
    from loushang.work import (
        InMemoryEventLogBackend,
        WorkOperation,
        WorkRuntime,
        project_work_runs,
    )

    class Executor:
        async def execute(self, operation, context):
            del operation, context

    async def scenario() -> None:
        event_log = InMemoryEventLogBackend()
        runtime = WorkRuntime(executor=Executor(), event_log=event_log, clock=_clock)
        accepted = await runtime.accept(
            WorkOperation("op-1", "DoWork", "session-1", "test", {})
        )
        completed = await runtime.wait(accepted.run_id)

        restarted = WorkRuntime(executor=Executor(), event_log=event_log, clock=_clock)
        assert restarted.get_run(completed.run_id) == completed
        assert restarted.get_run_for_operation("op-1") == completed
        assert project_work_runs(event_log.query()) == (completed,)

    asyncio.run(scenario())


def test_jsonl_event_log_replays_work_run_in_a_fresh_runtime(tmp_path) -> None:
    from loushang.work import JsonlEventLogBackend, WorkOperation, WorkRuntime

    class Executor:
        async def execute(self, operation, context):
            del operation, context

    async def scenario() -> None:
        path = tmp_path / "work-events.jsonl"
        runtime = WorkRuntime(
            executor=Executor(),
            event_log=JsonlEventLogBackend(path),
            clock=_clock,
        )
        accepted = await runtime.accept(
            WorkOperation("op-jsonl", "DoWork", "session-1", "test", {})
        )
        completed = await runtime.wait(accepted.run_id)

        restarted = WorkRuntime(
            executor=Executor(),
            event_log=JsonlEventLogBackend(path),
            clock=_clock,
        )
        assert restarted.query_runs() == (completed,)
        assert restarted.get_run(completed.run_id).status == "completed"

    asyncio.run(scenario())


def test_project_work_runs_rejects_non_increasing_and_post_terminal_events() -> None:
    from loushang.work import (
        EventLogEntry,
        WorkRunReplayError,
        project_work_runs,
    )

    operation = EventLogEntry(
        entry_id="operation",
        entry_type="operation",
        operation_id="op-1",
        event_id=None,
        run_id="run-1",
        session_id="session-1",
        sequence=0,
        payload={"kind": "DoWork", "domain": "test", "payload": {}},
        created_at=_clock(),
    )
    started = replace(
        operation,
        entry_id="started",
        entry_type="event",
        event_id="event-1",
        sequence=1,
        payload={"kind": "WorkRunStarted", "payload": {}},
    )
    terminal = replace(
        started,
        entry_id="terminal",
        event_id="event-2",
        sequence=2,
        payload={"kind": "WorkRunCompleted", "payload": {}},
    )

    with pytest.raises(WorkRunReplayError, match="strictly increasing"):
        project_work_runs((operation, started, replace(started, entry_id="again")))
    with pytest.raises(WorkRunReplayError, match="after terminal"):
        project_work_runs(
            (
                operation,
                started,
                terminal,
                replace(started, entry_id="late", event_id="event-3", sequence=3),
            )
        )


def test_restarted_runtime_marks_incomplete_historical_run_as_orphaned() -> None:
    from loushang.work import EventLogEntry, InMemoryEventLogBackend, WorkRuntime

    class Executor:
        async def execute(self, operation, context):
            del operation, context

    event_log = InMemoryEventLogBackend()
    event_log.append(
        EventLogEntry(
            entry_id="operation",
            entry_type="operation",
            operation_id="op-orphan",
            event_id=None,
            run_id="run-orphan",
            session_id="session-1",
            sequence=0,
            payload={"kind": "DoWork", "domain": "test", "payload": {}},
            created_at=_clock(),
        )
    )
    event_log.append(
        EventLogEntry(
            entry_id="started",
            entry_type="event",
            operation_id="op-orphan",
            event_id="event-1",
            run_id="run-orphan",
            session_id="session-1",
            sequence=1,
            payload={"kind": "WorkRunStarted", "payload": {}},
            created_at=_clock(),
        )
    )

    restarted = WorkRuntime(executor=Executor(), event_log=event_log, clock=_clock)

    assert restarted.replay_checkpoint.offset == 2
    assert restarted.get_run("run-orphan").status == "orphaned"
    assert restarted.get_run_for_operation("op-orphan").status == "orphaned"
    assert restarted.query_runs()[0].status == "orphaned"
