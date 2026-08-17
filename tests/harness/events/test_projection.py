from __future__ import annotations

from datetime import UTC, datetime

import pytest

from loushang.foundation.json import JsonValueError
from loushang.harness.events import (
    RuntimeEvent,
    RuntimeEventView,
    matches_event_select,
    normalize_event_select,
    project_runtime_event,
    select_runtime_event_views,
    snake_case_json_keys,
)
from loushang.harness.session import serialize_session_event


def _event() -> RuntimeEvent[object]:
    return RuntimeEvent(
        event_id="event-1",
        kind="agent.message_update",
        stream_id="session:session-1",
        sequence=3,
        occurred_at=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        session_id="session-1",
        run_id="run-1",
        source_event_ref="agent-event-1",
        source_record_id="record-1",
        payload=object(),
    )


def test_runtime_event_projection_retains_source_envelope_and_snapshots_json() -> None:
    source = _event()
    payload = {"type": "assistant_delta", "content": {"text": "hello"}}

    view = project_runtime_event(
        source,
        event_type="assistant_delta",
        view="assistant_stream",
        payload=payload,
        delivery_hint="coalesce",
        correlation_id="tool-1",
    )
    payload["content"] = {"text": "changed"}

    assert view.event_id == source.event_id
    assert view.kind == source.kind
    assert view.stream_id == source.stream_id
    assert view.sequence == source.sequence
    assert view.occurred_at == source.occurred_at
    assert view.session_id == "session-1"
    assert view.run_id == "run-1"
    assert view.source_event_ref == "agent-event-1"
    assert view.source_record_id == "record-1"
    assert view.correlation_id == "tool-1"
    assert view.payload == {"type": "assistant_delta", "content": {"text": "hello"}}


def test_runtime_event_projection_normalizes_payload_keys() -> None:
    view = project_runtime_event(
        _event(),
        event_type="tool_execution_end",
        view="tools",
        payload={"toolCallId": "tc1", "renderedToolResult": {"isPartial": False}},
    )

    assert view.payload == {
        "tool_call_id": "tc1",
        "rendered_tool_result": {"is_partial": False},
    }


def test_runtime_event_view_rejects_unsafe_payload_and_invalid_delivery_hint() -> None:
    with pytest.raises(JsonValueError, match="JSON-safe"):
        RuntimeEventView(
            event_id="event-1",
            kind="session.queue_update",
            stream_id="session:session-1",
            sequence=1,
            occurred_at=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
            event_type="queue_update",
            view="full",
            payload={"unsafe": object()},
        )

    with pytest.raises(ValueError, match="delivery hint"):
        RuntimeEventView(
            event_id="event-1",
            kind="session.queue_update",
            stream_id="session:session-1",
            sequence=1,
            occurred_at=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
            event_type="queue_update",
            view="full",
            payload={},
            delivery_hint="later",  # type: ignore[arg-type]
        )


def test_runtime_event_selector_is_generic_and_preserves_product_alias_ownership() -> (
    None
):
    views = (
        project_runtime_event(
            _event(),
            event_type="assistant_delta",
            view="compact",
            payload={"type": "assistant_delta"},
        ),
        project_runtime_event(
            _event(),
            event_type="tool_execution_end",
            view="compact",
            payload={"type": "tool_execution_end"},
        ),
    )

    assert normalize_event_select("assistant_*") == ("assistant_*",)
    assert matches_event_select("assistant_delta", ("assistant_*",))
    assert not matches_event_select("assistant_delta", ("assistant",))
    assert select_runtime_event_views(views, ("tool_execution_*",)) == (views[1],)


def test_runtime_event_selector_rejects_invalid_patterns() -> None:
    with pytest.raises(TypeError, match="patterns must be strings"):
        normalize_event_select(("assistant_*", 1))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-empty"):
        normalize_event_select(("",))


def test_session_event_json_contract_is_snake_case_only() -> None:
    payload = serialize_session_event(
        {
            "type": "queue_update",
            "steering": ["now"],
            "follow_up": ["later"],
        }
    )

    assert payload == {
        "type": "queue_update",
        "steering": ["now"],
        "follow_up": ["later"],
    }
    assert snake_case_json_keys(
        {"assistantMessageEvent": {"contentIndex": 0, "toolCallId": "tc1"}}
    ) == {
        "assistant_message_event": {"content_index": 0, "tool_call_id": "tc1"}
    }


def test_events_package_exposes_lazy_public_contracts() -> None:
    import loushang.harness as harness
    import loushang.harness.events as events

    assert "RuntimeEventView" in events.__all__
    assert events.RuntimeEventView is RuntimeEventView
    assert events.RuntimeEvent is RuntimeEvent
    assert harness.AgentRunSpec.__name__ == "AgentRunSpec"
