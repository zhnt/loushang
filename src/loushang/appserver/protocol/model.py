"""Closed client-safe values for the G11 hosted application contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from .errors import AppFailureV1

APP_PROTOCOL_VERSION = "loushang.app/v1"
MAX_TEXT_CHARS = 262_144
MAX_TITLE_CHARS = 256
MAX_MEMBERS = 128
MAX_MUX_SPACES = 256
MAX_SNAPSHOT_RECORDS = 4_096

_STABLE_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,127})\Z")
_OPAQUE_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._~-]{0,511})\Z")
_MUX_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")


def _require_stable_id(value: str, *, field: str) -> None:
    if type(value) is not str or _STABLE_ID.fullmatch(value) is None:
        raise ValueError(f"invalid {field}")


def _require_opaque_id(value: str, *, field: str) -> None:
    if type(value) is not str or _OPAQUE_ID.fullmatch(value) is None:
        raise ValueError(f"invalid {field}")


def _require_positive(value: int, *, field: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"invalid {field}")


def _require_text(value: str, *, field: str, maximum: int, empty: bool) -> None:
    if (
        type(value) is not str
        or len(value) > maximum
        or (not empty and not value.strip())
    ):
        raise ValueError(f"invalid {field}")


class SessionScopeV1(str, Enum):
    CWD = "cwd"
    USER_HOME = "user_home"


class TranscriptRecordKindV1(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    STATUS = "status"
    ERROR = "error"


class SessionEventKindV1(str, Enum):
    TURN_STARTED = "turn_started"
    USER_MESSAGE = "user_message"
    ASSISTANT_DELTA = "assistant_delta"
    ASSISTANT_MESSAGE = "assistant_message"
    STATUS = "status"
    ERROR = "error"
    TURN_COMPLETED = "turn_completed"
    TURN_INTERRUPTED = "turn_interrupted"
    INTERACTION_REQUESTED = "interaction_requested"
    INTERACTION_DISMISSED = "interaction_dismissed"


class InteractionOutcomeV1(str, Enum):
    APPROVE = "approve"
    DENY = "deny"
    CANCEL = "cancel"


class AppOperationV1(str, Enum):
    MUX_CREATE = "mux/create"
    MUX_LIST = "mux/list"
    MUX_READ = "mux/read"
    MUX_ATTACH = "mux/attach"
    MUX_DETACH = "mux/detach"
    MUX_CLOSE = "mux/close"
    MEMBER_OPEN = "mux/member/open"
    MEMBER_CLOSE = "mux/member/close"
    SESSION_SNAPSHOT = "session/snapshot"
    TURN_START = "turn/start"
    TURN_STEER = "turn/steer"
    TURN_FOLLOW_UP = "turn/follow_up"
    TURN_INTERRUPT = "turn/interrupt"
    INTERACTION_RESPOND = "interaction/respond"


@dataclass(frozen=True, slots=True)
class SessionIdentityV1:
    product_id: str
    continuity_id: str
    session_id: str
    scope: SessionScopeV1
    scope_fingerprint: str

    def __post_init__(self) -> None:
        _require_stable_id(self.product_id, field="product_id")
        _require_opaque_id(self.continuity_id, field="continuity_id")
        _require_opaque_id(self.session_id, field="session_id")
        if type(self.scope) is not SessionScopeV1:
            raise ValueError("invalid session scope")
        if (
            type(self.scope_fingerprint) is not str
            or _FINGERPRINT.fullmatch(self.scope_fingerprint) is None
        ):
            raise ValueError("invalid scope_fingerprint")


@dataclass(frozen=True, slots=True)
class SessionOpenSpecV1:
    product_id: str
    continuity_id: str
    scope: SessionScopeV1
    scope_fingerprint: str
    title: str
    session_id: str | None = None

    def __post_init__(self) -> None:
        _require_stable_id(self.product_id, field="product_id")
        _require_opaque_id(self.continuity_id, field="continuity_id")
        if self.session_id is not None:
            _require_opaque_id(self.session_id, field="session_id")
        if type(self.scope) is not SessionScopeV1:
            raise ValueError("invalid session scope")
        if (
            type(self.scope_fingerprint) is not str
            or _FINGERPRINT.fullmatch(self.scope_fingerprint) is None
        ):
            raise ValueError("invalid scope_fingerprint")
        _require_text(
            self.title,
            field="session title",
            maximum=MAX_TITLE_CHARS,
            empty=False,
        )


@dataclass(frozen=True, slots=True)
class TranscriptRecordV1:
    kind: TranscriptRecordKindV1
    text: str

    def __post_init__(self) -> None:
        if type(self.kind) is not TranscriptRecordKindV1:
            raise ValueError("invalid transcript record kind")
        _require_text(self.text, field="transcript text", maximum=MAX_TEXT_CHARS, empty=True)


@dataclass(frozen=True, slots=True)
class SessionSnapshotV1:
    identity: SessionIdentityV1
    title: str
    cursor: int
    revision: int
    running: bool
    records: tuple[TranscriptRecordV1, ...] = ()

    def __post_init__(self) -> None:
        if type(self.identity) is not SessionIdentityV1:
            raise TypeError("invalid session identity")
        _require_text(self.title, field="session title", maximum=MAX_TITLE_CHARS, empty=False)
        if type(self.cursor) is not int or self.cursor < 0:
            raise ValueError("invalid session cursor")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("invalid session revision")
        if type(self.running) is not bool:
            raise TypeError("invalid session running state")
        if (
            not isinstance(self.records, tuple)
            or len(self.records) > MAX_SNAPSHOT_RECORDS
            or any(type(item) is not TranscriptRecordV1 for item in self.records)
        ):
            raise ValueError("invalid session records")


@dataclass(frozen=True, slots=True)
class SessionEventV1:
    session_id: str
    cursor: int
    kind: SessionEventKindV1
    text: str | None = None
    interaction_id: str | None = None

    def __post_init__(self) -> None:
        _require_opaque_id(self.session_id, field="session_id")
        _require_positive(self.cursor, field="event cursor")
        if type(self.kind) is not SessionEventKindV1:
            raise ValueError("invalid session event kind")
        if self.text is not None:
            _require_text(self.text, field="event text", maximum=MAX_TEXT_CHARS, empty=True)
        if self.interaction_id is not None:
            _require_opaque_id(self.interaction_id, field="interaction_id")
        interaction_kind = self.kind in {
            SessionEventKindV1.INTERACTION_REQUESTED,
            SessionEventKindV1.INTERACTION_DISMISSED,
        }
        if interaction_kind != (self.interaction_id is not None):
            raise ValueError("invalid interaction event identity")


@dataclass(frozen=True, slots=True)
class MuxSelectorV1:
    mux_space_id: str | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        if (self.mux_space_id is None) == (self.name is None):
            raise ValueError("exactly one mux selector is required")
        if self.mux_space_id is not None:
            _require_opaque_id(self.mux_space_id, field="mux_space_id")
        if self.name is not None and (
            type(self.name) is not str or _MUX_NAME.fullmatch(self.name) is None
        ):
            raise ValueError("invalid mux name")


@dataclass(frozen=True, slots=True)
class MuxSpaceMemberV1:
    member_id: str
    session: SessionIdentityV1
    title: str
    position: int

    def __post_init__(self) -> None:
        _require_opaque_id(self.member_id, field="member_id")
        if type(self.session) is not SessionIdentityV1:
            raise TypeError("invalid member session")
        _require_text(self.title, field="member title", maximum=MAX_TITLE_CHARS, empty=False)
        _require_positive(self.position, field="member position")


@dataclass(frozen=True, slots=True)
class MuxSpaceV1:
    mux_space_id: str
    name: str
    revision: int
    members: tuple[MuxSpaceMemberV1, ...] = ()

    def __post_init__(self) -> None:
        _require_opaque_id(self.mux_space_id, field="mux_space_id")
        if type(self.name) is not str or _MUX_NAME.fullmatch(self.name) is None:
            raise ValueError("invalid mux name")
        _require_positive(self.revision, field="mux revision")
        if (
            not isinstance(self.members, tuple)
            or len(self.members) > MAX_MEMBERS
            or any(type(item) is not MuxSpaceMemberV1 for item in self.members)
            or tuple(item.position for item in self.members)
            != tuple(range(1, len(self.members) + 1))
            or len({item.member_id for item in self.members}) != len(self.members)
            or len({item.session.session_id for item in self.members})
            != len(self.members)
        ):
            raise ValueError("invalid mux members")


@dataclass(frozen=True, slots=True)
class AttachedSessionV1:
    member: MuxSpaceMemberV1
    snapshot: SessionSnapshotV1

    def __post_init__(self) -> None:
        if type(self.member) is not MuxSpaceMemberV1 or type(
            self.snapshot
        ) is not SessionSnapshotV1:
            raise TypeError("invalid attached session")
        if self.member.session != self.snapshot.identity:
            raise ValueError("attached session identity mismatch")


@dataclass(frozen=True, slots=True)
class MuxAttachmentV1:
    attachment_id: str
    mux_space: MuxSpaceV1
    controller_generation: int
    sessions: tuple[AttachedSessionV1, ...]

    def __post_init__(self) -> None:
        _require_opaque_id(self.attachment_id, field="attachment_id")
        if type(self.mux_space) is not MuxSpaceV1:
            raise TypeError("invalid attachment mux")
        _require_positive(self.controller_generation, field="controller generation")
        if (
            not isinstance(self.sessions, tuple)
            or len(self.sessions) != len(self.mux_space.members)
            or tuple(item.member for item in self.sessions) != self.mux_space.members
        ):
            raise ValueError("invalid attachment sessions")


@dataclass(frozen=True, slots=True)
class AttachmentEventV1:
    attachment_id: str
    member_id: str
    event: SessionEventV1

    def __post_init__(self) -> None:
        _require_opaque_id(self.attachment_id, field="attachment_id")
        _require_opaque_id(self.member_id, field="member_id")
        if type(self.event) is not SessionEventV1:
            raise TypeError("invalid attachment event")


@dataclass(frozen=True, slots=True)
class MuxCreateV1:
    name: str

    def __post_init__(self) -> None:
        MuxSelectorV1(name=self.name)


@dataclass(frozen=True, slots=True)
class MuxListV1:
    pass


@dataclass(frozen=True, slots=True)
class MuxReadV1:
    selector: MuxSelectorV1

    def __post_init__(self) -> None:
        if type(self.selector) is not MuxSelectorV1:
            raise TypeError("invalid mux selector")


@dataclass(frozen=True, slots=True)
class MuxAttachV1:
    selector: MuxSelectorV1
    mailbox_capacity: int = 256

    def __post_init__(self) -> None:
        if type(self.selector) is not MuxSelectorV1:
            raise TypeError("invalid mux selector")
        if type(self.mailbox_capacity) is not int or not 8 <= self.mailbox_capacity <= 4096:
            raise ValueError("invalid mailbox capacity")


@dataclass(frozen=True, slots=True)
class MuxDetachV1:
    attachment_id: str
    controller_generation: int

    def __post_init__(self) -> None:
        _require_opaque_id(self.attachment_id, field="attachment_id")
        _require_positive(self.controller_generation, field="controller generation")


@dataclass(frozen=True, slots=True)
class MuxCloseV1:
    selector: MuxSelectorV1

    def __post_init__(self) -> None:
        if type(self.selector) is not MuxSelectorV1:
            raise TypeError("invalid mux selector")


@dataclass(frozen=True, slots=True)
class MuxMemberOpenV1:
    selector: MuxSelectorV1
    session: SessionOpenSpecV1

    def __post_init__(self) -> None:
        if type(self.selector) is not MuxSelectorV1:
            raise TypeError("invalid mux selector")
        if type(self.session) is not SessionOpenSpecV1:
            raise TypeError("invalid session open specification")


@dataclass(frozen=True, slots=True)
class MuxMemberCloseV1:
    selector: MuxSelectorV1
    member_id: str
    close_session: bool = True

    def __post_init__(self) -> None:
        if type(self.selector) is not MuxSelectorV1:
            raise TypeError("invalid mux selector")
        _require_opaque_id(self.member_id, field="member_id")
        if type(self.close_session) is not bool:
            raise TypeError("invalid close_session")


@dataclass(frozen=True, slots=True)
class SessionSnapshotRequestV1:
    attachment_id: str
    controller_generation: int
    member_id: str

    def __post_init__(self) -> None:
        _require_opaque_id(self.attachment_id, field="attachment_id")
        _require_positive(self.controller_generation, field="controller generation")
        _require_opaque_id(self.member_id, field="member_id")


@dataclass(frozen=True, slots=True)
class TurnTextV1:
    attachment_id: str
    controller_generation: int
    member_id: str
    text: str

    def __post_init__(self) -> None:
        _require_opaque_id(self.attachment_id, field="attachment_id")
        _require_positive(self.controller_generation, field="controller generation")
        _require_opaque_id(self.member_id, field="member_id")
        _require_text(self.text, field="turn text", maximum=MAX_TEXT_CHARS, empty=False)


@dataclass(frozen=True, slots=True)
class TurnInterruptV1:
    attachment_id: str
    controller_generation: int
    member_id: str

    def __post_init__(self) -> None:
        _require_opaque_id(self.attachment_id, field="attachment_id")
        _require_positive(self.controller_generation, field="controller generation")
        _require_opaque_id(self.member_id, field="member_id")


@dataclass(frozen=True, slots=True)
class InteractionRespondV1:
    attachment_id: str
    controller_generation: int
    member_id: str
    interaction_id: str
    outcome: InteractionOutcomeV1

    def __post_init__(self) -> None:
        _require_opaque_id(self.attachment_id, field="attachment_id")
        _require_positive(self.controller_generation, field="controller generation")
        _require_opaque_id(self.member_id, field="member_id")
        _require_opaque_id(self.interaction_id, field="interaction_id")
        if type(self.outcome) is not InteractionOutcomeV1:
            raise ValueError("invalid interaction outcome")


AppRequestPayloadV1: TypeAlias = (
    MuxCreateV1
    | MuxListV1
    | MuxReadV1
    | MuxAttachV1
    | MuxDetachV1
    | MuxCloseV1
    | MuxMemberOpenV1
    | MuxMemberCloseV1
    | SessionSnapshotRequestV1
    | TurnTextV1
    | TurnInterruptV1
    | InteractionRespondV1
)


_PAYLOAD_TYPES: dict[AppOperationV1, type[object]] = {
    AppOperationV1.MUX_CREATE: MuxCreateV1,
    AppOperationV1.MUX_LIST: MuxListV1,
    AppOperationV1.MUX_READ: MuxReadV1,
    AppOperationV1.MUX_ATTACH: MuxAttachV1,
    AppOperationV1.MUX_DETACH: MuxDetachV1,
    AppOperationV1.MUX_CLOSE: MuxCloseV1,
    AppOperationV1.MEMBER_OPEN: MuxMemberOpenV1,
    AppOperationV1.MEMBER_CLOSE: MuxMemberCloseV1,
    AppOperationV1.SESSION_SNAPSHOT: SessionSnapshotRequestV1,
    AppOperationV1.TURN_START: TurnTextV1,
    AppOperationV1.TURN_STEER: TurnTextV1,
    AppOperationV1.TURN_FOLLOW_UP: TurnTextV1,
    AppOperationV1.TURN_INTERRUPT: TurnInterruptV1,
    AppOperationV1.INTERACTION_RESPOND: InteractionRespondV1,
}


@dataclass(frozen=True, slots=True)
class AppRequestV1:
    request_id: str
    operation: AppOperationV1
    payload: AppRequestPayloadV1
    protocol_version: str = APP_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _require_opaque_id(self.request_id, field="request_id")
        if self.protocol_version != APP_PROTOCOL_VERSION:
            raise ValueError("unsupported app protocol version")
        if type(self.operation) is not AppOperationV1:
            raise ValueError("invalid app operation")
        if type(self.payload) is not _PAYLOAD_TYPES[self.operation]:
            raise ValueError("request payload does not match operation")


@dataclass(frozen=True, slots=True)
class AckV1:
    pass


@dataclass(frozen=True, slots=True)
class MuxListResultV1:
    mux_spaces: tuple[MuxSpaceV1, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.mux_spaces, tuple)
            or len(self.mux_spaces) > MAX_MUX_SPACES
            or any(type(item) is not MuxSpaceV1 for item in self.mux_spaces)
        ):
            raise TypeError("invalid mux list")


AppResultPayloadV1: TypeAlias = (
    AckV1
    | AppFailureV1
    | MuxSpaceV1
    | MuxListResultV1
    | MuxAttachmentV1
    | SessionSnapshotV1
)


@dataclass(frozen=True, slots=True)
class AppResponseV1:
    request_id: str
    result: AppResultPayloadV1
    protocol_version: str = APP_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _require_opaque_id(self.request_id, field="request_id")
        if self.protocol_version != APP_PROTOCOL_VERSION:
            raise ValueError("unsupported app protocol version")
        if type(self.result) not in {
            AckV1,
            AppFailureV1,
            MuxSpaceV1,
            MuxListResultV1,
            MuxAttachmentV1,
            SessionSnapshotV1,
        }:
            raise TypeError("invalid app result")


__all__ = [
    "APP_PROTOCOL_VERSION",
    "MAX_MEMBERS",
    "MAX_MUX_SPACES",
    "AckV1",
    "AppOperationV1",
    "AppRequestPayloadV1",
    "AppRequestV1",
    "AppResponseV1",
    "AppResultPayloadV1",
    "AttachedSessionV1",
    "AttachmentEventV1",
    "InteractionOutcomeV1",
    "InteractionRespondV1",
    "MuxAttachV1",
    "MuxAttachmentV1",
    "MuxCloseV1",
    "MuxCreateV1",
    "MuxDetachV1",
    "MuxListResultV1",
    "MuxListV1",
    "MuxMemberCloseV1",
    "MuxMemberOpenV1",
    "MuxReadV1",
    "MuxSelectorV1",
    "MuxSpaceMemberV1",
    "MuxSpaceV1",
    "SessionEventKindV1",
    "SessionEventV1",
    "SessionIdentityV1",
    "SessionOpenSpecV1",
    "SessionScopeV1",
    "SessionSnapshotRequestV1",
    "SessionSnapshotV1",
    "TranscriptRecordKindV1",
    "TranscriptRecordV1",
    "TurnInterruptV1",
    "TurnTextV1",
]
