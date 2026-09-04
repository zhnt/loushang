"""Bounded, canonical, direction-aware protocol for local Worker sessions."""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, NoReturn, Protocol, cast

WORKER_PROTOCOL_MESSAGE_VERSION = 1
WORKER_PROTOCOL_MAX_FRAME_BYTES = 256 * 1024
WORKER_PROTOCOL_MAX_JSON_DEPTH = 32
WORKER_PROTOCOL_MAX_JSON_CONTAINERS = 4096

WorkerMessageDirection = Literal["host_to_worker", "worker_to_host"]
WorkerMessageKind = Literal[
    "start",
    "ready",
    "query",
    "result",
    "failure",
    "cancel",
    "cancelled",
    "ping",
    "pong",
    "shutdown",
    "shutdown_ack",
]

_HOST_MESSAGE_KINDS = frozenset({"start", "query", "cancel", "ping", "shutdown"})
_WORKER_MESSAGE_KINDS = frozenset(
    {"ready", "result", "failure", "cancelled", "pong", "shutdown_ack"}
)
_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
_MAX_IDENTIFIER_LENGTH = 128
_START_IDENTITY_FIELDS = frozenset(
    {
        "attemptId",
        "contributionId",
        "declarationFingerprint",
        "identityVersion",
        "ownerGeneration",
        "ownerId",
        "pluginId",
        "pluginRevisionDigest",
        "productId",
        "scopeId",
        "sessionNonce",
        "supervisorEpoch",
        "workerConfigurationFingerprint",
    }
)
_MESSAGE_FIELDS: dict[str, frozenset[str]] = {
    "start": frozenset(
        {"identity", "kind", "messageVersion", "protocol", "protocolVersion"}
    ),
    "ready": frozenset(
        {
            "attemptId",
            "identityFingerprint",
            "kind",
            "messageVersion",
            "protocol",
            "protocolVersion",
            "sessionNonce",
            "supervisorEpoch",
        }
    ),
    "query": frozenset({"correlationId", "kind", "messageVersion", "payload"}),
    "result": frozenset({"correlationId", "kind", "messageVersion", "payload"}),
    "failure": frozenset(
        {"code", "correlationId", "kind", "messageVersion", "retryable"}
    ),
    "cancel": frozenset({"correlationId", "kind", "messageVersion"}),
    "cancelled": frozenset({"correlationId", "kind", "messageVersion"}),
    "ping": frozenset({"heartbeatId", "kind", "messageVersion"}),
    "pong": frozenset({"heartbeatId", "kind", "messageVersion"}),
    "shutdown": frozenset({"kind", "messageVersion", "reason"}),
    "shutdown_ack": frozenset({"kind", "messageVersion"}),
}


