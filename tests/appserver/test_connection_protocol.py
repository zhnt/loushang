from __future__ import annotations

import pytest

from loushang.appserver.protocol import (
    AppOperationV1,
    AppRequestV1,
    AppResponseV1,
    AttachmentEventsV1,
    AttachmentEventV1,
    AttachmentReadEventsV1,
    InvalidAppMessageError,
    SessionEventKindV1,
    SessionEventV1,
    decode_request,
    decode_response,
    encode_request,
    encode_response,
)
from loushang.appserver.protocol.codec import MAX_MESSAGE_BYTES


def test_G14_WIRE_poll_request_and_result_round_trip() -> None:
    request = AppRequestV1(
        "1",
        AppOperationV1.ATTACHMENT_READ_EVENTS,
        AttachmentReadEventsV1("attachment-1", 1, 64),
    )
    event = AttachmentEventV1(
        "attachment-1",
        "member-1",
        SessionEventV1("session-1", 1, SessionEventKindV1.ASSISTANT_DELTA, "你好"),
    )
    response = AppResponseV1("1", AttachmentEventsV1((event,)))
    assert decode_request(encode_request(request)) == request
    assert decode_response(encode_response(response)) == response


@pytest.mark.parametrize("limit", [0, 65, True, -1])
def test_G14_WIRE_poll_limits_are_strict(limit: int) -> None:
    with pytest.raises(ValueError):
        AttachmentReadEventsV1("attachment-1", 1, limit)


def test_G14_WIRE_deep_input_is_a_redacted_protocol_failure() -> None:
    with pytest.raises(InvalidAppMessageError, match="^invalid_request$"):
        decode_request(b'{"nested":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}")


def test_G14_WIRE_outgoing_bytes_obey_the_incoming_bound() -> None:
    event = AttachmentEventV1(
        "attachment-1",
        "member-1",
        SessionEventV1(
            "session-1", 1, SessionEventKindV1.ASSISTANT_DELTA, "\x00" * 262144
        ),
    )
    assert len(event.event.text or "") < MAX_MESSAGE_BYTES
    with pytest.raises(InvalidAppMessageError):
        encode_response(AppResponseV1("1", AttachmentEventsV1((event,))))
