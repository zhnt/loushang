"""Strict closed execution algebra, negotiated separately from legacy v1."""

from __future__ import annotations

from enum import Enum
from types import UnionType
from typing import cast, get_args, get_origin, get_type_hints

from ..protocol import (
    AckV1,
    AppFailureV1,
    InvalidAppMessageError,
    SessionEventV1,
    SessionIdentityV1,
    SessionSnapshotRequestV1,
    SessionSnapshotV1,
    TranscriptRecordV1,
)
from ..protocol.codec import _dumps, _loads, _object, _string
from .model import (
    ExecutionCallV1,
    ExecutionContentEventV1,
    ExecutionEventsV1,
    ExecutionFailureV1,
    ExecutionInterruptResultV1,
    ExecutionObservationV1,
    ExecutionOperationV1,
    ExecutionOutcomeV1,
    ExecutionRecordV1,
    ExecutionResponseV1,
    ExecutionResultV1,
    ExecutionSessionSnapshotV1,
    ExecutionSessionViewV1,
    ExecutionSourceSnapshotV1,
    ExecutionStateV1,
    ExecutionUpdateV1,
    _identifier,
)

EXECUTION_PROTOCOL_VERSION = "loushang.execution/v1"

# Explicit fields freeze the wire independently of future dataclass additions.
# No arbitrary type/name lookup or untyped Product payload is admitted.
_FIELDS: dict[type, tuple[str, ...]] = {
    AckV1: (), AppFailureV1: ("code",), ExecutionFailureV1: ("code",),
    SessionIdentityV1: ("product_id", "continuity_id", "session_id", "scope", "scope_fingerprint"),
    TranscriptRecordV1: ("kind", "text"),
    SessionSnapshotV1: ("identity", "title", "cursor", "revision", "running", "records"),
    SessionSnapshotRequestV1: ("attachment_id", "controller_generation", "member_id"),
    SessionEventV1: ("session_id", "cursor", "kind", "text", "interaction_id"),
    ExecutionOutcomeV1: ("status", "error_code", "legacy_result"),
    ExecutionStateV1: ("execution_id", "status", "revision", "interrupt_requested", "outcome"),
    ExecutionObservationV1: ("execution_id", "status", "final_cursor"),
    ExecutionSourceSnapshotV1: ("source", "observation", "draft", "truncated"),
    ExecutionRecordV1: ("service_instance_id", "identity", "submission_id", "state"),
    ExecutionSessionViewV1: ("identity", "revision", "quiescent", "active", "latest_terminal"),
    ExecutionSessionSnapshotV1: ("service_instance_id", "source", "executions"),
    ExecutionContentEventV1: ("source", "execution_id"),
    ExecutionUpdateV1: ("revision", "execution"),
    ExecutionEventsV1: ("events",),
    ExecutionInterruptResultV1: ("record", "disposition"),
}
_KINDS: dict[str, type] = {
    "record": ExecutionRecordV1, "snapshot": ExecutionSessionSnapshotV1,
    "events": ExecutionEventsV1, "failure": ExecutionFailureV1,
    "app_failure": AppFailureV1,
    "interrupt": ExecutionInterruptResultV1,
}


def _camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.title() for part in rest)


def _encode(value: object) -> object:
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, Enum):
        return value.value
    if type(value) is tuple:
        return [_encode(item) for item in value]
    fields = _FIELDS.get(type(value))
    if fields is None:
        raise InvalidAppMessageError()
    return {_camel(name): _encode(getattr(value, name)) for name in fields}


def _decode(expected: object, raw: object) -> object:
    if expected is type(None):
        if raw is not None:
            raise InvalidAppMessageError()
        return None
    if expected in (str, bool, int):
        if type(raw) is not expected:
            raise InvalidAppMessageError()
        return raw
    origin, args = get_origin(expected), get_args(expected)
    if origin is UnionType:
        for member in args:
            try:
                return _decode(member, raw)
            except (TypeError, ValueError, InvalidAppMessageError):
                pass
        raise InvalidAppMessageError()
    if origin is tuple and len(args) == 2 and args[1] is Ellipsis:
        if type(raw) is not list or len(raw) > 256:
            raise InvalidAppMessageError()
        return tuple(_decode(args[0], item) for item in raw)
    if isinstance(expected, type) and issubclass(expected, Enum):
        return expected(_string(raw))
    if not isinstance(expected, type) or expected not in _FIELDS:
        raise InvalidAppMessageError()
    fields = _FIELDS[expected]
    value = _object(raw, {_camel(name) for name in fields})
    annotations = get_type_hints(expected)
    return expected(**{
        name: _decode(annotations[name], value[_camel(name)]) for name in fields
    })