class WorkerProtocolError(RuntimeError):
    """Finite, redacted protocol failure suitable for supervisor evidence."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class WorkerByteTransport(Protocol):
    async def read_exactly(self, size: int) -> bytes: ...

    async def write(self, body: bytes) -> None: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class WorkerProtocolMessage:
    kind: WorkerMessageKind
    fields: Mapping[str, object]
    message_version: int = WORKER_PROTOCOL_MESSAGE_VERSION

    def __post_init__(self) -> None:
        if self.kind not in _MESSAGE_FIELDS:
            raise ValueError("Unsupported Worker protocol message kind")
        if (
            type(self.message_version) is not int
            or self.message_version != WORKER_PROTOCOL_MESSAGE_VERSION
        ):
            raise ValueError("Unsupported Worker protocol message version")
        if not isinstance(self.fields, Mapping):
            raise TypeError("Worker protocol message fields must be a mapping")
        fields = dict(self.fields)
        if set(fields) != _MESSAGE_FIELDS[self.kind] - {"kind", "messageVersion"}:
            raise ValueError("Worker protocol message fields do not match its kind")
        _validate_message_fields(self.kind, fields)
        _validate_json(fields)
        object.__setattr__(self, "fields", _freeze_mapping(fields))

    @classmethod
    def create(
        cls,
        kind: WorkerMessageKind,
        **fields: object,
    ) -> WorkerProtocolMessage:
        return cls(kind=kind, fields=fields)

    @classmethod
    def from_dict(cls, value: object) -> WorkerProtocolMessage:
        if not isinstance(value, dict):
            _raise_protocol(
                "worker_protocol_message_type_invalid",
                "Worker protocol message must be an object",
            )
        kind = value.get("kind")
        if not isinstance(kind, str) or kind not in _MESSAGE_FIELDS:
            _raise_protocol(
                "worker_protocol_message_kind_invalid",
                "Worker protocol message kind is unsupported",
            )
        if set(value) != _MESSAGE_FIELDS[kind]:
            _raise_protocol(
                "worker_protocol_message_fields_invalid",
                "Worker protocol message fields do not match its kind",
            )
        version = value.get("messageVersion")
        if type(version) is not int or version != WORKER_PROTOCOL_MESSAGE_VERSION:
            _raise_protocol(
                "worker_protocol_message_version_unsupported",
                "Worker protocol message version is unsupported",
            )
        fields = {
            key: item
            for key, item in value.items()
            if key not in {"kind", "messageVersion"}
        }
        try:
            return cls(
                kind=cast(WorkerMessageKind, kind),
                fields=fields,
                message_version=version,
            )
        except (TypeError, ValueError) as exc:
            raise WorkerProtocolError(
                "Worker protocol message values are invalid",
                code="worker_protocol_message_value_invalid",
            ) from exc

    def to_dict(self) -> dict[str, object]:
        return {
            **cast(dict[str, object], _thaw_json(self.fields)),
            "kind": self.kind,
            "messageVersion": self.message_version,
        }


class WorkerFrameCodec:
    """Four-byte big-endian length prefix plus canonical JSON object body."""

    @staticmethod
    def encode(message: WorkerProtocolMessage) -> bytes:
        if not isinstance(message, WorkerProtocolMessage):
            raise TypeError("Worker frame codec requires a typed message")
        body = _encode_document(message.to_dict())
        if not body or len(body) > WORKER_PROTOCOL_MAX_FRAME_BYTES:
            _raise_protocol(
                "worker_protocol_frame_too_large",
                "Worker protocol frame exceeds its byte limit",
            )
        return len(body).to_bytes(4, "big") + body

    @staticmethod
    def decode_header(header: bytes) -> int:
        if not isinstance(header, bytes) or len(header) != 4:
            _raise_protocol(
                "worker_protocol_frame_header_invalid",
                "Worker protocol frame header must contain four bytes",
            )
        size = int.from_bytes(header, "big")
        if size < 1 or size > WORKER_PROTOCOL_MAX_FRAME_BYTES:
            _raise_protocol(
                "worker_protocol_frame_too_large",
                "Worker protocol frame length is outside the accepted bound",
            )
        return size

    @staticmethod
    def decode_body(body: bytes, *, expected_size: int) -> WorkerProtocolMessage:
        if not isinstance(body, bytes) or len(body) != expected_size:
            _raise_protocol(
                "worker_protocol_frame_body_incomplete",
                "Worker protocol frame body length changed",
            )
        try:
            value = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
            _validate_json(value)
        except WorkerProtocolError:
            raise
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
            TypeError,
            ValueError,
        ) as exc:
            raise WorkerProtocolError(
                "Worker protocol frame is not strict JSON",
                code="worker_protocol_frame_json_invalid",
            ) from exc
        if _encode_document(value) != body:
            _raise_protocol(
                "worker_protocol_frame_noncanonical",
                "Worker protocol frame bytes are not canonical",
            )
        return WorkerProtocolMessage.from_dict(value)


class WorkerFramedTransport:
    """Serialize bounded frames over an injected byte transport."""

    def __init__(self, transport: WorkerByteTransport) -> None:
        if not all(
            callable(getattr(transport, name, None))
            for name in ("read_exactly", "write", "close")
        ):
            raise TypeError("Worker framed transport requires a byte transport")
        self._transport = transport
        self._write_lock = asyncio.Lock()
        self._closed = False
        self._failure_code: str | None = None

    @property
    def failure_code(self) -> str | None:
        return self._failure_code

    async def send(
        self,
        message: WorkerProtocolMessage,
        *,
        direction: WorkerMessageDirection,
    ) -> None:
        _require_direction(message, direction)
        frame = WorkerFrameCodec.encode(message)
        async with self._write_lock:
            if self._closed:
                _raise_protocol(
                    "worker_protocol_transport_closed",
                    "Worker protocol transport is closed",
                )
            try:
                await self._transport.write(frame)
            except asyncio.CancelledError:
                await self._close_after_write_failure(
                    code="worker_protocol_write_cancelled"
                )
                raise
            except BaseException as exc:
                await self._close_after_write_failure(
                    code="worker_protocol_write_failed"
                )
                raise WorkerProtocolError(
                    "Worker protocol frame write failed",
                    code="worker_protocol_write_failed",
                ) from exc

    async def receive(
        self,
        *,
        direction: WorkerMessageDirection,
    ) -> WorkerProtocolMessage:
        if self._closed:
            _raise_protocol(
                "worker_protocol_transport_closed",
                "Worker protocol transport is closed",
            )
        try:
            header = await self._transport.read_exactly(4)
            size = WorkerFrameCodec.decode_header(header)
            body = await self._transport.read_exactly(size)
        except WorkerProtocolError:
            raise
        except (EOFError, asyncio.IncompleteReadError) as exc:
            raise WorkerProtocolError(
                "Worker protocol peer closed the transport",
                code="worker_protocol_peer_closed",
            ) from exc
        message = WorkerFrameCodec.decode_body(body, expected_size=size)
        _require_direction(message, direction)
        return message

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._transport.close()

    async def _close_after_write_failure(self, *, code: str) -> None:
        self._failure_code = code
        self._closed = True
        with suppress(BaseException):
            await asyncio.shield(self._transport.close())


class AsyncioStreamWorkerTransport:
    """Byte transport adapter for an already-owned non-stdio stream pair."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        if not isinstance(reader, asyncio.StreamReader):
            raise TypeError("Worker stream transport requires an asyncio reader")
        if not isinstance(writer, asyncio.StreamWriter):
            raise TypeError("Worker stream transport requires an asyncio writer")
        self._reader = reader
        self._writer = writer

    async def read_exactly(self, size: int) -> bytes:
        return await self._reader.readexactly(size)

    async def write(self, body: bytes) -> None:
        self._writer.write(body)
        await self._writer.drain()

    async def close(self) -> None:
        self._writer.close()
        await self._writer.wait_closed()


