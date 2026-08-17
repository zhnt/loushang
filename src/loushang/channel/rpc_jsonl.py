from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, TypeAlias, cast

from loushang.channel.json_codec import (
    channel_envelope_from_json,
    channel_envelope_to_json,
)
from loushang.channel.types import ChannelEnvelope
from loushang.foundation.json import JSONValue, dump_json_value, require_json_mapping

ChannelRpcFrameKind: TypeAlias = Literal[
    "operation_request",
    "operation_accepted",
    "operation_cancel_request",
    "operation_cancelled",
    "event",
    "error",
]


@dataclass(frozen=True)
class ChannelOperationRequest:
    """One correlated request to submit a WorkOperation through a channel."""

    request_id: str
    envelope: ChannelEnvelope

    def __post_init__(self) -> None:
        _require_text(self.request_id, name="channel request id")
        _require_envelope_kind(self.envelope, expected="operation")


@dataclass(frozen=True)
class ChannelOperationAccepted:
    """An ACK that only confirms acceptance; results arrive as event frames."""

    request_id: str
    operation_id: str
    run_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.request_id, name="channel request id")
        _require_text(self.operation_id, name="work operation id")
        _require_optional_text(self.run_id, name="work run id")


@dataclass(frozen=True)
class ChannelOperationCancelRequest:
    """One correlated request to cancel an accepted operation."""

    request_id: str
    operation_id: str

    def __post_init__(self) -> None:
        _require_text(self.request_id, name="channel request id")
        _require_text(self.operation_id, name="work operation id")


@dataclass(frozen=True)
class ChannelOperationCancelled:
    """An ACK that confirms cancellation admission, not final completion."""

    request_id: str
    operation_id: str

    def __post_init__(self) -> None:
        _require_text(self.request_id, name="channel request id")
        _require_text(self.operation_id, name="work operation id")


@dataclass(frozen=True)
class ChannelEventDelivery:
    """Deliver one WorkEvent or RuntimeEventView, optionally request-correlated."""

    envelope: ChannelEnvelope
    request_id: str | None = None

    def __post_init__(self) -> None:
        _require_envelope_kind(self.envelope, expected="event")
        _require_optional_text(self.request_id, name="channel request id")


@dataclass(frozen=True)
class ChannelError:
    """A transport or acceptance error, never a replacement for WorkEvent."""

    code: str
    message: str
    request_id: str | None = None
    retryable: bool = False
    details: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.code, name="channel error code")
        _require_text(self.message, name="channel error message")
        _require_optional_text(self.request_id, name="channel request id")
        if type(self.retryable) is not bool:
            raise TypeError("channel error retryable must be a boolean")
        object.__setattr__(
            self,
            "details",
            require_json_mapping(dict(self.details), name="channel error details"),
        )


ChannelRpcFrame: TypeAlias = (
    ChannelOperationRequest
    | ChannelOperationAccepted
    | ChannelOperationCancelRequest
    | ChannelOperationCancelled
    | ChannelEventDelivery
    | ChannelError
)


def rpc_jsonl_frame_to_json(frame: ChannelRpcFrame) -> dict[str, JSONValue]:
    """Encode one frame without adding a JSONL line terminator."""

    if isinstance(frame, ChannelOperationRequest):
        return {
            "frame_type": "operation_request",
            "request_id": frame.request_id,
            "envelope": channel_envelope_to_json(frame.envelope),
        }
    if isinstance(frame, ChannelOperationAccepted):
        return {
            "frame_type": "operation_accepted",
            "request_id": frame.request_id,
            "operation_id": frame.operation_id,
            "run_id": frame.run_id,
        }
    if isinstance(frame, ChannelOperationCancelRequest):
        return {
            "frame_type": "operation_cancel_request",
            "request_id": frame.request_id,
            "operation_id": frame.operation_id,
        }
    if isinstance(frame, ChannelOperationCancelled):
        return {
            "frame_type": "operation_cancelled",
            "request_id": frame.request_id,
            "operation_id": frame.operation_id,
        }
    if isinstance(frame, ChannelEventDelivery):
        return {
            "frame_type": "event",
            "request_id": frame.request_id,
            "envelope": channel_envelope_to_json(frame.envelope),
        }
    if isinstance(frame, ChannelError):
        return {
            "frame_type": "error",
            "request_id": frame.request_id,
            "code": frame.code,
            "message": frame.message,
            "retryable": frame.retryable,
            "details": dict(frame.details),
        }
    raise TypeError(f"unsupported Channel RPC frame: {type(frame).__name__}")


