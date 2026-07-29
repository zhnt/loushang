from __future__ import annotations

from datetime import UTC, datetime

import pytest

from loushang.channel import (
    ChannelEndpoint,
    ChannelEnvelope,
    ChannelError,
    ChannelEventDelivery,
    ChannelOperationAccepted,
    ChannelOperationCancelled,
    ChannelOperationCancelRequest,
    ChannelOperationRequest,
    decode_rpc_jsonl_frame,
    encode_rpc_jsonl_frame,
    rpc_jsonl_frame_from_json,
    rpc_jsonl_frame_to_json,
)
from loushang.harness.events import RuntimeEventView
from loushang.work import WorkEvent, WorkOperation


def test_operation_request_jsonl_round_trips_with_request_correlation() -> None:
    request = ChannelOperationRequest(
        request_id="request-1",
        envelope=_operation_envelope(),
    )

    encoded = encode_rpc_jsonl_frame(request)

    assert "\n" not in encoded
    assert decode_rpc_jsonl_frame(f"{encoded}\n") == request
    assert rpc_jsonl_frame_to_json(request)["frame_type"] == "operation_request"


def test_operation_accepted_ack_carries_request_and_run_ids() -> None:
    accepted = ChannelOperationAccepted(
        request_id="request-1",
        operation_id="operation-1",
        run_id="run-1",
    )

    assert decode_rpc_jsonl_frame(encode_rpc_jsonl_frame(accepted)) == accepted


def test_operation_cancellation_frames_round_trip() -> None:
    request = ChannelOperationCancelRequest(
        request_id="cancel-1",
        operation_id="operation-1",
    )
    accepted = ChannelOperationCancelled(
        request_id="cancel-1",
        operation_id="operation-1",
    )

    assert decode_rpc_jsonl_frame(encode_rpc_jsonl_frame(request)) == request
    assert decode_rpc_jsonl_frame(encode_rpc_jsonl_frame(accepted)) == accepted


def test_event_delivery_preserves_work_event_and_optional_request_correlation() -> None:
    delivery = ChannelEventDelivery(
        request_id="request-1",
        envelope=ChannelEnvelope(
            envelope_id="envelope-event-1",
            kind="event",
            payload=WorkEvent(
                event_id="event-1",
                kind="ContentDelta",
                run_id="run-1",
                session_id="session-1",
                domain="research",
                operation_id="operation-1",
                sequence=1,
                created_at=datetime(2026, 7, 17, tzinfo=UTC),
                delivery_hint="coalesce",
                payload={"text": "partial result"},
            ),
        ),
    )

    decoded = decode_rpc_jsonl_frame(encode_rpc_jsonl_frame(delivery))

    assert decoded == delivery
    assert isinstance(decoded, ChannelEventDelivery)
    assert decoded.envelope.payload.delivery_hint == "coalesce"


def test_event_delivery_round_trips_projected_runtime_event() -> None:
    delivery = ChannelEventDelivery(
        request_id="request-1",
        envelope=ChannelEnvelope(
            envelope_id="envelope-runtime-event-1",
            kind="event",
            payload=RuntimeEventView(
                event_id="runtime-event-1",
                kind="agent.message_update",
                stream_id="session:session-1",
                sequence=1,
                occurred_at=datetime(2026, 7, 17, tzinfo=UTC),
                event_type="assistant_delta",
                view="assistant_stream",
                payload={"type": "assistant_delta", "delta": "partial"},
                delivery_hint="coalesce",
                session_id="session-1",
            ),
        ),
    )

    decoded = decode_rpc_jsonl_frame(encode_rpc_jsonl_frame(delivery))

    assert decoded == delivery
    assert isinstance(decoded, ChannelEventDelivery)
    assert isinstance(decoded.envelope.payload, RuntimeEventView)


def test_error_frame_round_trips_strict_json_details() -> None:
    error = ChannelError(
        request_id="request-1",
        code="operation_rejected",
        message="The operation is not supported by this host.",
        retryable=False,
        details={"operation": "PublishReport", "reasons": ["unsupported"]},
    )

    assert decode_rpc_jsonl_frame(encode_rpc_jsonl_frame(error)) == error


def test_jsonl_decode_ignores_unknown_additive_fields() -> None:
    data = rpc_jsonl_frame_to_json(
        ChannelOperationAccepted(
            request_id="request-1",
            operation_id="operation-1",
        )
    )
    data["future_field"] = {"enabled": True}

    decoded = rpc_jsonl_frame_from_json(data)

    assert decoded == ChannelOperationAccepted(
        request_id="request-1",
        operation_id="operation-1",
    )


@pytest.mark.parametrize(
    "frame",
    [
        "",
        "\n",
        '{"frame_type":"operation_accepted"}\n{"frame_type":"event"}',
    ],
)
def test_jsonl_decode_requires_exactly_one_non_empty_frame(frame: str) -> None:
    with pytest.raises(ValueError, match="frame|exactly one"):
        decode_rpc_jsonl_frame(frame)


def test_frames_reject_channel_envelopes_with_the_wrong_payload_family() -> None:
    operation_envelope = _operation_envelope()

    with pytest.raises(TypeError, match="requires an event"):
        ChannelEventDelivery(envelope=operation_envelope)

    with pytest.raises(TypeError, match="requires an operation"):
        ChannelOperationRequest(
            request_id="request-1",
            envelope=ChannelEnvelope(
                envelope_id="envelope-event-1",
                kind="event",
                payload=_event(),
            ),
        )


def _operation_envelope() -> ChannelEnvelope:
    return ChannelEnvelope(
        envelope_id="envelope-operation-1",
        kind="operation",
        payload=WorkOperation(
            operation_id="operation-1",
            kind="SubmitTask",
            session_id="session-1",
            domain="research",
            payload={"topic": "channel architecture"},
        ),
        source=ChannelEndpoint(endpoint_id="client:test", kind="test"),
    )


def _event() -> WorkEvent:
    return WorkEvent(
        event_id="event-1",
        kind="WorkRunCompleted",
        run_id="run-1",
        session_id="session-1",
        domain="research",
        operation_id="operation-1",
        sequence=2,
        created_at=datetime(2026, 7, 17, tzinfo=UTC),
        delivery_hint="final_only",
        payload={},
    )
