from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest


def _clock():
    return datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def _cancellation_history(*, cancelling=True, terminal=True):
    from loushang.harnesswork import EventLogEntry

    operation = EventLogEntry(
        entry_id="operation",
        entry_type="operation",
        operation_id="op-1",
        event_id=None,
        run_id="run-1",
        session_id="session-1",
        sequence=0,
        payload={
            "kind": "DoWork",
            "domain": "test",
            "payload": {},
            "_harnesswork": {"cancellation_observation_version": 1},
        },
        created_at=_clock(),
    )
    entries = [operation]
    kinds = ["WorkRunStarted"]
    if cancelling:
        kinds.append("WorkRunCancelling")
    if terminal:
        kinds.append("WorkRunCancelled" if cancelling else "WorkRunCompleted")
    for sequence, kind in enumerate(kinds, 1):
        entries.append(
            replace(
                operation,
                entry_id=f"entry-{sequence}",
                entry_type="event",
                event_id=f"event-{sequence}",
                sequence=sequence,
                payload={
                    "kind": kind,
                    "payload": {},
                    "_harnesswork": {
                        "cancellation": {
                            "version": 1,
                            "status": "unsupported" if cancelling else "not_requested",
                            "reason_code": "no_capability" if cancelling else "none",
                            "reported_status": None,
                        }
                    },
                },
            )
        )
    return entries


@pytest.mark.parametrize("cut", [1, 2, 3, 4])
@pytest.mark.parametrize(
    "mode,reason",
    [
        ("legacy", "legacy_unrecorded"),
        ("empty_owner", "legacy_unrecorded"),
        ("future", "unsupported_version"),
        ("supported", "incomplete_history"),
    ],
)
def test_cancellation_projection_versions_and_incomplete_evidence(cut, mode, reason):
    from loushang.harnesswork import project_work_cancellations

    entries = _cancellation_history()[:cut]
    payload = dict(entries[0].payload)
    if mode == "legacy":
        payload.pop("_harnesswork")
    elif mode == "empty_owner":
        payload["_harnesswork"] = {}
    elif mode == "future":
        payload["_harnesswork"] = {"cancellation_observation_version": 2}
        # A future operation must not decode an unfamiliar terminal shape.
        if cut == 4:
            entries[-1] = replace(
                entries[-1],
                payload={**entries[-1].payload, "_harnesswork": "future opaque data"},
            )
    entries[0] = replace(entries[0], payload=payload)
    (record,) = project_work_cancellations(iter(entries))
    if mode == "supported" and cut == 4:
        assert record.status == "unsupported"
        assert record.reason_code == "no_capability"
    else:
        assert (record.status, record.reason_code) == ("unknown", reason)
    assert record.basis == "journal" and record.reported_status is None
    assert (record.observed_sequence, record.source_event_id) == (
        entries[-1].sequence,
        entries[-1].event_id,
    )


@pytest.mark.parametrize(
    "owner",
    [
        None,
        False,
        [],
        "v1",
        {"cancellation_observation_version": True},
        {"cancellation_observation_version": 0},
        {"cancellation_observation_version": -1},
        {"cancellation_observation_version": "1"},
        {"cancellation_observation_version": 1.0},
    ],
)
def test_cancellation_projection_rejects_bad_operation_marker(owner):
    from loushang.harnesswork import (
        WorkCancellationReplayError,
        project_work_cancellations,
    )

    entries = _cancellation_history()
    entries[0] = replace(
        entries[0], payload={**entries[0].payload, "_harnesswork": owner}
    )
    with pytest.raises(WorkCancellationReplayError):
        project_work_cancellations(entries)


@pytest.mark.parametrize(
    "record",
    [
        None,
        {},
        {"version": True},
        {"version": 2},
        {"version": 1, "status": "unsupported", "reason_code": "no_capability"},
        {
            "version": 1,
            "status": "pending",
            "reason_code": "in_progress",
            "reported_status": None,
        },
        {
            "version": 1,
            "status": "unsupported",
            "reason_code": "no_capability",
            "reported_status": "settled",
        },
        {
            "version": 1,
            "status": "settled",
            "reason_code": "domain_reported",
            "reported_status": None,
        },
        {
            "version": 1,
            "status": "settled",
            "reason_code": [],
            "reported_status": "settled",
        },
        {
            "version": 1,
            "status": "unsupported",
            "reason_code": "no_capability",
            "reported_status": {},
        },
        {
            "version": 1,
            "status": "not_requested",
            "reason_code": "none",
            "reported_status": None,
        },
    ],
)
def test_cancellation_projection_rejects_bad_supported_terminal(record):
    from loushang.harnesswork import (
        WorkCancellationReplayError,
        project_work_cancellations,
    )

    entries = _cancellation_history()
    entries[-1] = replace(
        entries[-1],
        payload={**entries[-1].payload, "_harnesswork": {"cancellation": record}},
    )
    with pytest.raises(WorkCancellationReplayError):
        project_work_cancellations(entries)


def test_cancellation_projection_validates_lifecycle_first_and_keeps_run_local_positions():
    from loushang.harnesswork import WorkRunReplayError, project_work_cancellations

    first = _cancellation_history()[:1]
    second = [
        replace(entry, run_id="run-2", operation_id="op-2")
        for entry in _cancellation_history(cancelling=False)
    ]
    records = project_work_cancellations([*first, *second])
    assert [record.run_id for record in records] == ["run-1", "run-2"]
    assert (records[0].observed_sequence, records[0].source_event_id) == (0, None)
    assert records[1].status == "not_requested"
    invalid_operation = replace(
        first[0], payload={**first[0].payload, "_harnesswork": None}
    )
    with pytest.raises(WorkRunReplayError):
        project_work_cancellations([invalid_operation, *second, second[-1]])
    with pytest.raises(WorkRunReplayError, match="without an operation"):
        project_work_cancellations(second[1:])


@pytest.mark.parametrize(
    "operation_kind", ["WorkRunCompleted", "WorkRunFailed", "WorkRunCancelled"]
)
def test_operation_kind_does_not_turn_operation_only_history_into_terminal(
    operation_kind,
):
    from loushang.harnesswork import project_work_cancellations

    operation = _cancellation_history()[0]
    operation = replace(
        operation, payload={**operation.payload, "kind": operation_kind}
    )
    (record,) = project_work_cancellations([operation])
    assert (record.status, record.reason_code) == ("unknown", "incomplete_history")
    assert (record.observed_sequence, record.source_event_id) == (0, None)


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
