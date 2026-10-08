"""Pure bounded namespace initialization witnesses, not IO admission authority.

Only the retained initializer may supply native identity evidence. No
record, including initialized, claims that a service is running or stopped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum

from .contracts import _HEX32, _HEX64, ManagedContractError, _match

MAX_ADMISSION_RECORD_BYTES = 4096
_VERSION = "loushang.managed-namespace/v2"
_FIELDS = {"version", "namespace", "operation", "deployment", "phase", "registryRoot", "database", "registryLock",
           "admissionRoot", "admissionLock"}
FileIdentity = tuple[int, int]


class ManagedInitializationPhaseV1(str, Enum):
    INITIALIZING = "initializing"
    INITIALIZED = "initialized"


@dataclass(frozen=True, slots=True)
class ManagedNamespaceAdmissionRecordV1:
    namespace_key: str
    operation_id: str
    deployment_id: str
    phase: ManagedInitializationPhaseV1
    registry_root_identity: FileIdentity | None = field(default=None, repr=False)
    database_identity: FileIdentity | None = field(default=None, repr=False)
    registry_lock_identity: FileIdentity | None = field(default=None, repr=False)
    admission_root_identity: FileIdentity | None = field(default=None, repr=False)
    admission_lock_identity: FileIdentity | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _match(self.namespace_key, _HEX64)
        _match(self.operation_id, _HEX32)
        _match(self.deployment_id, _HEX32)
        if type(self.phase) is not ManagedInitializationPhaseV1:
            raise ManagedContractError()
        identities = (self.registry_root_identity, self.database_identity, self.registry_lock_identity)
        admission = (self.admission_root_identity, self.admission_lock_identity)
        if self.phase is ManagedInitializationPhaseV1.INITIALIZING:
            if any(value is not None for value in identities):
                raise ManagedContractError()
            if any(value is not None for value in admission):
                for value in admission:
                    _identity(value)
                if len(set(admission)) != 2:
                    raise ManagedContractError()
        else:
            for value in (*identities, *admission):
                _identity(value)
            if len(set((*identities, *admission))) != 5:
                raise ManagedContractError()

    def to_json(self) -> str:
        return json.dumps({
            "version": _VERSION, "namespace": self.namespace_key,
            "operation": self.operation_id, "deployment": self.deployment_id,
            "phase": self.phase.value, "registryRoot": self.registry_root_identity,
            "database": self.database_identity, "registryLock": self.registry_lock_identity,
            "admissionRoot": self.admission_root_identity, "admissionLock": self.admission_lock_identity,
        }, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> ManagedNamespaceAdmissionRecordV1:
        if type(value) is not str or not 1 <= len(value) <= MAX_ADMISSION_RECORD_BYTES:
            raise ManagedContractError()
        try:
            if len(value.encode("utf-8")) > MAX_ADMISSION_RECORD_BYTES:
                raise ManagedContractError()
            data = json.loads(value, object_pairs_hook=_unique)
            if type(data) is not dict or set(data) != _FIELDS or data["version"] != _VERSION:
                raise ManagedContractError()
            return cls(
                data["namespace"], data["operation"], data["deployment"],
                ManagedInitializationPhaseV1(data["phase"]),
                _decoded_identity(data["registryRoot"]), _decoded_identity(data["database"]),
                _decoded_identity(data["registryLock"]),
                _decoded_identity(data["admissionRoot"]), _decoded_identity(data["admissionLock"]),
            )
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise ManagedContractError() from None


def _identity(value: object) -> None:
    if (type(value) is not tuple or len(value) != 2
            or any(type(item) is not int or not 0 <= item < 2**64 for item in value)
            or value[1] == 0):
        raise ManagedContractError()


@dataclass(frozen=True, slots=True)
class ManagedServiceAdmissionRecordV1:
    """Durable fence initialization fact, independent of service generations."""

    service_id: str
    operation_id: str
    phase: ManagedInitializationPhaseV1
    root_identity: FileIdentity | None = field(default=None, repr=False)
    lock_identity: FileIdentity | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _match(self.service_id, _HEX64)
        _match(self.operation_id, _HEX32)
        if type(self.phase) is not ManagedInitializationPhaseV1:
            raise ManagedContractError()
        if self.phase is ManagedInitializationPhaseV1.INITIALIZING:
            if self.root_identity is not None or self.lock_identity is not None:
                raise ManagedContractError()
        else:
            _identity(self.root_identity)
            _identity(self.lock_identity)
            if self.root_identity == self.lock_identity:
                raise ManagedContractError()

    def to_json(self) -> str:
        return json.dumps({"version": "loushang.managed-service-control/v1", "service": self.service_id,
                           "operation": self.operation_id, "phase": self.phase.value,
                           "root": self.root_identity, "lock": self.lock_identity},
                          sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> ManagedServiceAdmissionRecordV1:
        if type(value) is not str or not 1 <= len(value) <= MAX_ADMISSION_RECORD_BYTES:
            raise ManagedContractError()
        try:
            if len(value.encode("utf-8")) > MAX_ADMISSION_RECORD_BYTES:
                raise ManagedContractError()
            data = json.loads(value, object_pairs_hook=_unique)
            if (type(data) is not dict or set(data) != {"version", "service", "operation", "phase", "root", "lock"}
                    or data["version"] != "loushang.managed-service-control/v1"):
                raise ManagedContractError()
            return cls(data["service"], data["operation"], ManagedInitializationPhaseV1(data["phase"]),
                       _decoded_identity(data["root"]), _decoded_identity(data["lock"]))
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise ManagedContractError() from None


def _decoded_identity(value: object) -> FileIdentity | None:
    if value is None:
        return None
    if type(value) is not list or len(value) != 2:
        raise ManagedContractError()
    result = (value[0], value[1])
    _identity(result)
    return result


def _unique(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ManagedContractError()
        result[key] = value
    return result


__all__ = ["ManagedInitializationPhaseV1", "ManagedNamespaceAdmissionRecordV1",
           "ManagedServiceAdmissionRecordV1", "MAX_ADMISSION_RECORD_BYTES"]
