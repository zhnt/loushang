from __future__ import annotations

from datetime import UTC, datetime

from loushang.harnesswork import (
    EventLogEntry,
    JsonlEventLogBackend,
    create_work_event_log,
    inspect_work_log,
)


def test_inspect_work_log_projects_shared_text_and_json_shapes(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    backend = JsonlEventLogBackend(path)
    backend.append(
        EventLogEntry(
            entry_id="entry-1",
            entry_type="event",
            operation_id="op-1",
            event_id="event-1",
            run_id="run-1",
            session_id="session-1",
            sequence=1,
            payload={"kind": "WorkRunStarted", "method_id": "review"},
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
    )

    text = inspect_work_log(path, project_root=tmp_path, output_format="text")
    payload = inspect_work_log(path, project_root=tmp_path, output_format="json")

    assert "method_id" in text
    assert '"method_id": "review"' in payload


def test_create_work_event_log_handles_optional_cli_path(tmp_path) -> None:
    assert create_work_event_log(None, tmp_path) is None

    backend = create_work_event_log("logs/work.jsonl", tmp_path)

    assert isinstance(backend, JsonlEventLogBackend)
