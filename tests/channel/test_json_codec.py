from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import cast

import pytest


def test_channel_envelope_json_round_trips_work_operation() -> None:
    from loushang.channel import (
        ChannelEndpoint,
        ChannelEnvelope,
        channel_envelope_from_json,
        channel_envelope_to_json,
    )
    from loushang.work import WorkOperation

    created_at = datetime(2026, 6, 10, 13, 0, tzinfo=UTC)
    envelope = ChannelEnvelope(
        envelope_id="env-1",
        kind="operation",
        payload=WorkOperation(
            operation_id="op-1",
            kind="SubmitCodingTurn",
            session_id="session-1",
            domain="coding",
            payload={"text": "inspect", "paths": ["src", "tests"]},
            source={"client": "tui"},
        ),
        source=ChannelEndpoint(
            endpoint_id="client:tui", kind="tui", session_id="session-1"
        ),
        target=ChannelEndpoint(
            endpoint_id="host:local", kind="host", metadata={"pid": 123}
        ),
        created_at=created_at,
        metadata={"trace_id": "trace-1"},
    )

    data = channel_envelope_to_json(envelope)

    assert json.loads(json.dumps(data, sort_keys=True)) == data
    assert data == {
        "envelope_id": "env-1",
        "kind": "operation",
        "payload": {
            "operation_id": "op-1",
            "kind": "SubmitCodingTurn",
            "session_id": "session-1",
            "domain": "coding",
            "payload": {"text": "inspect", "paths": ["src", "tests"]},
            "source": {"client": "tui"},
        },
        "source": {
            "endpoint_id": "client:tui",
            "kind": "tui",
            "session_id": "session-1",
            "metadata": {},
        },
        "target": {
            "endpoint_id": "host:local",
            "kind": "host",
            "session_id": None,
            "metadata": {"pid": 123},
        },
        "created_at": "2026-06-10T13:00:00+00:00",
        "metadata": {"trace_id": "trace-1"},
    }

    decoded = channel_envelope_from_json(data)

    assert decoded == ChannelEnvelope(
        envelope_id="env-1",
        kind="operation",
        payload=WorkOperation(
            operation_id="op-1",
            kind="SubmitCodingTurn",
            session_id="session-1",
            domain="coding",
            payload={"text": "inspect", "paths": ["src", "tests"]},
            source={"client": "tui"},
        ),
        source=ChannelEndpoint(
            endpoint_id="client:tui", kind="tui", session_id="session-1"
        ),
        target=ChannelEndpoint(
            endpoint_id="host:local", kind="host", metadata={"pid": 123}
        ),
        created_at=created_at,
        metadata={"trace_id": "trace-1"},
    )


def test_channel_envelope_json_round_trips_work_event() -> None:
    from loushang.channel import (
        ChannelEnvelope,
        channel_envelope_from_json,
        channel_envelope_to_json,
    )
    from loushang.work import WorkEvent

    event_created_at = datetime(2026, 6, 10, 13, 1, tzinfo=UTC)
    envelope_created_at = datetime(2026, 6, 10, 13, 2, tzinfo=UTC)
    envelope = ChannelEnvelope(
        envelope_id="env-2",
        kind="event",
        payload=WorkEvent(
            event_id="event-1",
            kind="ContentDelta",
            run_id="run-1",
            session_id="session-1",
            domain="coding",
            operation_id="op-1",
            sequence=7,
            created_at=event_created_at,
            delivery_hint="coalesce",
            payload={"text": "hello"},
            source_event_ref="agent:event:1",
        ),
        created_at=envelope_created_at,
    )

    data = channel_envelope_to_json(envelope)

    assert data["payload"] == {
        "event_id": "event-1",
        "kind": "ContentDelta",
        "run_id": "run-1",
        "session_id": "session-1",
        "domain": "coding",
        "operation_id": "op-1",
        "sequence": 7,
        "created_at": "2026-06-10T13:01:00+00:00",
        "delivery_hint": "coalesce",
        "payload": {"text": "hello"},
        "source_event_ref": "agent:event:1",
    }
    assert channel_envelope_from_json(data) == envelope