def rpc_jsonl_frame_from_json(data: Mapping[str, object]) -> ChannelRpcFrame:
    """Decode a frame while tolerating future additive fields."""

    payload = require_json_mapping(dict(data), name="channel_rpc_frame")
    frame_type = _require_frame_type(payload.get("frame_type"))
    if frame_type == "operation_request":
        envelope = _decode_envelope(payload.get("envelope"))
        return ChannelOperationRequest(
            request_id=_require_text(
                payload.get("request_id"), name="channel request id"
            ),
            envelope=envelope,
        )
    if frame_type == "operation_accepted":
        return ChannelOperationAccepted(
            request_id=_require_text(
                payload.get("request_id"), name="channel request id"
            ),
            operation_id=_require_text(
                payload.get("operation_id"), name="work operation id"
            ),
            run_id=_optional_text(payload.get("run_id"), name="work run id"),
        )
    if frame_type == "operation_cancel_request":
        return ChannelOperationCancelRequest(
            request_id=_require_text(
                payload.get("request_id"), name="channel request id"
            ),
            operation_id=_require_text(
                payload.get("operation_id"), name="work operation id"
            ),
        )
    if frame_type == "operation_cancelled":
        return ChannelOperationCancelled(
            request_id=_require_text(
                payload.get("request_id"), name="channel request id"
            ),
            operation_id=_require_text(
                payload.get("operation_id"), name="work operation id"
            ),
        )
    if frame_type == "event":
        return ChannelEventDelivery(
            request_id=_optional_text(
                payload.get("request_id"), name="channel request id"
            ),
            envelope=_decode_envelope(payload.get("envelope")),
        )
    return ChannelError(
        request_id=_optional_text(payload.get("request_id"), name="channel request id"),
        code=_require_text(payload.get("code"), name="channel error code"),
        message=_require_text(payload.get("message"), name="channel error message"),
        retryable=_require_bool(
            payload.get("retryable"), name="channel error retryable"
        ),
        details=_require_json_details(payload.get("details")),
    )


def encode_rpc_jsonl_frame(frame: ChannelRpcFrame) -> str:
    """Encode a single JSONL frame; callers own the trailing newline and I/O."""

    return dump_json_value(rpc_jsonl_frame_to_json(frame), name="channel_rpc_frame")


def decode_rpc_jsonl_frame(line: str) -> ChannelRpcFrame:
    """Decode exactly one JSONL line without binding to stdin or stdout."""

    if not isinstance(line, str):
        raise TypeError("channel JSONL frame must be a string")
    content = _strip_single_line_terminator(line)
    if not content.strip():
        raise ValueError("channel JSONL frame must not be empty")
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid channel JSONL frame: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise TypeError("channel JSONL frame must be a JSON object")
    return rpc_jsonl_frame_from_json(value)


def _strip_single_line_terminator(line: str) -> str:
    if line.endswith("\r\n"):
        line = line[:-2]
    elif line.endswith("\n"):
        line = line[:-1]
    if "\n" in line or "\r" in line:
        raise ValueError("channel JSONL input must contain exactly one frame")
    return line


def _decode_envelope(value: object) -> ChannelEnvelope:
    if not isinstance(value, Mapping):
        raise TypeError("channel envelope must be a JSON object")
    return channel_envelope_from_json(value)


def _require_frame_type(value: object) -> ChannelRpcFrameKind:
    value = _require_text(value, name="channel frame type")
    if value not in {
        "operation_request",
        "operation_accepted",
        "operation_cancel_request",
        "operation_cancelled",
        "event",
        "error",
    }:
        raise ValueError(f"unsupported channel frame type: {value}")
    return cast(ChannelRpcFrameKind, value)


def _require_envelope_kind(envelope: object, *, expected: str) -> None:
    if not isinstance(envelope, ChannelEnvelope):
        raise TypeError("channel frame envelope must be a ChannelEnvelope")
    if envelope.kind != expected:
        raise TypeError(f"{expected} channel frame requires an {expected} envelope")


def _require_text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_optional_text(value: object, *, name: str) -> None:
    if value is not None:
        _require_text(value, name=name)


def _optional_text(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, name=name)


def _require_bool(value: object, *, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a boolean")
    return cast(bool, value)


def _require_json_details(value: object) -> dict[str, JSONValue]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("channel error details must be a JSON object")
    return require_json_mapping(dict(value), name="channel error details")


__all__ = [
    "ChannelError",
    "ChannelEventDelivery",
    "ChannelOperationAccepted",
    "ChannelOperationCancelRequest",
    "ChannelOperationCancelled",
    "ChannelOperationRequest",
    "ChannelRpcFrame",
    "ChannelRpcFrameKind",
    "decode_rpc_jsonl_frame",
    "encode_rpc_jsonl_frame",
    "rpc_jsonl_frame_from_json",
    "rpc_jsonl_frame_to_json",
]
