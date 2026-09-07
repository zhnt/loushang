"""Closed G14 foreground profile shared by both peers; no runtime or IO."""

from __future__ import annotations

from .errors import InvalidAppMessageError
from .model import AppOperationV1

STDIO_HELLO_V1 = (
    b'{"profile":"foreground-stdio/v1","protocolVersion":"loushang.app/v1"}'
)
MAX_ORDINARY_REQUESTS = 16
MAX_CONTROL_REQUESTS = 4
CONTROL_OPERATIONS = frozenset(
    {
        AppOperationV1.TURN_INTERRUPT,
        AppOperationV1.INTERACTION_RESPOND,
        AppOperationV1.MUX_DETACH,
        AppOperationV1.ATTACHMENT_READ_EVENTS,
    }
)


def connection_request_number(request_id: str) -> int:
    if (
        not request_id.isascii()
        or not request_id.isdecimal()
        or request_id.startswith("0")
        or len(request_id) > 19
    ):
        raise InvalidAppMessageError()
    value = int(request_id)
    if value > (1 << 63) - 1:
        raise InvalidAppMessageError()
    return value