def test_channel_envelope_json_round_trips_projected_runtime_event() -> None:
    from loushang.channel import (
        ChannelEnvelope,
        channel_envelope_from_json,
        channel_envelope_to_json,
    )
    from loushang.harness.events import RuntimeEventView

    occurred_at = datetime(2026, 6, 10, 13, 1, tzinfo=UTC)
    envelope = ChannelEnvelope(
        envelope_id="env-runtime-1",
        kind="event",
        payload=RuntimeEventView(
            event_id="runtime-event-1",
            kind="agent.message_update",
            stream_id="session:session-1",
            sequence=7,
            occurred_at=occurred_at,
            event_type="assistant_delta",
            view="assistant_stream",
            payload={"type": "assistant_delta", "text": "hello"},
            delivery_hint="coalesce",
            session_id="session-1",
            run_id="run-1",
            source_event_ref="agent:event:1",
            source_record_id="record-1",
            correlation_id="call-1",
        ),
    )

    data = channel_envelope_to_json(envelope)

    assert data["payload"] == {
        "event_family": "runtime",
        "event_id": "runtime-event-1",
        "kind": "agent.message_update",
        "stream_id": "session:session-1",
        "sequence": 7,
        "occurred_at": "2026-06-10T13:01:00+00:00",
        "event_type": "assistant_delta",
        "view": "assistant_stream",
        "delivery_hint": "coalesce",
        "payload": {"type": "assistant_delta", "text": "hello"},
        "session_id": "session-1",
        "run_id": "run-1",
        "source_event_ref": "agent:event:1",
        "source_record_id": "record-1",
        "correlation_id": "call-1",
    }
    assert channel_envelope_from_json(data) == envelope


def test_channel_envelope_json_decode_rejects_unknown_kind() -> None:
    from loushang.channel import channel_envelope_from_json

    with pytest.raises(ValueError, match="kind"):
        channel_envelope_from_json(
            {
                "envelope_id": "env-1",
                "kind": "response",
                "payload": {},
                "source": None,
                "target": None,
                "created_at": None,
                "metadata": {},
            }
        )


def test_channel_envelope_json_rejects_implicit_payload_projection() -> None:
    from pathlib import Path

    from loushang.channel import ChannelEnvelope, channel_envelope_to_json
    from loushang.foundation.json import JsonValueError
    from loushang.work import WorkOperation

    envelope = ChannelEnvelope(
        envelope_id="env-unsafe",
        kind="operation",
        payload=WorkOperation(
            operation_id="op-unsafe",
            kind="SubmitCodingTurn",
            session_id=None,
            domain="coding",
            payload={"path": Path("notes.txt")},
        ),
    )

    with pytest.raises(JsonValueError) as exc_info:
        channel_envelope_to_json(envelope)

    assert exc_info.value.path == "channel_mapping.path"


def test_channel_envelope_json_encode_rejects_non_string_top_level_id() -> None:
    from pathlib import Path

    from loushang.channel import ChannelEnvelope, channel_envelope_to_json
    from loushang.work import WorkOperation

    envelope = ChannelEnvelope(
        envelope_id=cast(str, Path("env-unsafe")),
        kind="operation",
        payload=WorkOperation(
            operation_id="op-1",
            kind="SubmitCodingTurn",
            session_id=None,
            domain="coding",
            payload={},
        ),
    )

    with pytest.raises(TypeError, match="envelope_id must be a string"):
        channel_envelope_to_json(envelope)


@pytest.mark.parametrize("field_name", ["endpoint_id", "kind", "session_id"])
def test_channel_envelope_json_encode_rejects_non_string_endpoint_fields(
    field_name: str,
) -> None:
    from pathlib import Path

    from loushang.channel import (
        ChannelEndpoint,
        ChannelEnvelope,
        channel_envelope_to_json,
    )
    from loushang.work import WorkOperation

    endpoint_fields = {
        "endpoint_id": "client:tui",
        "kind": "tui",
        "session_id": "session-1",
    }
    endpoint_fields[field_name] = cast(str, Path("implicit-value"))
    envelope = ChannelEnvelope(
        envelope_id="env-1",
        kind="operation",
        payload=WorkOperation(
            operation_id="op-1",
            kind="SubmitCodingTurn",
            session_id=None,
            domain="coding",
            payload={},
        ),
        source=ChannelEndpoint(**endpoint_fields),
    )

    with pytest.raises(TypeError, match="must be a string"):
        channel_envelope_to_json(envelope)


