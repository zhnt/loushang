from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime


def _entry(
    entry_id: str,
    *,
    entry_type: str = "event",
    operation_id: str = "op-1",
    event_id: str | None = "event-1",
    run_id: str = "run-1",
    session_id: str = "session-1",
    sequence: int = 1,
    payload: Mapping[str, object] | None = None,
) -> object:
    from loushang.work import EventLogEntry

    return EventLogEntry(
        entry_id=entry_id,
        entry_type=entry_type,
        operation_id=operation_id,
        event_id=event_id,
        run_id=run_id,
        session_id=session_id,
        sequence=sequence,
        payload=payload or {"kind": "WorkRunStarted"},
        created_at=datetime(2026, 6, 1, 10, 30, tzinfo=UTC),
    )


def test_in_memory_event_log_appends_and_queries_by_run_and_session() -> None:
    from loushang.work import InMemoryEventLogBackend

    backend = InMemoryEventLogBackend()
    first = _entry("entry-1", run_id="run-1", session_id="session-1", sequence=1)
    second = _entry("entry-2", run_id="run-2", session_id="session-1", sequence=1)
    third = _entry("entry-3", run_id="run-1", session_id="session-2", sequence=2)

    first_position = backend.append(first)
    second_position = backend.append(second)
    third_position = backend.append(third)

    assert first_position.offset == 1
    assert second_position.offset == 2
    assert third_position.offset == 3
    assert backend.query(run_id="run-1") == [first, third]
    assert backend.query(session_id="session-1") == [first, second]
    assert backend.query(run_id="run-1", session_id="session-2") == [third]
    assert backend.query(run_id="run-1", after=first_position) == [third]
    assert backend.query(limit=2) == [first, second]


def test_in_memory_event_log_subscribe_replays_existing_then_streams_later_entries() -> None:
    from loushang.work import InMemoryEventLogBackend

    async def scenario() -> None:
        backend = InMemoryEventLogBackend()
        existing = _entry(
            "entry-1",
            run_id="run-1",
            sequence=1,
            payload={"items": ["existing"]},
        )
        ignored = _entry("entry-ignored", run_id="run-2", sequence=1)
        later = _entry(
            "entry-2",
            run_id="run-1",
            sequence=2,
            payload={"items": ["later"]},
        )
        backend.append(existing)

        stream = backend.subscribe(run_id="run-1")
        replayed = await asyncio.wait_for(anext(stream), timeout=0.1)
        assert replayed == existing
        replayed_items = replayed.payload["items"]
        assert isinstance(replayed_items, list)
        replayed_items.append("external mutation")
        assert backend.query()[0].payload == {"items": ["existing"]}

        next_entry = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        backend.append(ignored)
        backend.append(later)

        streamed = await asyncio.wait_for(next_entry, timeout=0.1)
        assert streamed == later
        streamed_items = streamed.payload["items"]
        assert isinstance(streamed_items, list)
        streamed_items.append("external mutation")
        assert backend.query(run_id="run-1")[1].payload == {"items": ["later"]}
        await stream.aclose()

    asyncio.run(scenario())


def test_jsonl_event_log_appends_queries_and_reopens(tmp_path) -> None:
    from loushang.work import JsonlEventLogBackend

    log_path = tmp_path / "work" / "events.jsonl"
    backend = JsonlEventLogBackend(log_path)
    first = _entry(
        "entry-1",
        run_id="run-1",
        session_id="session-1",
        sequence=1,
        payload={
            "kind": "WorkRunStarted",
            "nested": {"at": "2026-06-01T10:31:00+00:00"},
        },
    )
    second = _entry("entry-2", run_id="run-2", session_id="session-1", sequence=1)
    third = _entry("entry-3", run_id="run-1", session_id="session-2", sequence=2)

    first_position = backend.append(first)
    backend.append(second)
    backend.append(third)

    assert first_position.offset == 1
    assert log_path.read_text(encoding="utf-8").count("\n") == 3

    reopened = JsonlEventLogBackend(log_path)
    run_entries = reopened.query(run_id="run-1")
    assert [entry.entry_id for entry in run_entries] == ["entry-1", "entry-3"]
    assert run_entries[0].payload == {
        "kind": "WorkRunStarted",
        "nested": {"at": "2026-06-01T10:31:00+00:00"},
    }
    assert reopened.query(session_id="session-1") == [run_entries[0], second]
    assert [entry.entry_id for entry in reopened.query(run_id="run-1", after=first_position)] == ["entry-3"]


