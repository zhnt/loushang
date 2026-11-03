"""Closed optional management wire; transports authority but never issues it."""

from __future__ import annotations

from dataclasses import dataclass

from .managed_mux import ManagedMuxCreatedV1, ManagedMuxCreateV1
from .managed_mux_close import (
    ManagedMuxClosePhaseV1,
    ManagedMuxCloseStateV1,
    ManagedMuxCloseV1,
)
from .protocol import (
    AppErrorCodeV1,
    AppFailureV1,
    AppOperationV1,
    InvalidAppMessageError,
)
from .protocol.codec import _dumps, _loads, _object, _string
from .protocol.stdio_profile import connection_request_number

MANAGED_MUX_PROTOCOL_VERSION = "loushang.managed-mux/v1"
MANAGED_MUX_CLOSE_PROTOCOL_VERSION = "loushang.managed-mux-close/v1"
MAX_MANAGED_MUX_FRAME = 4096


@dataclass(frozen=True, slots=True)
class ManagedMuxCallV1:
    request_id: str
    request: ManagedMuxCreateV1

    def __post_init__(self) -> None:
        connection_request_number(self.request_id)
        if type(self.request) is not ManagedMuxCreateV1:
            raise InvalidAppMessageError()

    @property
    def operation(self) -> AppOperationV1:
        return AppOperationV1.MUX_CREATE


@dataclass(frozen=True, slots=True)
class ManagedMuxResponseV1:
    request_id: str
    result: ManagedMuxCreatedV1 | AppFailureV1

    def __post_init__(self) -> None:
        connection_request_number(self.request_id)
        if type(self.result) not in (ManagedMuxCreatedV1, AppFailureV1):
            raise InvalidAppMessageError()


def _frame(payload: bytes, fields: set[str], version: str = MANAGED_MUX_PROTOCOL_VERSION) -> dict[str, object]:
    if type(payload) is not bytes or not 1 <= len(payload) <= MAX_MANAGED_MUX_FRAME:
        raise InvalidAppMessageError()
    value = _object(_loads(payload), fields | {"protocolVersion", "requestId"})
    if value["protocolVersion"] != version:
        raise InvalidAppMessageError()
    connection_request_number(_string(value["requestId"]))
    return value


def encode_call(call: ManagedMuxCallV1) -> bytes:
    if type(call) is not ManagedMuxCallV1:
        raise InvalidAppMessageError()
    request = call.request
    return _dumps({
        "protocolVersion": MANAGED_MUX_PROTOCOL_VERSION, "requestId": call.request_id,
        "operation": "mux/create", "request": {
            "serviceId": request.service_id, "instanceId": request.instance_id,
            "operationId": request.operation_id, "name": request.name, "authority": request.authority,
        },
    })


def decode_call(payload: bytes) -> ManagedMuxCallV1:
    try:
        value = _frame(payload, {"operation", "request"})
        if value["operation"] != "mux/create":
            raise InvalidAppMessageError()
        request = _object(value["request"], {"serviceId", "instanceId", "operationId", "name", "authority"})
        return ManagedMuxCallV1(_string(value["requestId"]), ManagedMuxCreateV1(
            _string(request["serviceId"]), _string(request["instanceId"]),
            _string(request["operationId"]), _string(request["name"]), _string(request["authority"]),
        ))
    except (ValueError, TypeError):
        raise InvalidAppMessageError() from None


def encode_response(response: ManagedMuxResponseV1) -> bytes:
    if type(response) is not ManagedMuxResponseV1:
        raise InvalidAppMessageError()
    result = response.result
    body: dict[str, object]
    if type(result) is AppFailureV1:
        body = {"kind": "failure", "code": result.code.value}
    elif type(result) is ManagedMuxCreatedV1:
        body = {"kind": "created", "operationId": result.operation_id,
                "instanceId": result.instance_id, "name": result.name, "muxSpaceId": result.mux_space_id}
    else:
        raise InvalidAppMessageError()
    return _dumps({"protocolVersion": MANAGED_MUX_PROTOCOL_VERSION,
                   "requestId": response.request_id, "result": body})


def decode_response(payload: bytes) -> ManagedMuxResponseV1:
    try:
        value = _frame(payload, {"result"})
        result = value["result"]
        if type(result) is not dict:
            raise InvalidAppMessageError()
        decoded: ManagedMuxCreatedV1 | AppFailureV1
        if result.get("kind") == "failure":
            fields = _object(result, {"kind", "code"})
            decoded = AppFailureV1(AppErrorCodeV1(_string(fields["code"])))
        else:
            fields = _object(result, {"kind", "operationId", "instanceId", "name", "muxSpaceId"})
            if fields["kind"] != "created":
                raise InvalidAppMessageError()
            decoded = ManagedMuxCreatedV1(_string(fields["operationId"]), _string(fields["instanceId"]),
                                           _string(fields["name"]), _string(fields["muxSpaceId"]))
        return ManagedMuxResponseV1(_string(value["requestId"]), decoded)
    except (ValueError, TypeError):
        raise InvalidAppMessageError() from None


