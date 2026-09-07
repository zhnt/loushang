"""Strict JSON codec for the closed G11 request and response algebra."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from enum import Enum
from typing import TypeVar, cast

from .errors import InvalidAppMessageError
from .model import (
    APP_PROTOCOL_VERSION,
    AckV1,
    AppOperationV1,
    AppRequestV1,
    AppResponseV1,
    AttachedSessionV1,
    InteractionOutcomeV1,
    InteractionRespondV1,
    MuxAttachmentV1,
    MuxAttachV1,
    MuxCloseV1,
    MuxCreateV1,
    MuxDetachV1,
    MuxListResultV1,
    MuxListV1,
    MuxMemberCloseV1,
    MuxMemberOpenV1,
    MuxReadV1,
    MuxSelectorV1,
    MuxSpaceMemberV1,
    MuxSpaceV1,
    SessionIdentityV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    SessionSnapshotRequestV1,
    SessionSnapshotV1,
    TranscriptRecordKindV1,
    TranscriptRecordV1,
    TurnInterruptV1,
    TurnTextV1,
)

MAX_MESSAGE_BYTES = 1_048_576
_T = TypeVar("_T")
_EnumT = TypeVar("_EnumT", bound=Enum)
_Object = dict[str, object]


def _pairs(pairs: list[tuple[str, object]]) -> _Object:
    value: _Object = {}
    for key, item in pairs:
        if key in value:
            raise InvalidAppMessageError()
        value[key] = item
    return value


def _loads(payload: bytes) -> _Object:
    if type(payload) is not bytes or not payload or len(payload) > MAX_MESSAGE_BYTES:
        raise InvalidAppMessageError()
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        raise InvalidAppMessageError() from None
    if type(value) is not dict:
        raise InvalidAppMessageError()
    return cast(_Object, value)


def _dumps(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _object(value: object, fields: set[str]) -> _Object:
    if type(value) is not dict or set(value) != fields:
        raise InvalidAppMessageError()
    return cast(_Object, value)


def _string(value: object) -> str:
    if type(value) is not str:
        raise InvalidAppMessageError()
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise InvalidAppMessageError()
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise InvalidAppMessageError()
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _enum(enum_type: type[_EnumT], value: object) -> _EnumT:
    try:
        return enum_type(_string(value))
    except (TypeError, ValueError):
        raise InvalidAppMessageError() from None


def _construct(factory: Callable[..., _T], **values: object) -> _T:
    try:
        return factory(**values)
    except (TypeError, ValueError):
        raise InvalidAppMessageError() from None


def encode_request(request: AppRequestV1) -> bytes:
    if type(request) is not AppRequestV1:
        raise TypeError("request must be AppRequestV1")
    return _dumps(
        {
            "operation": request.operation.value,
            "payload": _encode_request_payload(request),
            "protocolVersion": request.protocol_version,
            "requestId": request.request_id,
        }
    )


def decode_request(payload: bytes) -> AppRequestV1:
    root = _object(
        _loads(payload),
        {"operation", "payload", "protocolVersion", "requestId"},
    )
    if root["protocolVersion"] != APP_PROTOCOL_VERSION:
        raise InvalidAppMessageError()
    operation = _enum(AppOperationV1, root["operation"])
    request_payload = _decode_request_payload(operation, root["payload"])
    return _construct(
        AppRequestV1,
        request_id=_string(root["requestId"]),
        operation=operation,
        payload=request_payload,
    )


def encode_response(response: AppResponseV1) -> bytes:
    if type(response) is not AppResponseV1:
        raise TypeError("response must be AppResponseV1")
    result = response.result
    if type(result) is AckV1:
        result_type, value = "ack", {}
    elif type(result) is MuxSpaceV1:
        result_type, value = "mux", _encode_mux(result)
    elif type(result) is MuxListResultV1:
        result_type, value = "muxList", {
            "muxSpaces": [_encode_mux(item) for item in result.mux_spaces]
        }
    elif type(result) is MuxAttachmentV1:
        result_type, value = "attachment", _encode_attachment(result)
    elif type(result) is SessionSnapshotV1:
        result_type, value = "snapshot", _encode_snapshot(result)
    else:
        raise TypeError("unsupported response result")
    return _dumps(
        {
            "protocolVersion": response.protocol_version,
            "requestId": response.request_id,
            "result": value,
            "resultType": result_type,
        }
    )


def decode_response(payload: bytes) -> AppResponseV1:
    root = _object(
        _loads(payload),
        {"protocolVersion", "requestId", "result", "resultType"},
    )
    if root["protocolVersion"] != APP_PROTOCOL_VERSION:
        raise InvalidAppMessageError()
    result_type = _string(root["resultType"])
    raw = root["result"]
    if result_type == "ack":
        _object(raw, set())
        result: object = AckV1()
    elif result_type == "mux":
        result = _decode_mux(raw)
    elif result_type == "muxList":
        value = _object(raw, {"muxSpaces"})
        muxes = value["muxSpaces"]
        if type(muxes) is not list:
            raise InvalidAppMessageError()
        result = _construct(
            MuxListResultV1,
            mux_spaces=tuple(_decode_mux(item) for item in muxes),
        )
    elif result_type == "attachment":
        result = _decode_attachment(raw)
    elif result_type == "snapshot":
        result = _decode_snapshot(raw)
    else:
        raise InvalidAppMessageError()
    return _construct(
        AppResponseV1,
        request_id=_string(root["requestId"]),
        result=result,
    )


def _encode_request_payload(request: AppRequestV1) -> _Object:
    payload = request.payload
    operation = request.operation
    if operation is AppOperationV1.MUX_CREATE:
        return {"name": cast(MuxCreateV1, payload).name}
    if operation is AppOperationV1.MUX_LIST:
        return {}
    if operation in {AppOperationV1.MUX_READ, AppOperationV1.MUX_CLOSE}:
        return {"selector": _encode_selector(cast(MuxReadV1 | MuxCloseV1, payload).selector)}
    if operation is AppOperationV1.MUX_ATTACH:
        attach_value = cast(MuxAttachV1, payload)
        return {
            "mailboxCapacity": attach_value.mailbox_capacity,
            "selector": _encode_selector(attach_value.selector),
        }
    if operation is AppOperationV1.MUX_DETACH:
        detach_value = cast(MuxDetachV1, payload)
        return {
            "attachmentId": detach_value.attachment_id,
            "controllerGeneration": detach_value.controller_generation,
        }
    if operation is AppOperationV1.MEMBER_OPEN:
        open_value = cast(MuxMemberOpenV1, payload)
        return {
            "selector": _encode_selector(open_value.selector),
            "session": _encode_open_spec(open_value.session),
        }
    if operation is AppOperationV1.MEMBER_CLOSE:
        close_value = cast(MuxMemberCloseV1, payload)
        return {
            "closeSession": close_value.close_session,
            "memberId": close_value.member_id,
            "selector": _encode_selector(close_value.selector),
        }
    if operation is AppOperationV1.SESSION_SNAPSHOT:
        return _encode_member_operation(cast(SessionSnapshotRequestV1, payload))
    if operation in {
        AppOperationV1.TURN_START,
        AppOperationV1.TURN_STEER,
        AppOperationV1.TURN_FOLLOW_UP,
    }:
        text_value = cast(TurnTextV1, payload)
        return {**_encode_member_operation(text_value), "text": text_value.text}
    if operation is AppOperationV1.TURN_INTERRUPT:
        return _encode_member_operation(cast(TurnInterruptV1, payload))
    if operation is AppOperationV1.INTERACTION_RESPOND:
        interaction_value = cast(InteractionRespondV1, payload)
        return {
            **_encode_member_operation(interaction_value),
            "interactionId": interaction_value.interaction_id,
            "outcome": interaction_value.outcome.value,
        }
    raise TypeError("unsupported request payload")


def _decode_request_payload(operation: AppOperationV1, raw: object) -> object:
    if operation is AppOperationV1.MUX_CREATE:
        value = _object(raw, {"name"})
        return _construct(MuxCreateV1, name=_string(value["name"]))
    if operation is AppOperationV1.MUX_LIST:
        _object(raw, set())
        return MuxListV1()
    if operation in {AppOperationV1.MUX_READ, AppOperationV1.MUX_CLOSE}:
        value = _object(raw, {"selector"})
        factory = MuxReadV1 if operation is AppOperationV1.MUX_READ else MuxCloseV1
        return _construct(factory, selector=_decode_selector(value["selector"]))
    if operation is AppOperationV1.MUX_ATTACH:
        value = _object(raw, {"mailboxCapacity", "selector"})
        return _construct(
            MuxAttachV1,
            selector=_decode_selector(value["selector"]),
            mailbox_capacity=_integer(value["mailboxCapacity"]),
        )
    if operation is AppOperationV1.MUX_DETACH:
        value = _object(raw, {"attachmentId", "controllerGeneration"})
        return _construct(
            MuxDetachV1,
            attachment_id=_string(value["attachmentId"]),
            controller_generation=_integer(value["controllerGeneration"]),
        )
    if operation is AppOperationV1.MEMBER_OPEN:
        value = _object(raw, {"selector", "session"})
        return _construct(
            MuxMemberOpenV1,
            selector=_decode_selector(value["selector"]),
            session=_decode_open_spec(value["session"]),
        )
    if operation is AppOperationV1.MEMBER_CLOSE:
        value = _object(raw, {"closeSession", "memberId", "selector"})
        return _construct(
            MuxMemberCloseV1,
            selector=_decode_selector(value["selector"]),
            member_id=_string(value["memberId"]),
            close_session=_boolean(value["closeSession"]),
        )
    if operation is AppOperationV1.SESSION_SNAPSHOT:
        return _decode_member_operation(SessionSnapshotRequestV1, raw, set())
    if operation in {
        AppOperationV1.TURN_START,
        AppOperationV1.TURN_STEER,
        AppOperationV1.TURN_FOLLOW_UP,
    }:
        return _decode_member_operation(TurnTextV1, raw, {"text"})
    if operation is AppOperationV1.TURN_INTERRUPT:
        return _decode_member_operation(TurnInterruptV1, raw, set())
    if operation is AppOperationV1.INTERACTION_RESPOND:
        value = _object(
            raw,
            {
                "attachmentId",
                "controllerGeneration",
                "interactionId",
                "memberId",
                "outcome",
            },
        )
        return _construct(
            InteractionRespondV1,
            attachment_id=_string(value["attachmentId"]),
            controller_generation=_integer(value["controllerGeneration"]),
            member_id=_string(value["memberId"]),
            interaction_id=_string(value["interactionId"]),
            outcome=_enum(InteractionOutcomeV1, value["outcome"]),
        )
    raise InvalidAppMessageError()


def _decode_member_operation(
    factory: Callable[..., _T],
    raw: object,
    extra_fields: set[str],
) -> _T:
    value = _object(
        raw,
        {"attachmentId", "controllerGeneration", "memberId", *extra_fields},
    )
    arguments: dict[str, object] = {
        "attachment_id": _string(value["attachmentId"]),
        "controller_generation": _integer(value["controllerGeneration"]),
        "member_id": _string(value["memberId"]),
    }
    if "text" in extra_fields:
        arguments["text"] = _string(value["text"])
    return _construct(factory, **arguments)


def _encode_member_operation(value: object) -> _Object:
    return {
        "attachmentId": cast(str, getattr(value, "attachment_id")),
        "controllerGeneration": cast(int, getattr(value, "controller_generation")),
        "memberId": cast(str, getattr(value, "member_id")),
    }


def _encode_selector(value: MuxSelectorV1) -> _Object:
    return {"muxSpaceId": value.mux_space_id, "name": value.name}


def _decode_selector(raw: object) -> MuxSelectorV1:
    value = _object(raw, {"muxSpaceId", "name"})
    return _construct(
        MuxSelectorV1,
        mux_space_id=_optional_string(value["muxSpaceId"]),
        name=_optional_string(value["name"]),
    )


def _encode_identity(value: SessionIdentityV1) -> _Object:
    return {
        "continuityId": value.continuity_id,
        "productId": value.product_id,
        "scope": value.scope.value,
        "scopeFingerprint": value.scope_fingerprint,
        "sessionId": value.session_id,
    }


def _decode_identity(raw: object) -> SessionIdentityV1:
    value = _object(
        raw,
        {"continuityId", "productId", "scope", "scopeFingerprint", "sessionId"},
    )
    return _construct(
        SessionIdentityV1,
        product_id=_string(value["productId"]),
        continuity_id=_string(value["continuityId"]),
        session_id=_string(value["sessionId"]),
        scope=_enum(SessionScopeV1, value["scope"]),
        scope_fingerprint=_string(value["scopeFingerprint"]),
    )


def _encode_open_spec(value: SessionOpenSpecV1) -> _Object:
    return {
        "continuityId": value.continuity_id,
        "productId": value.product_id,
        "scope": value.scope.value,
        "scopeFingerprint": value.scope_fingerprint,
        "sessionId": value.session_id,
        "title": value.title,
    }


def _decode_open_spec(raw: object) -> SessionOpenSpecV1:
    value = _object(
        raw,
        {
            "continuityId",
            "productId",
            "scope",
            "scopeFingerprint",
            "sessionId",
            "title",
        },
    )
    return _construct(
        SessionOpenSpecV1,
        product_id=_string(value["productId"]),
        continuity_id=_string(value["continuityId"]),
        scope=_enum(SessionScopeV1, value["scope"]),
        scope_fingerprint=_string(value["scopeFingerprint"]),
        title=_string(value["title"]),
        session_id=_optional_string(value["sessionId"]),
    )


def _encode_member(value: MuxSpaceMemberV1) -> _Object:
    return {
        "memberId": value.member_id,
        "position": value.position,
        "session": _encode_identity(value.session),
        "title": value.title,
    }


def _decode_member(raw: object) -> MuxSpaceMemberV1:
    value = _object(raw, {"memberId", "position", "session", "title"})
    return _construct(
        MuxSpaceMemberV1,
        member_id=_string(value["memberId"]),
        session=_decode_identity(value["session"]),
        title=_string(value["title"]),
        position=_integer(value["position"]),
    )


def _encode_mux(value: MuxSpaceV1) -> _Object:
    return {
        "members": [_encode_member(item) for item in value.members],
        "muxSpaceId": value.mux_space_id,
        "name": value.name,
        "revision": value.revision,
    }


def _decode_mux(raw: object) -> MuxSpaceV1:
    value = _object(raw, {"members", "muxSpaceId", "name", "revision"})
    members = value["members"]
    if type(members) is not list:
        raise InvalidAppMessageError()
    return _construct(
        MuxSpaceV1,
        mux_space_id=_string(value["muxSpaceId"]),
        name=_string(value["name"]),
        revision=_integer(value["revision"]),
        members=tuple(_decode_member(item) for item in members),
    )


def _encode_snapshot(value: SessionSnapshotV1) -> _Object:
    return {
        "cursor": value.cursor,
        "identity": _encode_identity(value.identity),
        "records": [
            {"kind": item.kind.value, "text": item.text} for item in value.records
        ],
        "revision": value.revision,
        "running": value.running,
        "title": value.title,
    }


def _decode_snapshot(raw: object) -> SessionSnapshotV1:
    value = _object(
        raw,
        {"cursor", "identity", "records", "revision", "running", "title"},
    )
    records = value["records"]
    if type(records) is not list:
        raise InvalidAppMessageError()
    decoded_records: list[TranscriptRecordV1] = []
    for raw_record in records:
        record = _object(raw_record, {"kind", "text"})
        decoded_records.append(
            _construct(
                TranscriptRecordV1,
                kind=_enum(TranscriptRecordKindV1, record["kind"]),
                text=_string(record["text"]),
            )
        )
    return _construct(
        SessionSnapshotV1,
        identity=_decode_identity(value["identity"]),
        title=_string(value["title"]),
        cursor=_integer(value["cursor"]),
        revision=_integer(value["revision"]),
        running=_boolean(value["running"]),
        records=tuple(decoded_records),
    )


def _encode_attachment(value: MuxAttachmentV1) -> _Object:
    return {
        "attachmentId": value.attachment_id,
        "controllerGeneration": value.controller_generation,
        "muxSpace": _encode_mux(value.mux_space),
        "sessions": [
            {
                "member": _encode_member(item.member),
                "snapshot": _encode_snapshot(item.snapshot),
            }
            for item in value.sessions
        ],
    }


def _decode_attachment(raw: object) -> MuxAttachmentV1:
    value = _object(
        raw,
        {"attachmentId", "controllerGeneration", "muxSpace", "sessions"},
    )
    sessions = value["sessions"]
    if type(sessions) is not list:
        raise InvalidAppMessageError()
    decoded: list[AttachedSessionV1] = []
    for raw_session in sessions:
        item = _object(raw_session, {"member", "snapshot"})
        decoded.append(
            _construct(
                AttachedSessionV1,
                member=_decode_member(item["member"]),
                snapshot=_decode_snapshot(item["snapshot"]),
            )
        )
    return _construct(
        MuxAttachmentV1,
        attachment_id=_string(value["attachmentId"]),
        mux_space=_decode_mux(value["muxSpace"]),
        controller_generation=_integer(value["controllerGeneration"]),
        sessions=tuple(decoded),
    )


def reject_non_finite_number(value: float) -> None:
    """Schema/conformance helper retained for direct decoder tests."""

    if not math.isfinite(value):
        raise InvalidAppMessageError()


__all__ = [
    "MAX_MESSAGE_BYTES",
    "decode_request",
    "decode_response",
    "encode_request",
    "encode_response",
]