def _require_direction(
    message: WorkerProtocolMessage,
    direction: WorkerMessageDirection,
) -> None:
    if type(direction) is not str or direction not in {
        "host_to_worker",
        "worker_to_host",
    }:
        _raise_protocol(
            "worker_protocol_message_direction_invalid",
            "Worker protocol message direction is invalid",
        )
    allowed = (
        _HOST_MESSAGE_KINDS if direction == "host_to_worker" else _WORKER_MESSAGE_KINDS
    )
    if message.kind not in allowed:
        _raise_protocol(
            "worker_protocol_message_direction_invalid",
            "Worker protocol message is illegal for this direction",
        )


def _validate_message_fields(kind: str, fields: Mapping[str, object]) -> None:
    for name in ("code", "protocol", "reason"):
        if name in fields and (
            not isinstance(fields[name], str)
            or len(cast(str, fields[name])) > _MAX_IDENTIFIER_LENGTH
            or not _IDENTIFIER.fullmatch(cast(str, fields[name]))
        ):
            raise ValueError(f"Worker protocol {name} must be an identifier")
    for name, length in (
        ("attemptId", 32),
        ("correlationId", 32),
        ("heartbeatId", 32),
        ("identityFingerprint", 64),
        ("sessionNonce", 64),
    ):
        if name in fields and (
            not isinstance(fields[name], str)
            or len(cast(str, fields[name])) != length
            or any(char not in "0123456789abcdef" for char in cast(str, fields[name]))
        ):
            raise ValueError(f"Worker protocol {name} must be lowercase hexadecimal")
    for name in ("protocolVersion", "supervisorEpoch"):
        if name in fields and (
            type(fields[name]) is not int or cast(int, fields[name]) < 1
        ):
            raise ValueError(f"Worker protocol {name} must be a positive integer")
    if "retryable" in fields and type(fields["retryable"]) is not bool:
        raise TypeError("Worker protocol retryable must be a bool")
    if kind == "start":
        identity = fields.get("identity")
        if not isinstance(identity, dict):
            raise TypeError("Worker start identity must be an object")
        _validate_start_identity(identity)
    if kind in {"query", "result"} and not isinstance(fields.get("payload"), dict):
        raise TypeError("Worker query/result payload must be an object")


