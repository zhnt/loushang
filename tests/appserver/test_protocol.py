from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.appserver.protocol import (
    APP_PROTOCOL_VERSION,
    AckV1,
    AppErrorCodeV1,
    AppFailureV1,
    AppOperationV1,
    AppRequestV1,
    AppResponseV1,
    AttachedSessionV1,
    AttachmentEventV1,
    InteractionOutcomeV1,
    InteractionRespondV1,
    InvalidAppMessageError,
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
    SessionEventKindV1,
    SessionEventV1,
    SessionIdentityV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    SessionSnapshotRequestV1,
    SessionSnapshotV1,
    TranscriptRecordKindV1,
    TranscriptRecordV1,
    TurnInterruptV1,
    TurnTextV1,
    decode_event,
    decode_request,
    decode_response,
    encode_event,
    encode_request,
    encode_response,
    operation_names_v1,
)

FINGERPRINT = "a" * 64


def _identity() -> SessionIdentityV1:
    return SessionIdentityV1(
        product_id="coding",
        continuity_id="continuity-1",
        session_id="session-1",
        scope=SessionScopeV1.CWD,
        scope_fingerprint=FINGERPRINT,
    )


def _open_spec(*, resume: bool = False) -> SessionOpenSpecV1:
    return SessionOpenSpecV1(
        product_id="coding",
        continuity_id="continuity-1",
        session_id="session-1" if resume else None,
        scope=SessionScopeV1.CWD,
        scope_fingerprint=FINGERPRINT,
        title="Session one",
    )


def _mux() -> MuxSpaceV1:
    return MuxSpaceV1(
        mux_space_id="mux-1",
        name="dev",
        revision=2,
        members=(
            MuxSpaceMemberV1(
                member_id="member-1",
                session=_identity(),
                title="Session one",
                position=1,
            ),
        ),
    )


def _snapshot() -> SessionSnapshotV1:
    return SessionSnapshotV1(
        identity=_identity(),
        title="Session one",
        cursor=4,
        revision=3,
        running=False,
        records=(
            TranscriptRecordV1(TranscriptRecordKindV1.USER, "hello"),
            TranscriptRecordV1(TranscriptRecordKindV1.ASSISTANT, "hi"),
        ),
    )


def _attachment() -> MuxAttachmentV1:
    mux = _mux()
    return MuxAttachmentV1(
        attachment_id="attachment-1",
        mux_space=mux,
        controller_generation=1,
        sessions=(AttachedSessionV1(mux.members[0], _snapshot()),),
    )


@pytest.mark.parametrize(
    ("operation", "payload"),
    (
        (AppOperationV1.MUX_CREATE, MuxCreateV1("dev")),
        (AppOperationV1.MUX_LIST, MuxListV1()),
        (AppOperationV1.MUX_READ, MuxReadV1(MuxSelectorV1(name="dev"))),
        (AppOperationV1.MUX_ATTACH, MuxAttachV1(MuxSelectorV1(name="dev"))),
        (AppOperationV1.MUX_DETACH, MuxDetachV1("attachment-1", 2)),
        (AppOperationV1.MUX_CLOSE, MuxCloseV1(MuxSelectorV1(name="dev"))),
        (
            AppOperationV1.MEMBER_OPEN,
            MuxMemberOpenV1(MuxSelectorV1(name="dev"), _open_spec()),
        ),
        (
            AppOperationV1.MEMBER_CLOSE,
            MuxMemberCloseV1(MuxSelectorV1(name="dev"), "member-1"),
        ),
        (
            AppOperationV1.SESSION_SNAPSHOT,
            SessionSnapshotRequestV1("attachment-1", 2, "member-1"),
        ),
        (
            AppOperationV1.TURN_START,
            TurnTextV1("attachment-1", 2, "member-1", "hello"),
        ),
        (
            AppOperationV1.TURN_STEER,
            TurnTextV1("attachment-1", 2, "member-1", "change course"),
        ),
        (
            AppOperationV1.TURN_FOLLOW_UP,
            TurnTextV1("attachment-1", 2, "member-1", "then finish"),
        ),
        (
            AppOperationV1.TURN_INTERRUPT,
            TurnInterruptV1("attachment-1", 2, "member-1"),
        ),
        (
            AppOperationV1.INTERACTION_RESPOND,
            InteractionRespondV1(
                "attachment-1",
                2,
                "member-1",
                "interaction-1",
                InteractionOutcomeV1.APPROVE,
            ),
        ),
    ),
)
def test_G11_CONTRACT_STRICT_request_round_trip(
    operation: AppOperationV1,
    payload: object,
) -> None:
    request = AppRequestV1("request-1", operation, payload)  # type: ignore[arg-type]

    assert decode_request(encode_request(request)) == request