def test_channel_envelope_json_decode_rejects_bool_event_sequence() -> None:
    from loushang.channel import channel_envelope_from_json

    data = _work_event_envelope_data()
    payload = cast(dict[str, object], data["payload"])
    payload["sequence"] = True

    with pytest.raises(TypeError, match="sequence must be an integer"):
        channel_envelope_from_json(data)


def test_channel_envelope_json_decode_rejects_invalid_delivery_hint() -> None:
    from loushang.channel import channel_envelope_from_json

    data = _work_event_envelope_data()
    payload = cast(dict[str, object], data["payload"])
    payload["delivery_hint"] = "eventually"

    with pytest.raises(ValueError, match="delivery_hint"):
        channel_envelope_from_json(data)


@pytest.mark.parametrize(
    ("created_at", "exception_type"),
    [
        (datetime(2026, 6, 10, tzinfo=UTC), TypeError),
        ("not-a-datetime", ValueError),
    ],
)
def test_channel_envelope_json_decode_rejects_invalid_datetime(
    created_at: object,
    exception_type: type[Exception],
) -> None:
    from loushang.channel import channel_envelope_from_json

    data = _work_event_envelope_data()
    payload = cast(dict[str, object], data["payload"])
    payload["created_at"] = created_at

    with pytest.raises(exception_type, match="created_at|JSON-safe"):
        channel_envelope_from_json(data)


def test_channel_envelope_json_decode_does_not_coerce_custom_string_values() -> None:
    from loushang.channel import channel_envelope_from_json
    from loushang.foundation.json import JsonValueError

    class StringLike:
        called = False

        def __str__(self) -> str:
            self.called = True
            return "env-1"

    string_like = StringLike()
    data = _work_event_envelope_data()
    data["envelope_id"] = string_like

    with pytest.raises(JsonValueError) as exc_info:
        channel_envelope_from_json(data)

    assert exc_info.value.path == "channel_envelope.envelope_id"
    assert string_like.called is False


def test_channel_envelope_json_decode_snapshots_source_payload() -> None:
    from loushang.channel import channel_envelope_from_json
    from loushang.work import WorkOperation

    operation_payload: dict[str, object] = {"paths": ["src"]}
    operation_source: dict[str, object] = {"client": {"name": "tui"}}
    data: dict[str, object] = {
        "envelope_id": "env-1",
        "kind": "operation",
        "payload": {
            "operation_id": "op-1",
            "kind": "SubmitCodingTurn",
            "session_id": "session-1",
            "domain": "coding",
            "payload": operation_payload,
            "source": operation_source,
        },
        "source": None,
        "target": None,
        "created_at": None,
        "metadata": {},
    }

    decoded = channel_envelope_from_json(data)
    cast(list[object], operation_payload["paths"]).append("tests")
    cast(dict[str, object], operation_source["client"])["name"] = "rpc"

    assert isinstance(decoded.payload, WorkOperation)
    assert decoded.payload.payload == {"paths": ["src"]}
    assert decoded.payload.source == {"client": {"name": "tui"}}


def _work_event_envelope_data() -> dict[str, object]:
    return {
        "envelope_id": "env-2",
        "kind": "event",
        "payload": {
            "event_id": "event-1",
            "kind": "ContentDelta",
            "run_id": "run-1",
            "session_id": "session-1",
            "domain": "coding",
            "operation_id": "op-1",
            "sequence": 7,
            "created_at": "2026-06-10T13:01:00+00:00",
            "delivery_hint": "coalesce",
            "payload": {"text": "hello"},
            "source_event_ref": "agent:event:1",
        },
        "source": None,
        "target": None,
        "created_at": "2026-06-10T13:02:00+00:00",
        "metadata": {},
    }
