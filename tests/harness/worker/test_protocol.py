from __future__ import annotations

import asyncio

import pytest

from loushang.harness.worker.protocol import (
    WORKER_PROTOCOL_MAX_FRAME_BYTES,
    WORKER_PROTOCOL_MAX_JSON_DEPTH,
    WorkerFrameCodec,
    WorkerFramedTransport,
    WorkerProtocolError,
    WorkerProtocolMessage,
)


class _ReadProbe:
    def __init__(self, body: bytes) -> None:
        self._body = bytearray(body)
        self.read_sizes: list[int] = []

    async def read_exactly(self, size: int) -> bytes:
        self.read_sizes.append(size)
        if len(self._body) < size:
            raise EOFError
        result = bytes(self._body[:size])
        del self._body[:size]
        return result

    async def write(self, body: bytes) -> None:
        self._body.extend(body)

    async def close(self) -> None:
        return None


class _BlockingWriteProbe(_ReadProbe):
    def __init__(self) -> None:
        super().__init__(b"")
        self.entered = asyncio.Event()
        self.closed = False

    async def write(self, body: bytes) -> None:
        del body
        self.entered.set()
        await asyncio.Future()

    async def close(self) -> None:
        self.closed = True


def test_frame_codec_round_trips_canonical_directional_message() -> None:
    message = WorkerProtocolMessage.create(
        "query",
        correlationId="a" * 32,
        payload={"operation": "describe", "ordinal": 1},
    )
    frame = WorkerFrameCodec.encode(message)
    size = WorkerFrameCodec.decode_header(frame[:4])

    assert size == len(frame) - 4
    assert WorkerFrameCodec.decode_body(frame[4:], expected_size=size) == message


def test_frame_length_is_rejected_before_body_read_or_allocation() -> None:
    async def scenario() -> None:
        transport = _ReadProbe((WORKER_PROTOCOL_MAX_FRAME_BYTES + 1).to_bytes(4, "big"))
        framed = WorkerFramedTransport(transport)

        with pytest.raises(WorkerProtocolError) as caught:
            await framed.receive(direction="worker_to_host")

        assert caught.value.code == "worker_protocol_frame_too_large"
        assert transport.read_sizes == [4]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (
            b'{"kind":"pong","heartbeatId":"x","heartbeatId":"y","messageVersion":1}',
            "worker_protocol_frame_duplicate_key",
        ),
        (
            b'{"messageVersion":1, "kind":"shutdown_ack"}',
            "worker_protocol_frame_noncanonical",
        ),
    ],
)
def test_frame_codec_rejects_duplicate_keys_and_noncanonical_bytes(
    body: bytes,
    code: str,
) -> None:
    with pytest.raises(WorkerProtocolError) as caught:
        WorkerFrameCodec.decode_body(body, expected_size=len(body))

    assert caught.value.code == code


def test_transport_rejects_message_on_the_wrong_direction() -> None:
    async def scenario() -> None:
        message = WorkerProtocolMessage.create(
            "query",
            correlationId="a" * 32,
            payload={},
        )
        probe = _ReadProbe(WorkerFrameCodec.encode(message))
        framed = WorkerFramedTransport(probe)

        with pytest.raises(WorkerProtocolError) as caught:
            await framed.receive(direction="worker_to_host")

        assert caught.value.code == "worker_protocol_message_direction_invalid"

    asyncio.run(scenario())


def test_protocol_rejects_unknown_direction_and_boolean_message_version() -> None:
    message = WorkerProtocolMessage.create(
        "query",
        correlationId="a" * 32,
        payload={},
    )

    async def scenario() -> None:
        framed = WorkerFramedTransport(_ReadProbe(b""))
        with pytest.raises(WorkerProtocolError) as caught:
            await framed.send(message, direction="sideways")  # type: ignore[arg-type]
        assert caught.value.code == "worker_protocol_message_direction_invalid"

    asyncio.run(scenario())
    with pytest.raises(ValueError, match="message version"):
        WorkerProtocolMessage(
            kind="query",
            fields={"correlationId": "a" * 32, "payload": {}},
            message_version=True,  # type: ignore[arg-type]
        )


def test_message_schema_rejects_unknown_fields_and_non_object_payloads() -> None:
    with pytest.raises(WorkerProtocolError) as caught:
        WorkerProtocolMessage.from_dict(
            {
                "correlationId": "a" * 32,
                "kind": "result",
                "messageVersion": 1,
                "payload": {},
                "registrar": "forbidden",
            }
        )
    assert caught.value.code == "worker_protocol_message_fields_invalid"

    with pytest.raises(TypeError, match="payload"):
        WorkerProtocolMessage.create(
            "query",
            correlationId="a" * 32,
            payload=["not", "an", "object"],
        )


def test_message_schema_bounds_json_depth_and_start_identity() -> None:
    nested: dict[str, object] = {}
    for _ in range(WORKER_PROTOCOL_MAX_JSON_DEPTH + 1):
        nested = {"nested": nested}
    with pytest.raises(ValueError, match="nesting is too deep"):
        WorkerProtocolMessage.create(
            "query",
            correlationId="a" * 32,
            payload=nested,
        )

    with pytest.raises(WorkerProtocolError) as caught:
        WorkerProtocolMessage.from_dict(
            {
                "identity": {"attemptId": "a" * 32},
                "kind": "start",
                "messageVersion": 1,
                "protocol": "capability.query",
                "protocolVersion": 1,
            }
        )
    assert caught.value.code == "worker_protocol_message_value_invalid"


def test_cancelled_frame_write_closes_the_uncertain_transport() -> None:
    async def scenario() -> None:
        probe = _BlockingWriteProbe()
        transport = WorkerFramedTransport(probe)
        task = asyncio.create_task(
            transport.send(
                WorkerProtocolMessage.create("ping", heartbeatId="a" * 32),
                direction="host_to_worker",
            )
        )
        await probe.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert probe.closed is True
        assert transport.failure_code == "worker_protocol_write_cancelled"
        with pytest.raises(WorkerProtocolError) as caught:
            await transport.send(
                WorkerProtocolMessage.create("ping", heartbeatId="b" * 32),
                direction="host_to_worker",
            )
        assert caught.value.code == "worker_protocol_transport_closed"

    asyncio.run(scenario())
