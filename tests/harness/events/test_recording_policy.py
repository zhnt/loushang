from __future__ import annotations

from types import SimpleNamespace

from loushang.harness.events.recording_policy import (
    event_writes_transcript,
    is_cancelled_error_message,
)


def test_writes_only_visible_transcript_events() -> None:
    assert event_writes_transcript(
        {"type": "message_start", "message": SimpleNamespace(role="user")}
    )
    assert not event_writes_transcript(
        {"type": "message_start", "message": SimpleNamespace(role="assistant")}
    )
    assert event_writes_transcript(
        {"type": "message_end", "message": SimpleNamespace(role="assistant")}
    )
    assert event_writes_transcript(
        {"type": "message_end", "message": SimpleNamespace(role="toolResult")}
    )
    assert event_writes_transcript({"type": "tool_execution_end"})
    assert event_writes_transcript({"type": "auto_retry_start"})
    assert event_writes_transcript({"type": "compaction_start"})
    assert event_writes_transcript({"type": "compaction_end"})


def test_skips_internal_state_events() -> None:
    for event_type in (
        "agent_start",
        "turn_start",
        "turn_end",
        "queue_update",
        "message_update",
    ):
        assert not event_writes_transcript({"type": event_type})


def test_writes_agent_end_only_for_visible_errors() -> None:
    assert not event_writes_transcript(
        {
            "type": "agent_end",
            "messages": [
                SimpleNamespace(
                    role="assistant",
                    stop_reason="aborted",
                    error_message="Request aborted by user",
                ),
            ],
        }
    )
    assert event_writes_transcript(
        {
            "type": "agent_end",
            "messages": [
                SimpleNamespace(
                    role="assistant",
                    stop_reason="error",
                    error_message="provider failed",
                ),
            ],
        }
    )
    assert event_writes_transcript(
        {
            "type": "agent_end",
            "messages": [
                SimpleNamespace(
                    role="assistant",
                    stop_reason="aborted",
                    error_message="provider failed",
                ),
            ],
        }
    )


def test_cancelled_error_message_detection_matches_abort_variants() -> None:
    assert is_cancelled_error_message("Request cancelled.")
    assert is_cancelled_error_message("Request aborted by user")
    assert is_cancelled_error_message("provider aborted while streaming")
    assert not is_cancelled_error_message("provider failed")
    assert not is_cancelled_error_message(None)
