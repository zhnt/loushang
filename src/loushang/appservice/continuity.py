"""Durable AppService coordination records and store ports for G13."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, cast

from loushang.appserver.protocol import (
    MAX_MEMBERS,
    MAX_MUX_SPACES,
    SessionIdentityV1,
    SessionScopeV1,
)

APPLICATION_CONTINUITY_VERSION = "loushang.appservice.continuity/v1"
MAX_CONTINUITY_RECORD_BYTES = 1_048_576
MAX_APPLICATION_RECORDS = 256

_STABLE_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,127})\Z")
_OPAQUE_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._~-]{0,511})\Z")
_MUX_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_Object = dict[str, object]


class ApplicationContinuityErrorCodeV1(str, Enum):
    """Stable private-storage failures without filesystem detail."""

    LOCKED = "continuity_locked"
    CONFLICT = "continuity_conflict"
    CORRUPT = "continuity_corrupt"
    UNAVAILABLE = "continuity_unavailable"
    CLOSED = "continuity_closed"


class ApplicationContinuityError(RuntimeError):
    """Bounded G13 continuity error."""

    def __init__(self, code: ApplicationContinuityErrorCodeV1) -> None:
        if type(code) is not ApplicationContinuityErrorCodeV1:
            raise TypeError("invalid continuity error code")
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class MuxMemberContinuityV1:
    """One stable MuxSpace membership record."""

    member_id: str
    title: str
    position: int
    session: SessionIdentityV1

    def __post_init__(self) -> None:
        _require_opaque_id(self.member_id, "member identity")
        _require_title(self.title)
        _require_positive(self.position, "member position")
        if type(self.session) is not SessionIdentityV1:
            raise TypeError("invalid continuity Session identity")


@dataclass(frozen=True, slots=True)
class MuxSpaceContinuityV1:
    """One durable named coordination aggregate."""

    mux_space_id: str
    name: str
    revision: int
    members: tuple[MuxMemberContinuityV1, ...] = ()

    def __post_init__(self) -> None:
        _require_opaque_id(self.mux_space_id, "MuxSpace identity")
        if type(self.name) is not str or _MUX_NAME.fullmatch(self.name) is None:
            raise ValueError("invalid continuity MuxSpace name")
        _require_positive(self.revision, "MuxSpace revision")
        if (
            not isinstance(self.members, tuple)
            or len(self.members) > MAX_MEMBERS
            or any(type(item) is not MuxMemberContinuityV1 for item in self.members)
            or tuple(item.position for item in self.members)
            != tuple(range(1, len(self.members) + 1))
            or len({item.member_id for item in self.members}) != len(self.members)
            or len({item.session.session_id for item in self.members})
            != len(self.members)
        ):
            raise ValueError("invalid continuity MuxSpace members")


@dataclass(frozen=True, slots=True)
class ApplicationContinuityRecordV1:
    """Complete desired AppService coordination state for one application."""

    application_id: str
    product_id: str
    record_revision: int
    mux_spaces: tuple[MuxSpaceContinuityV1, ...] = ()
    contract_version: str = APPLICATION_CONTINUITY_VERSION

    def __post_init__(self) -> None:
        _require_stable_id(self.application_id, "application identity")
        _require_stable_id(self.product_id, "Product identity")
        _require_positive(self.record_revision, "record revision")
        if self.contract_version != APPLICATION_CONTINUITY_VERSION:
            raise ValueError("unsupported continuity record")
        if (
            not isinstance(self.mux_spaces, tuple)
            or len(self.mux_spaces) > MAX_MUX_SPACES
            or any(type(item) is not MuxSpaceContinuityV1 for item in self.mux_spaces)
            or len({item.mux_space_id for item in self.mux_spaces})
            != len(self.mux_spaces)
            or len({item.name for item in self.mux_spaces}) != len(self.mux_spaces)
        ):
            raise ValueError("invalid continuity MuxSpace registry")
        sessions = tuple(
            member.session.session_id
            for mux in self.mux_spaces
            for member in mux.members
        )
        if len(sessions) != len(set(sessions)):
            raise ValueError("continuity Session belongs to several MuxSpaces")
        if any(
            member.session.product_id != self.product_id
            for mux in self.mux_spaces
            for member in mux.members
        ):
            raise ValueError("continuity Product identity mismatch")


@dataclass(frozen=True, slots=True)
class ApplicationContinuitySummaryV1:
    """Bounded inert listing fact; never service-liveness evidence."""

    application_id: str
    product_id: str
    record_revision: int
    mux_space_count: int
    session_count: int

    def __post_init__(self) -> None:
        _require_stable_id(self.application_id, "application identity")
        _require_stable_id(self.product_id, "Product identity")
        _require_positive(self.record_revision, "record revision")
        if (
            type(self.mux_space_count) is not int
            or not 0 <= self.mux_space_count <= MAX_MUX_SPACES
            or type(self.session_count) is not int
            or not 0 <= self.session_count <= MAX_MUX_SPACES * MAX_MEMBERS
        ):
            raise ValueError("invalid continuity summary cardinality")


class ApplicationContinuityLeaseV1(Protocol):
    """Exclusive exact-application record authority held for one runtime."""

    @property
    def application_id(self) -> str: ...

    @property
    def owner_epoch(self) -> str: ...

    async def load(self) -> ApplicationContinuityRecordV1 | None: ...

    async def commit(
        self,
        *,
        expected_revision: int | None,
        record: ApplicationContinuityRecordV1,
    ) -> None: ...

    async def delete(self, *, expected_revision: int) -> None: ...

    async def close(self) -> None: ...


class ApplicationContinuityStoreV1(Protocol):
    """Store boundary; callers never infer liveness from its records."""

    async def acquire(
        self,
        *,
        application_id: str,
        owner_epoch: str,
    ) -> ApplicationContinuityLeaseV1: ...

    async def list_applications(
        self,
        *,
        limit: int = MAX_APPLICATION_RECORDS,
    ) -> tuple[ApplicationContinuitySummaryV1, ...]: ...


def encode_application_continuity_record(
    record: ApplicationContinuityRecordV1,
) -> bytes:
    """Encode one exact canonical G13 record."""

    if type(record) is not ApplicationContinuityRecordV1:
        raise TypeError("invalid continuity record")
    payload = {
        "applicationId": record.application_id,
        "contractVersion": record.contract_version,
        "muxSpaces": [_encode_mux(mux) for mux in record.mux_spaces],
        "productId": record.product_id,
        "recordRevision": record.record_revision,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > MAX_CONTINUITY_RECORD_BYTES:
        raise ApplicationContinuityError(ApplicationContinuityErrorCodeV1.CORRUPT)
    return encoded


def decode_application_continuity_record(
    payload: bytes,
) -> ApplicationContinuityRecordV1:
    """Strictly decode one bounded exact G13 record."""

    if (
        type(payload) is not bytes
        or not payload
        or len(payload) > MAX_CONTINUITY_RECORD_BYTES
    ):
        raise ApplicationContinuityError(ApplicationContinuityErrorCodeV1.CORRUPT)
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        root = _object(
            value,
            {"applicationId", "contractVersion", "muxSpaces", "productId", "recordRevision"},
        )
        mux_values = _array(root["muxSpaces"], maximum=MAX_MUX_SPACES)
        return ApplicationContinuityRecordV1(
            application_id=_string(root["applicationId"]),
            product_id=_string(root["productId"]),
            record_revision=_integer(root["recordRevision"]),
            mux_spaces=tuple(_decode_mux(item) for item in mux_values),
            contract_version=_string(root["contractVersion"]),
        )
    except ApplicationContinuityError:
        raise
    except (UnicodeDecodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise ApplicationContinuityError(
            ApplicationContinuityErrorCodeV1.CORRUPT
        ) from None


def continuity_summary(
    record: ApplicationContinuityRecordV1,
) -> ApplicationContinuitySummaryV1:
    if type(record) is not ApplicationContinuityRecordV1:
        raise TypeError("invalid continuity record")
    return ApplicationContinuitySummaryV1(
        application_id=record.application_id,
        product_id=record.product_id,
        record_revision=record.record_revision,
        mux_space_count=len(record.mux_spaces),
        session_count=sum(len(mux.members) for mux in record.mux_spaces),
    )


def require_application_id(value: str) -> str:
    _require_stable_id(value, "application identity")
    return value


def require_owner_epoch(value: str) -> str:
    _require_opaque_id(value, "continuity owner epoch")
    return value


def require_exact_continuity_root(value: Path) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        raise ValueError("continuity root must be an exact absolute Path")
    return value


def _encode_mux(mux: MuxSpaceContinuityV1) -> _Object:
    return {
        "members": [_encode_member(member) for member in mux.members],
        "muxSpaceId": mux.mux_space_id,
        "name": mux.name,
        "revision": mux.revision,
    }


def _encode_member(member: MuxMemberContinuityV1) -> _Object:
    session = member.session
    return {
        "memberId": member.member_id,
        "position": member.position,
        "session": {
            "continuityId": session.continuity_id,
            "productId": session.product_id,
            "scope": session.scope.value,
            "scopeFingerprint": session.scope_fingerprint,
            "sessionId": session.session_id,
        },
        "title": member.title,
    }


def _decode_mux(value: object) -> MuxSpaceContinuityV1:
    raw = _object(value, {"members", "muxSpaceId", "name", "revision"})
    members = _array(raw["members"], maximum=MAX_MEMBERS)
    return MuxSpaceContinuityV1(
        mux_space_id=_string(raw["muxSpaceId"]),
        name=_string(raw["name"]),
        revision=_integer(raw["revision"]),
        members=tuple(_decode_member(item) for item in members),
    )


def _decode_member(value: object) -> MuxMemberContinuityV1:
    raw = _object(value, {"memberId", "position", "session", "title"})
    session = _object(
        raw["session"],
        {"continuityId", "productId", "scope", "scopeFingerprint", "sessionId"},
    )
    return MuxMemberContinuityV1(
        member_id=_string(raw["memberId"]),
        title=_string(raw["title"]),
        position=_integer(raw["position"]),
        session=SessionIdentityV1(
            product_id=_string(session["productId"]),
            continuity_id=_string(session["continuityId"]),
            session_id=_string(session["sessionId"]),
            scope=SessionScopeV1(_string(session["scope"])),
            scope_fingerprint=_string(session["scopeFingerprint"]),
        ),
    )


def _pairs(pairs: list[tuple[str, object]]) -> _Object:
    value: _Object = {}
    for key, item in pairs:
        if key in value:
            raise ApplicationContinuityError(
                ApplicationContinuityErrorCodeV1.CORRUPT
            )
        value[key] = item
    return value


def _object(value: object, fields: set[str]) -> _Object:
    if type(value) is not dict or set(value) != fields:
        raise ApplicationContinuityError(ApplicationContinuityErrorCodeV1.CORRUPT)
    return cast(_Object, value)


def _array(value: object, *, maximum: int) -> list[object]:
    if type(value) is not list or len(value) > maximum:
        raise ApplicationContinuityError(ApplicationContinuityErrorCodeV1.CORRUPT)
    return cast(list[object], value)


def _string(value: object) -> str:
    if type(value) is not str:
        raise ApplicationContinuityError(ApplicationContinuityErrorCodeV1.CORRUPT)
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ApplicationContinuityError(ApplicationContinuityErrorCodeV1.CORRUPT)
    return value


def _require_stable_id(value: str, field: str) -> None:
    if type(value) is not str or _STABLE_ID.fullmatch(value) is None:
        raise ValueError(f"invalid {field}")


def _require_opaque_id(value: str, field: str) -> None:
    if type(value) is not str or _OPAQUE_ID.fullmatch(value) is None:
        raise ValueError(f"invalid {field}")


def _require_title(value: str) -> None:
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise ValueError("invalid continuity member title")


def _require_positive(value: int, field: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"invalid {field}")


__all__ = [
    "APPLICATION_CONTINUITY_VERSION",
    "MAX_APPLICATION_RECORDS",
    "MAX_CONTINUITY_RECORD_BYTES",
    "ApplicationContinuityError",
    "ApplicationContinuityErrorCodeV1",
    "ApplicationContinuityLeaseV1",
    "ApplicationContinuityRecordV1",
    "ApplicationContinuityStoreV1",
    "ApplicationContinuitySummaryV1",
    "MuxMemberContinuityV1",
    "MuxSpaceContinuityV1",
    "continuity_summary",
    "decode_application_continuity_record",
    "encode_application_continuity_record",
    "require_application_id",
    "require_exact_continuity_root",
    "require_owner_epoch",
]
