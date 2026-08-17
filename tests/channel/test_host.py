from __future__ import annotations

import asyncio
import json
from io import StringIO

from loushang.channel import (
    ChannelError,
    ChannelEventDelivery,
    ChannelHost,
    ChannelOperationAccepted,
    ChannelOperationCancelled,
    ChannelOperationCancelRequest,
    ChannelOperationRequest,
    encode_rpc_jsonl_frame,
)
from loushang.channel.types import ChannelEnvelope
from loushang.harnesswork import WorkEvent, WorkOperation


class _FakePort:
    def __init__(self) -> None:
        self.accepted_requests: list[ChannelOperationRequest] = []
        self.cancelled_requests: list[ChannelOperationCancelRequest] = []
        self.listener = None
        self.unsubscribe_calls = 0
        self.accept_result: ChannelOperationAccepted | ChannelError | None = None
        self.cancel_result: ChannelOperationCancelled | ChannelError | None = None

    async def accept_operation(
        self, request: ChannelOperationRequest
    ) -> ChannelOperationAccepted | ChannelError:
        self.accepted_requests.append(request)
        if self.accept_result is not None:
            return self.accept_result
        return ChannelOperationAccepted(
            request_id=request.request_id,
            operation_id=request.envelope.payload.operation_id,
            run_id="run-1",
        )

    async def cancel_operation(
        self, request: ChannelOperationCancelRequest
    ) -> ChannelOperationCancelled | ChannelError:
        self.cancelled_requests.append(request)
        if self.cancel_result is not None:
            return self.cancel_result
        return ChannelOperationCancelled(
            request_id=request.request_id,
            operation_id=request.operation_id,
        )

    def subscribe_deliveries(self, listener):
        self.listener = listener

        def unsubscribe() -> None:
            self.unsubscribe_calls += 1

        return unsubscribe

    def emit(self, delivery: ChannelEventDelivery | ChannelError) -> None:
        assert self.listener is not None
        self.listener(delivery)


def test_channel_host_runs_standard_operation_request_and_releases_subscription() -> (
    None
):
    port = _FakePort()
    request = _operation_request(request_id="request-1", operation_id="operation-1")
    stdout = StringIO()
    host = ChannelHost(
        port=port,
        stdin=StringIO(encode_rpc_jsonl_frame(request) + "\n"),
        stdout=stdout,
    )

    assert asyncio.run(host.run()) == 0

    assert port.accepted_requests == [request]
    assert port.unsubscribe_calls == 1
    assert _output_frames(stdout) == [
        {
            "frame_type": "operation_accepted",
            "request_id": "request-1",
            "operation_id": "operation-1",
            "run_id": "run-1",
        }
    ]


def test_channel_host_correlates_delivered_work_event_to_accepted_request() -> None:
    port = _FakePort()
    stdout = StringIO()
    host = ChannelHost(port=port, stdin=StringIO(), stdout=stdout)
    request = _operation_request(request_id="request-1", operation_id="operation-1")

    async def scenario() -> None:
        await host.handle_line(encode_rpc_jsonl_frame(request))
        host.deliver(
            ChannelEventDelivery(
                envelope=ChannelEnvelope(
                    envelope_id="event-envelope-1",
                    kind="event",
                    payload=WorkEvent(
                        event_id="event-1",
                        kind="WorkRunCompleted",
                        run_id="run-1",
                        session_id="session-1",
                        domain="coding",
                        operation_id="operation-1",
                        sequence=1,
                        created_at=_created_at(),
                        delivery_hint="final_only",
                        payload={},
                    ),
                )
            )
        )

    asyncio.run(scenario())

    frames = _output_frames(stdout)
    assert frames[0]["frame_type"] == "operation_accepted"
    assert frames[1]["frame_type"] == "event"
    assert frames[1]["request_id"] == "request-1"


def test_channel_host_routes_standard_cancellation_request() -> None:
    port = _FakePort()
    stdout = StringIO()
    host = ChannelHost(port=port, stdin=StringIO(), stdout=stdout)
    request = ChannelOperationCancelRequest(
        request_id="cancel-1",
        operation_id="operation-1",
    )

    asyncio.run(host.handle_line(encode_rpc_jsonl_frame(request)))

    assert port.cancelled_requests == [request]
    assert _output_frames(stdout) == [
        {
            "frame_type": "operation_cancelled",
            "request_id": "cancel-1",
            "operation_id": "operation-1",
        }
    ]


def test_channel_host_rejects_invalid_frames_without_stopping() -> None:
    port = _FakePort()
    stdout = StringIO()
    host = ChannelHost(port=port, stdin=StringIO(), stdout=stdout)

    asyncio.run(host.handle_line("{not json}"))

    assert _output_frames(stdout) == [
        {
            "frame_type": "error",
            "request_id": None,
            "code": "invalid_frame",
            "message": "invalid channel JSONL frame: Expecting property name enclosed in double quotes",
            "retryable": False,
            "details": {},
        }
    ]


def test_channel_host_rejects_port_result_with_mismatched_correlation() -> None:
    port = _FakePort()
    port.accept_result = ChannelOperationAccepted(
        request_id="wrong-request",
        operation_id="operation-1",
    )
    stdout = StringIO()
    host = ChannelHost(port=port, stdin=StringIO(), stdout=stdout)

    asyncio.run(
        host.handle_line(
            encode_rpc_jsonl_frame(
                _operation_request(request_id="request-1", operation_id="operation-1")
            )
        )
    )

    assert _output_frames(stdout)[0]["code"] == "invalid_port_result"


def test_channel_host_preserves_product_rejection_details() -> None:
    port = _FakePort()
    port.accept_result = ChannelError(
        code="operation_denied",
        message="approval required",
        details={"risk": "high"},
    )
    stdout = StringIO()
    host = ChannelHost(port=port, stdin=StringIO(), stdout=stdout)

    asyncio.run(
        host.handle_line(
            encode_rpc_jsonl_frame(
                _operation_request(request_id="request-1", operation_id="operation-1")
            )
        )
    )

    frame = _output_frames(stdout)[0]
    assert frame["request_id"] == "request-1"
    assert frame["code"] == "operation_denied"
    assert frame["details"] == {"risk": "high"}


def _operation_request(
    *, request_id: str, operation_id: str
) -> ChannelOperationRequest:
    return ChannelOperationRequest(
        request_id=request_id,
        envelope=ChannelEnvelope(
            envelope_id=f"envelope-{operation_id}",
            kind="operation",
            payload=WorkOperation(
                operation_id=operation_id,
                kind="SubmitCodingTurn",
                session_id="session-1",
                domain="coding",
                payload={"text": "inspect"},
            ),
        ),
    )


def _output_frames(stream: StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def _created_at():
    from datetime import UTC, datetime

    return datetime(2026, 7, 19, tzinfo=UTC)