@pytest.mark.parametrize(
    "result",
    (
        AckV1(),
        AppFailureV1(AppErrorCodeV1.SNAPSHOT_REQUIRED),
        _mux(),
        MuxListResultV1((_mux(),)),
        _attachment(),
        _snapshot(),
    ),
)
def test_G11_CONTRACT_STRICT_response_round_trip(result: object) -> None:
    response = AppResponseV1("request-1", result)  # type: ignore[arg-type]

    assert decode_response(encode_response(response)) == response


def test_G11_CONTRACT_STRICT_event_round_trip_is_closed() -> None:
    event = AttachmentEventV1(
        "attachment-1",
        "member-1",
        SessionEventV1(
            "session-1",
            5,
            SessionEventKindV1.INTERACTION_REQUESTED,
            "approval required",
            "interaction-1",
        ),
    )

    assert decode_event(encode_event(event)) == event
    raw = json.loads(encode_event(event))
    raw["event"]["hidden"] = True
    with pytest.raises(InvalidAppMessageError):
        decode_event(json.dumps(raw).encode())


@pytest.mark.parametrize(
    "payload",
    (
        b"",
        b"[]",
        b'{"protocolVersion":"loushang.app/v1","requestId":"r","operation":"mux/list","payload":{},"extra":1}',
        b'{"protocolVersion":"loushang.app/v2","requestId":"r","operation":"mux/list","payload":{}}',
        b'{"protocolVersion":"loushang.app/v1","requestId":"r","operation":"unknown","payload":{}}',
        b'{"protocolVersion":"loushang.app/v1","requestId":"r","requestId":"r2","operation":"mux/list","payload":{}}',
        b'{"protocolVersion":"loushang.app/v1","requestId":"r","operation":"mux/list","payload":{"hidden":1}}',
        b'{"protocolVersion":"loushang.app/v1","requestId":"r","operation":"mux/attach","payload":{"selector":{"muxSpaceId":null,"name":"dev"},"mailboxCapacity":true}}',
        b'{"protocolVersion":"loushang.app/v1","requestId":"r","operation":"mux/create","payload":{"name":NaN}}',
    ),
)
def test_G11_CONTRACT_STRICT_rejects_malformed_unknown_and_ambiguous_input(
    payload: bytes,
) -> None:
    with pytest.raises(InvalidAppMessageError):
        decode_request(payload)


def test_G11_MUX_IDENTITY_enforces_domains_and_cardinality() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        MuxSelectorV1()
    with pytest.raises(ValueError, match="exactly one"):
        MuxSelectorV1(mux_space_id="mux-1", name="dev")
    with pytest.raises(ValueError, match="mux name"):
        MuxCreateV1("../escape")
    with pytest.raises(ValueError, match="mux members"):
        replace(_mux(), members=(replace(_mux().members[0], position=2),))
    with pytest.raises(ValueError, match="attachment sessions"):
        replace(_attachment(), sessions=())
    with pytest.raises(TypeError, match="mux selector"):
        MuxReadV1("dev")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="mux selector"):
        MuxCloseV1("dev")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="mux list"):
        MuxListResultV1([_mux()])  # type: ignore[arg-type]


def test_protocol_schema_vocabulary_is_closed_and_complete() -> None:
    assert operation_names_v1() == tuple(item.value for item in AppOperationV1)
    assert APP_PROTOCOL_VERSION == "loushang.app/v1"
    encoded = json.loads(
        encode_request(AppRequestV1("request-1", AppOperationV1.MUX_LIST, MuxListV1()))
    )
    assert set(encoded) == {
        "operation",
        "payload",
        "protocolVersion",
        "requestId",
    }
    schema = json.loads(
        Path(
            "docs/internals/architecture/appserver/app-protocol-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert schema["additionalProperties"] is False
    assert tuple(schema["properties"]["operation"]["enum"]) == (
        operation_names_v1()
    )
    assert schema["properties"]["protocolVersion"]["const"] == (
        APP_PROTOCOL_VERSION
    )
