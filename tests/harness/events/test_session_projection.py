from __future__ import annotations

from loushang.harness.events.recording_policy import event_writes_transcript
from loushang.harness.session.event_projection import (
    project_session_event,
    shape_stream_event,
)
from loushang.harness.session.runtime_event_views import shape_runtime_event_view


def test_shared_projection_accepts_neutral_session_event_mapping() -> None:
    event = {
        "type": "queue_update",
        "steering": ["steer"],
        "follow_up": ["follow"],
    }

    assert project_session_event(event, event_view="full") == [event]


def test_shared_stream_shape_normalizes_external_keys_to_snake_case() -> None:
    shaped = shape_stream_event(
        {
            "type": "tool_execution_start",
            "toolCallId": "call-1",
        },
        event_view="full",
    )

    assert shaped["tool_call_id"] == "call-1"
    assert shaped["event_type"] == "tool_execution_start"
    assert shaped["correlation_id"] == "call-1"
    assert shaped["stream"] == {
        "kind": "session_event",
        "view": "full",
        "correlation_id": "call-1",
    }


def test_runtime_views_and_recording_policy_are_harness_owned() -> None:
    shaped = shape_runtime_event_view(
        type(
            "View",
            (),
            {
                "payload": {"toolCallId": "call-1"},
                "event_type": "tool_execution_end",
                "view": "tools",
                "correlation_id": "call-1",
            },
        )()
    )

    assert shaped["tool_call_id"] == "call-1"
    assert shaped["stream"]["view"] == "tools"
    assert event_writes_transcript({"type": "tool_execution_end"})