def _encode_document(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError) as exc:
        raise WorkerProtocolError(
            "Worker protocol message is not strict JSON",
            code="worker_protocol_message_json_invalid",
        ) from exc


def _validate_json(value: object) -> None:
    containers = 0
    pending: list[tuple[object, int]] = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if item is None or isinstance(item, str | bool | int):
            continue
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("Worker protocol JSON numbers must be finite")
            continue
        if isinstance(item, Mapping):
            containers += 1
            if depth >= WORKER_PROTOCOL_MAX_JSON_DEPTH:
                raise ValueError("Worker protocol JSON nesting is too deep")
            if containers > WORKER_PROTOCOL_MAX_JSON_CONTAINERS:
                raise ValueError("Worker protocol JSON has too many containers")
            for key, child in item.items():
                if not isinstance(key, str):
                    raise TypeError("Worker protocol object keys must be strings")
                pending.append((child, depth + 1))
            continue
        if isinstance(item, list | tuple):
            containers += 1
            if depth >= WORKER_PROTOCOL_MAX_JSON_DEPTH:
                raise ValueError("Worker protocol JSON nesting is too deep")
            if containers > WORKER_PROTOCOL_MAX_JSON_CONTAINERS:
                raise ValueError("Worker protocol JSON has too many containers")
            pending.extend((child, depth + 1) for child in item)
            continue
        raise TypeError("Worker protocol values must be strict JSON")


def _validate_start_identity(identity: Mapping[str, object]) -> None:
    if set(identity) != _START_IDENTITY_FIELDS:
        raise ValueError("Worker start identity fields are invalid")
    for name in (
        "contributionId",
        "ownerId",
        "pluginId",
        "productId",
        "scopeId",
    ):
        value = identity[name]
        if (
            not isinstance(value, str)
            or len(value) > _MAX_IDENTIFIER_LENGTH
            or not _IDENTIFIER.fullmatch(value)
        ):
            raise ValueError(f"Worker start identity {name} is invalid")
    for name, length in (
        ("attemptId", 32),
        ("declarationFingerprint", 64),
        ("pluginRevisionDigest", 64),
        ("sessionNonce", 64),
        ("workerConfigurationFingerprint", 64),
    ):
        value = identity[name]
        if (
            not isinstance(value, str)
            or len(value) != length
            or any(char not in "0123456789abcdef" for char in value)
        ):
            raise ValueError(f"Worker start identity {name} is invalid")
    if type(identity["identityVersion"]) is not int or identity["identityVersion"] != 1:
        raise ValueError("Worker start identity version is unsupported")
    for name in ("ownerGeneration", "supervisorEpoch"):
        if type(identity[name]) is not int or cast(int, identity[name]) < 1:
            raise ValueError(f"Worker start identity {name} is invalid")


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _raise_protocol(
                "worker_protocol_frame_duplicate_key",
                "Worker protocol frame contains a duplicate JSON key",
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Unsupported JSON constant: {value}")


def _raise_protocol(code: str, message: str) -> NoReturn:
    raise WorkerProtocolError(message, code=code)


__all__ = [
    "WORKER_PROTOCOL_MAX_FRAME_BYTES",
    "WORKER_PROTOCOL_MAX_JSON_CONTAINERS",
    "WORKER_PROTOCOL_MAX_JSON_DEPTH",
    "WORKER_PROTOCOL_MESSAGE_VERSION",
    "AsyncioStreamWorkerTransport",
    "WorkerByteTransport",
    "WorkerFrameCodec",
    "WorkerFramedTransport",
    "WorkerMessageDirection",
    "WorkerMessageKind",
    "WorkerProtocolError",
    "WorkerProtocolMessage",
]