def test_jsonl_event_log_rejects_implicit_object_projection(tmp_path) -> None:
    from dataclasses import dataclass
    from pathlib import Path

    import pytest

    from loushang.foundation.json import JsonValueError
    from loushang.work import JsonlEventLogBackend

    @dataclass(frozen=True)
    class Details:
        path: Path

    for unsafe in (
        datetime(2026, 6, 1, 10, 31, tzinfo=UTC),
        Details(path=Path("notes.txt")),
        object(),
    ):
        log_path = tmp_path / f"{type(unsafe).__name__}.jsonl"

        with pytest.raises(JsonValueError) as exc_info:
            JsonlEventLogBackend(log_path).append(
                _entry(
                    f"entry-{type(unsafe).__name__}",
                    payload={"unsafe": unsafe},
                )
            )

        assert exc_info.value.path == "event_log_entry.payload.unsafe"
        assert not log_path.exists()


def test_jsonl_event_log_accepts_json_safe_mapping_implementations(tmp_path) -> None:
    from types import MappingProxyType

    from loushang.work import JsonlEventLogBackend

    log_path = tmp_path / "mapping.jsonl"
    backend = JsonlEventLogBackend(log_path)
    backend.append(
        _entry(
            "entry-mapping",
            payload=MappingProxyType({"kind": "WorkRunStarted"}),
        )
    )

    assert JsonlEventLogBackend(log_path).query()[0].payload == {
        "kind": "WorkRunStarted"
    }


def test_event_log_backends_share_strict_snapshot_semantics(tmp_path) -> None:
    from pathlib import Path

    import pytest

    from loushang.foundation.json import JsonValueError
    from loushang.work import InMemoryEventLogBackend, JsonlEventLogBackend

    backends = (
        InMemoryEventLogBackend(),
        JsonlEventLogBackend(tmp_path / "events.jsonl"),
    )
    for index, backend in enumerate(backends):
        items = ["first"]
        backend.append(
            _entry(
                f"entry-{index}",
                payload={"items": items},
            )
        )
        items.append("later")

        queried = backend.query()[0]
        assert queried.payload == {"items": ["first"]}
        queried_items = queried.payload["items"]
        assert isinstance(queried_items, list)
        queried_items.append("external mutation")
        assert backend.query()[0].payload == {"items": ["first"]}
        with pytest.raises(JsonValueError) as exc_info:
            backend.append(
                _entry(
                    f"unsafe-{index}",
                    payload={"unsafe": Path("notes.txt")},
                )
            )
        assert exc_info.value.path == "event_log_entry.payload.unsafe"


def test_event_log_backends_reject_non_exact_entry_field_types(tmp_path) -> None:
    import pytest

    from loushang.work import InMemoryEventLogBackend, JsonlEventLogBackend

    backends = (
        InMemoryEventLogBackend(),
        JsonlEventLogBackend(tmp_path / "events.jsonl"),
    )
    for backend in backends:
        with pytest.raises(TypeError, match="sequence must be an integer"):
            backend.append(_entry("entry-invalid", sequence=True))

        assert backend.query() == []


def test_jsonl_event_log_rejects_malformed_schema_fields(tmp_path) -> None:
    import pytest

    from loushang.harness.journal import JournalFileError
    from loushang.work import JsonlEventLogBackend

    malformed_values = (
        ("entry_id", 1),
        ("entry_type", 1),
        ("entry_type", "snapshot"),
        ("operation_id", False),
        ("event_id", 1),
        ("run_id", []),
        ("session_id", {}),
        ("sequence", True),
        ("sequence", "1"),
        ("payload", []),
        ("created_at", 1),
        ("created_at", "2026-06-01"),
        ("created_at", "not-a-datetime"),
    )
    for index, (field_name, value) in enumerate(malformed_values):
        log_path = tmp_path / f"malformed-{index}.jsonl"
        data = _wire_entry_data()
        data[field_name] = value
        log_path.write_text(json.dumps(data) + "\n", encoding="utf-8")

        with pytest.raises(JournalFileError) as exc_info:
            JsonlEventLogBackend(log_path)

        assert exc_info.value.code == "invalid_record"
        assert exc_info.value.line_number == 1


