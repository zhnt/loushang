"""Private closed values for the local connection record owner."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256

from .local_auth import LOCAL_PROFILE_V1, LocalAuthenticationV1
from .protocol import APP_PROTOCOL_VERSION, SessionScopeV1
from .protocol.connection_profile import AppConnectionProfileV1

MAX_LOCAL_RECORD_BYTES = 8192
_VERSION = "loushang.appserver.local-record/v1"
_CAPABILITIES = ("named_mux", "text_turns", "approvals")
_DISCOVERY_CAPABILITIES = (*_CAPABILITIES, "session_discovery")
_EXECUTION_CAPABILITIES = (*_CAPABILITIES, "session_execution")
_COMBINED_CAPABILITIES = (*_DISCOVERY_CAPABILITIES, "session_execution")
_ENDPOINT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_STABLE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_HEX = re.compile(r"[0-9a-f]+\Z")


class LocalRecordErrorCodeV1(str, Enum):
    LOCKED = "local_record_locked"
    NOT_FOUND = "local_record_not_found"
    UNAVAILABLE = "local_record_unavailable"
    CORRUPT = "local_record_corrupt"
    CONFLICT = "local_record_conflict"
    CLOSED = "local_record_closed"
    CLEANUP_INCOMPLETE = "local_record_cleanup_incomplete"


class LocalRecordError(RuntimeError):
    def __init__(self, code: LocalRecordErrorCodeV1) -> None:
        if type(code) is not LocalRecordErrorCodeV1:
            raise TypeError("invalid local record error")
        self.code = code
        super().__init__(code.value)


def require_endpoint(value: str) -> None:
    if type(value) is not str or _ENDPOINT.fullmatch(value) is None:
        raise ValueError("invalid local endpoint name")


def _hex(value: object, size: int) -> bool:
    return type(value) is str and len(value) == size and _HEX.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class LocalRecordScopeV1:
    scope: SessionScopeV1
    fingerprint: str

    def __post_init__(self) -> None:
        if type(self.scope) is not SessionScopeV1 or not _hex(self.fingerprint, 64):
            raise ValueError("invalid local record scope")


@dataclass(frozen=True, slots=True, kw_only=True)
class LocalConnectionRecordV1:
    endpoint: str
    application_id: str
    product_id: str
    instance: str
    port: int
    scopes: tuple[LocalRecordScopeV1, ...]
    key: bytes = field(repr=False)
    session_discovery: bool = False
    session_execution: bool = False

    def __post_init__(self) -> None:
        if type(self.session_discovery) is not bool or type(self.session_execution) is not bool:
            raise TypeError("invalid discovery activation")
        require_endpoint(self.endpoint)
        if any(type(value) is not str or _STABLE_ID.fullmatch(value) is None
               for value in (self.application_id, self.product_id)):
            raise ValueError("invalid local record application identity")
        if not _hex(self.instance, 32) or type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("invalid local record endpoint")
        if type(self.key) is not bytes or len(self.key) != 32:
            raise ValueError("invalid local record key")
        if (
            type(self.scopes) is not tuple or not 1 <= len(self.scopes) <= 2
            or any(type(item) is not LocalRecordScopeV1 for item in self.scopes)
            or len({item.scope for item in self.scopes}) != len(self.scopes)
        ):
            raise ValueError("invalid local record scopes")

    @property
    def semantic_profile(self) -> AppConnectionProfileV1:
        if self.session_execution:
            return (AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION if self.session_discovery
                    else AppConnectionProfileV1.LOCAL_EXECUTION)
        return (AppConnectionProfileV1.LOCAL_DISCOVERY if self.session_discovery
                else AppConnectionProfileV1.LOCAL)

    @property
    def authentication(self) -> LocalAuthenticationV1:
        return LocalAuthenticationV1(
            self.instance, sha256(_encode(_public(self))).digest(), self.key
        )


def _public(record: LocalConnectionRecordV1) -> dict[str, object]:
    return {
        "schemaVersion": _VERSION, "profile": LOCAL_PROFILE_V1,
        "protocolVersion": APP_PROTOCOL_VERSION, "endpoint": record.endpoint,
        "applicationId": record.application_id, "productId": record.product_id,
        "instance": record.instance, "port": record.port,
        "scopes": [{"scope": item.scope.value, "fingerprint": item.fingerprint}
                   for item in record.scopes],
        "capabilities": list(
            (_COMBINED_CAPABILITIES if record.session_discovery else _EXECUTION_CAPABILITIES)
            if record.session_execution else
            (_DISCOVERY_CAPABILITIES if record.session_discovery else _CAPABILITIES)
        ),
    }


def _encode(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def encode_connection_record(record: LocalConnectionRecordV1) -> bytes:
    if type(record) is not LocalConnectionRecordV1:
        raise TypeError("invalid local connection record")
    return _encode({**_public(record), "key": record.key.hex()})


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate record field")
        value[key] = item
    return value


def decode_connection_record(payload: bytes) -> LocalConnectionRecordV1:
    try:
        if type(payload) is not bytes or not 1 <= len(payload) <= MAX_LOCAL_RECORD_BYTES:
            raise ValueError
        raw = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs)
        if type(raw) is not dict or set(raw) != {
            "schemaVersion", "profile", "protocolVersion", "endpoint", "applicationId",
            "productId", "instance", "port", "scopes", "capabilities", "key",
        }:
            raise ValueError
        if (
            raw["schemaVersion"] != _VERSION or raw["profile"] != LOCAL_PROFILE_V1
            or raw["protocolVersion"] != APP_PROTOCOL_VERSION
            or raw["capabilities"] not in (
                list(_CAPABILITIES), list(_DISCOVERY_CAPABILITIES),
                list(_EXECUTION_CAPABILITIES), list(_COMBINED_CAPABILITIES),
            )
            or not _hex(raw["key"], 64)
        ):
            raise ValueError
        scopes = raw["scopes"]
        if type(scopes) is not list or not 1 <= len(scopes) <= 2:
            raise ValueError
        if any(type(item) is not dict or set(item) != {"scope", "fingerprint"}
               or type(item["scope"]) is not str for item in scopes):
            raise ValueError
        return LocalConnectionRecordV1(
            endpoint=raw["endpoint"], application_id=raw["applicationId"],
            product_id=raw["productId"], instance=raw["instance"], port=raw["port"],
            key=bytes.fromhex(raw["key"]),
            session_discovery=raw["capabilities"] in (list(_DISCOVERY_CAPABILITIES), list(_COMBINED_CAPABILITIES)),
            session_execution=raw["capabilities"] in (list(_EXECUTION_CAPABILITIES), list(_COMBINED_CAPABILITIES)),
            scopes=tuple(LocalRecordScopeV1(SessionScopeV1(item["scope"]), item["fingerprint"])
                         for item in scopes),
        )
    except (ValueError, TypeError, KeyError, RecursionError):
        raise LocalRecordError(LocalRecordErrorCodeV1.CORRUPT) from None