@dataclass(frozen=True, slots=True)
class ManagedMuxCloseCallV1:
    request_id: str
    request: ManagedMuxCloseV1
    read_result: bool = False

    def __post_init__(self) -> None:
        connection_request_number(self.request_id)
        if type(self.request) is not ManagedMuxCloseV1 or type(self.read_result) is not bool:
            raise InvalidAppMessageError()

    @property
    def operation(self) -> AppOperationV1:
        return AppOperationV1.MUX_READ if self.read_result else AppOperationV1.MUX_CLOSE


@dataclass(frozen=True, slots=True)
class ManagedMuxCloseResponseV1:
    request_id: str
    result: ManagedMuxCloseStateV1 | AppFailureV1 | None

    def __post_init__(self) -> None:
        connection_request_number(self.request_id)
        if self.result is not None and type(self.result) not in (ManagedMuxCloseStateV1, AppFailureV1):
            raise InvalidAppMessageError()


def encode_close_call(call: ManagedMuxCloseCallV1) -> bytes:
    if type(call) is not ManagedMuxCloseCallV1:
        raise InvalidAppMessageError()
    request = call.request
    return _dumps({
        "protocolVersion": MANAGED_MUX_CLOSE_PROTOCOL_VERSION, "requestId": call.request_id,
        "operation": "mux/close/read" if call.read_result else "mux/close", "request": {
            "serviceId": request.service_id, "instanceId": request.instance_id,
            "operationId": request.operation_id, "creationOperationId": request.creation_operation_id,
            "name": request.name, "muxSpaceId": request.mux_space_id, "authority": request.authority,
        },
    })


def decode_close_call(payload: bytes) -> ManagedMuxCloseCallV1:
    try:
        value = _frame(payload, {"operation", "request"}, MANAGED_MUX_CLOSE_PROTOCOL_VERSION)
        if value["operation"] not in ("mux/close", "mux/close/read"):
            raise InvalidAppMessageError()
        request = _object(value["request"], {
            "serviceId", "instanceId", "operationId", "creationOperationId", "name", "muxSpaceId", "authority",
        })
        return ManagedMuxCloseCallV1(_string(value["requestId"]), ManagedMuxCloseV1(
            _string(request["serviceId"]), _string(request["instanceId"]), _string(request["operationId"]),
            _string(request["creationOperationId"]), _string(request["name"]),
            _string(request["muxSpaceId"]), _string(request["authority"]),
        ), read_result=value["operation"] == "mux/close/read")
    except (ValueError, TypeError):
        raise InvalidAppMessageError() from None


def encode_close_response(response: ManagedMuxCloseResponseV1) -> bytes:
    if type(response) is not ManagedMuxCloseResponseV1:
        raise InvalidAppMessageError()
    result = response.result
    body: dict[str, object] | None = None
    if type(result) is AppFailureV1:
        body = {"kind": "failure", "code": result.code.value}
    elif type(result) is ManagedMuxCloseStateV1:
        body = {"kind": "close_state", "operationId": result.operation_id, "instanceId": result.instance_id,
                "creationOperationId": result.creation_operation_id, "name": result.name,
                "muxSpaceId": result.mux_space_id, "phase": result.phase.value}
    return _dumps({"protocolVersion": MANAGED_MUX_CLOSE_PROTOCOL_VERSION,
                   "requestId": response.request_id, "result": body})


def decode_close_response(payload: bytes) -> ManagedMuxCloseResponseV1:
    try:
        value = _frame(payload, {"result"}, MANAGED_MUX_CLOSE_PROTOCOL_VERSION)
        result = value["result"]
        decoded: ManagedMuxCloseStateV1 | AppFailureV1 | None = None
        if result is not None:
            if type(result) is not dict:
                raise InvalidAppMessageError()
            if result.get("kind") == "failure":
                fields = _object(result, {"kind", "code"})
                decoded = AppFailureV1(AppErrorCodeV1(_string(fields["code"])))
            else:
                fields = _object(result, {"kind", "operationId", "instanceId", "creationOperationId",
                                          "name", "muxSpaceId", "phase"})
                if fields["kind"] != "close_state":
                    raise InvalidAppMessageError()
                decoded = ManagedMuxCloseStateV1(_string(fields["operationId"]), _string(fields["instanceId"]),
                    _string(fields["creationOperationId"]), _string(fields["name"]), _string(fields["muxSpaceId"]),
                    ManagedMuxClosePhaseV1(_string(fields["phase"])))
        return ManagedMuxCloseResponseV1(_string(value["requestId"]), decoded)
    except (ValueError, TypeError):
        raise InvalidAppMessageError() from None