def test_jsonl_event_log_rejects_missing_and_unknown_schema_fields(tmp_path) -> None:
    import pytest

    from loushang.harness.journal import JournalFileError
    from loushang.work import JsonlEventLogBackend

    missing = _wire_entry_data()
    missing.pop("event_id")
    unexpected = _wire_entry_data()
    unexpected["schema_version"] = 1

    for name, data in (("missing", missing), ("unexpected", unexpected)):
        log_path = tmp_path / f"{name}.jsonl"
        log_path.write_text(json.dumps(data) + "\n", encoding="utf-8")

        with pytest.raises(JournalFileError) as exc_info:
            JsonlEventLogBackend(log_path)

        assert exc_info.value.code == "invalid_record"
        assert exc_info.value.line_number == 1


def test_jsonl_event_log_preserves_sorted_unicode_wire_format(tmp_path) -> None:
    from loushang.work import JsonlEventLogBackend

    log_path = tmp_path / "events.jsonl"
    JsonlEventLogBackend(log_path).append(
        _entry(
            "entry-unicode",
            payload={"z": "你好", "a": 1},
        )
    )

    line = log_path.read_text(encoding="utf-8")
    assert "你好" in line
    assert "\\u4f60" not in line
    assert line.index('"created_at"') < line.index('"entry_id"')
    assert line.index('"a"') < line.index('"z"')


def test_jsonl_event_log_subscribe_replays_existing_then_streams_later_entries(tmp_path) -> None:
    from loushang.work import JsonlEventLogBackend

    async def scenario() -> None:
        backend = JsonlEventLogBackend(tmp_path / "events.jsonl")
        existing = _entry("entry-1", run_id="run-1", sequence=1)
        ignored = _entry("entry-ignored", run_id="run-2", sequence=1)
        later = _entry("entry-2", run_id="run-1", sequence=2)
        backend.append(existing)

        stream = backend.subscribe(run_id="run-1")
        assert await asyncio.wait_for(anext(stream), timeout=0.1) == existing

        next_entry = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        backend.append(ignored)
        backend.append(later)

        assert await asyncio.wait_for(next_entry, timeout=0.1) == later
        await stream.aclose()

    asyncio.run(scenario())


def _wire_entry_data() -> dict[str, object]:
    return {
        "entry_id": "entry-1",
        "entry_type": "event",
        "operation_id": "op-1",
        "event_id": "event-1",
        "run_id": "run-1",
        "session_id": "session-1",
        "sequence": 1,
        "payload": {"kind": "WorkRunStarted"},
        "created_at": "2026-06-01T10:30:00+00:00",
    }


def test_event_log_operation_index_and_checkpoint_are_consistent(tmp_path) -> None:
    from loushang.work import InMemoryEventLogBackend, JsonlEventLogBackend

    for backend in (
        InMemoryEventLogBackend(),
        JsonlEventLogBackend(tmp_path / "indexed-events.jsonl"),
    ):
        assert backend.checkpoint().offset == 0
        first = _entry("entry-1", operation_id="op-1", run_id="run-1")
        second = _entry("entry-2", operation_id="op-2", run_id="run-2")
        backend.append(first)
        checkpoint = backend.checkpoint()
        backend.append(second)

        assert checkpoint.offset == 1
        assert backend.query(operation_id="op-1") == [first]
        assert backend.query(operation_id="op-2", after=checkpoint) == [second]
        assert backend.query(operation_id="missing") == []

    reopened = JsonlEventLogBackend(tmp_path / "indexed-events.jsonl")
    assert reopened.checkpoint().offset == 2
    assert [entry.operation_id for entry in reopened.query(operation_id="op-2")] == [
        "op-2"
    ]