def is_execution_frame(payload: bytes) -> bool:
    return _loads(payload).get("protocolVersion") == EXECUTION_PROTOCOL_VERSION


def encode_call(call: ExecutionCallV1) -> bytes:
    if type(call) is not ExecutionCallV1:
        raise TypeError("invalid execution call")
    body = {
        "control": _encode(call.control), "expectedInstanceId": call.expected_instance_id,
    }
    if call.submission_id is not None:
        body["submissionId"] = call.submission_id
    if call.execution_id is not None:
        body["executionId"] = call.execution_id
    if call.text is not None:
        body["text"] = call.text
    return _dumps({
        "protocolVersion": EXECUTION_PROTOCOL_VERSION, "requestId": call.request_id,
        "operation": call.operation.value, "payload": body,
    })


def decode_call(payload: bytes) -> ExecutionCallV1:
    try:
        root = _object(_loads(payload), {"protocolVersion", "requestId", "operation", "payload"})
        if root["protocolVersion"] != EXECUTION_PROTOCOL_VERSION:
            raise InvalidAppMessageError()
        operation = ExecutionOperationV1(_string(root["operation"]))
        fields = {"control", "expectedInstanceId"}
        if operation in {ExecutionOperationV1.SUBMIT, ExecutionOperationV1.FIND}:
            fields.add("submissionId")
        if operation in {ExecutionOperationV1.GET, ExecutionOperationV1.INTERRUPT}:
            fields.add("executionId")
        if operation is ExecutionOperationV1.SUBMIT:
            fields.add("text")
        body = _object(root["payload"], fields)
        return ExecutionCallV1(
            _string(root["requestId"]), operation,
            cast(SessionSnapshotRequestV1, _decode(SessionSnapshotRequestV1, body["control"])),
            _string(body["expectedInstanceId"]),
            _string(body["submissionId"]) if "submissionId" in fields else None,
            _string(body["executionId"]) if "executionId" in fields else None,
            _string(body["text"]) if "text" in fields else None,
        )
    except (TypeError, ValueError, KeyError, RecursionError):
        raise InvalidAppMessageError() from None


def encode_response(response: ExecutionResponseV1) -> bytes:
    if type(response) is not ExecutionResponseV1:
        raise TypeError("invalid execution response")
    kind = "not_found" if response.result is None else next(
        key for key, value in _KINDS.items() if value is type(response.result)
    )
    return _dumps({
        "protocolVersion": EXECUTION_PROTOCOL_VERSION, "requestId": response.request_id,
        "resultType": kind, "result": _encode(response.result),
    })


def decode_response(payload: bytes) -> ExecutionResponseV1:
    try:
        root = _object(_loads(payload), {"protocolVersion", "requestId", "resultType", "result"})
        if root["protocolVersion"] != EXECUTION_PROTOCOL_VERSION:
            raise InvalidAppMessageError()
        kind = _string(root["resultType"])
        expected = type(None) if kind == "not_found" else _KINDS[kind]
        return ExecutionResponseV1(
            _string(root["requestId"]), cast(ExecutionResultV1, _decode(expected, root["result"]))
        )
    except (TypeError, ValueError, KeyError, RecursionError):
        raise InvalidAppMessageError() from None


def execution_hello(profile: str, service_instance_id: str) -> bytes:
    _identifier(service_instance_id)
    return _dumps({
        "profile": profile, "protocolVersion": "loushang.app/v1",
        "executionVersion": EXECUTION_PROTOCOL_VERSION, "serviceInstanceId": service_instance_id,
        "submissionRetention": "service_instance_lifetime",
        "restartRecovery": False,
    })


def decode_execution_hello(payload: bytes, profile: str) -> str:
    root = _loads(payload)
    instance = _string(root.get("serviceInstanceId"))
    try:
        if payload != execution_hello(profile, instance):
            raise InvalidAppMessageError()
    except (TypeError, ValueError):
        raise InvalidAppMessageError() from None
    return instance
