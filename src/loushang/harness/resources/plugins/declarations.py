from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Literal, cast

PLUGIN_CONTRIBUTION_INDEX_VERSION = 1
PLUGIN_DECLARATION_IR_VERSION = 1

PluginContributionKind = Literal["capability_provider"]
PluginExecutionModel = Literal["in_process"]

_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
_SYMBOL = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")


@dataclass(frozen=True, slots=True)
class PluginContributionReservation:
    """Inert security envelope reserving one future declaration identity."""

    contribution_id: str
    kind: PluginContributionKind
    owner: str
    entrypoint: str
    execution_model: PluginExecutionModel
    requested_authorities: tuple[str, ...]
    configuration: Mapping[str, object] = field(default_factory=dict)
    required: bool = True

    def __post_init__(self) -> None:
        _require_identifier(self.contribution_id, name="contribution id")
        _require_identifier(self.owner, name="contribution owner")
        if self.kind != "capability_provider":
            raise ValueError("Unsupported Plugin contribution kind")
        if self.execution_model != "in_process":
            raise ValueError("Unsupported Plugin execution model")
        _entrypoint_path_and_symbol(self.entrypoint)
        if any(not isinstance(item, str) for item in self.requested_authorities):
            raise TypeError("Plugin requested authorities must be strings")
        authorities = tuple(sorted(self.requested_authorities))
        if len(authorities) != len(set(authorities)):
            raise ValueError("Plugin requested authorities must be unique")
        for authority in authorities:
            _require_identifier(authority, name="requested authority")
        object.__setattr__(self, "requested_authorities", authorities)
        object.__setattr__(self, "configuration", _freeze_json_mapping(self.configuration))
        if not isinstance(self.required, bool):
            raise TypeError("Plugin contribution required must be a boolean")

    @property
    def entrypoint_path(self) -> PurePosixPath:
        path, _ = _entrypoint_path_and_symbol(self.entrypoint)
        return path

    @property
    def fingerprint(self) -> str:
        return _document_digest(self.to_dict())

    @property
    def configuration_fingerprint(self) -> str:
        return _document_digest(dict(self.configuration))

    def to_dict(self) -> dict[str, object]:
        return {
            "configuration": _thaw_json(self.configuration),
            "entrypoint": self.entrypoint,
            "executionModel": self.execution_model,
            "id": self.contribution_id,
            "kind": self.kind,
            "owner": self.owner,
            "requestedAuthorities": list(self.requested_authorities),
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginContributionReservation:
        document = _exact_document(
            value,
            name="Plugin contribution reservation",
            keys={
                "configuration",
                "entrypoint",
                "executionModel",
                "id",
                "kind",
                "owner",
                "requestedAuthorities",
                "required",
            },
        )
        contribution_id = document["id"]
        kind = document["kind"]
        owner = document["owner"]
        entrypoint = document["entrypoint"]
        execution_model = document["executionModel"]
        authorities = document["requestedAuthorities"]
        configuration = document["configuration"]
        required = document["required"]
        if not (
            isinstance(contribution_id, str)
            and isinstance(kind, str)
            and isinstance(owner, str)
            and isinstance(entrypoint, str)
            and isinstance(execution_model, str)
        ):
            raise ValueError("Plugin contribution identity fields must be strings")
        if not isinstance(authorities, list) or not all(
            isinstance(item, str) for item in authorities
        ):
            raise ValueError("Plugin requestedAuthorities must be a string list")
        if not isinstance(configuration, dict):
            raise ValueError("Plugin contribution configuration must be an object")
        if not isinstance(required, bool):
            raise ValueError("Plugin contribution required must be a boolean")
        return cls(
            contribution_id=contribution_id,
            kind=cast(PluginContributionKind, kind),
            owner=owner,
            entrypoint=entrypoint,
            execution_model=cast(PluginExecutionModel, execution_model),
            requested_authorities=tuple(authorities),
            configuration=configuration,
            required=required,
        )


@dataclass(frozen=True, slots=True)
class PluginContributionIndex:
    """Versioned inert reservation index parsed without importing Plugin code."""

    items: tuple[PluginContributionReservation, ...] = ()
    version: int = PLUGIN_CONTRIBUTION_INDEX_VERSION

    def __post_init__(self) -> None:
        if self.version != PLUGIN_CONTRIBUTION_INDEX_VERSION:
            raise ValueError("Unsupported Plugin contribution index version")
        if any(
            not isinstance(item, PluginContributionReservation) for item in self.items
        ):
            raise TypeError("Plugin contribution index items have an invalid type")
        items = tuple(sorted(self.items, key=lambda item: item.contribution_id))
        identities = [item.contribution_id for item in items]
        if len(identities) != len(set(identities)):
            raise ValueError("Plugin contribution index contains duplicate identities")
        object.__setattr__(self, "items", items)

    @property
    def fingerprint(self) -> str:
        return _document_digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "items": [item.to_dict() for item in self.items],
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginContributionIndex:
        document = _exact_document(
            value,
            name="Plugin contribution index",
            keys={"items", "version"},
        )
        version = document["version"]
        items = document["items"]
        if not isinstance(version, int) or isinstance(version, bool):
            raise ValueError("Plugin contribution index version must be an integer")
        if not isinstance(items, list):
            raise ValueError("Plugin contribution index items must be a list")
        return cls(
            items=tuple(PluginContributionReservation.from_dict(item) for item in items),
            version=version,
        )


@dataclass(frozen=True, slots=True)
class PluginDeclaration:
    """Strict serializable declaration consuming one manifest reservation."""

    plugin_id: str
    contribution_id: str
    kind: PluginContributionKind
    owner: str
    reservation_fingerprint: str
    payload: Mapping[str, object]
    ir_version: int = PLUGIN_DECLARATION_IR_VERSION

    def __post_init__(self) -> None:
        _require_identifier(self.plugin_id, name="Plugin id")
        _require_identifier(self.contribution_id, name="contribution id")
        _require_identifier(self.owner, name="contribution owner")
        if self.kind != "capability_provider":
            raise ValueError("Unsupported Plugin declaration kind")
        if self.ir_version != PLUGIN_DECLARATION_IR_VERSION:
            raise ValueError("Unsupported Plugin declaration IR version")
        _require_sha256(
            self.reservation_fingerprint,
            name="reservation fingerprint",
        )
        object.__setattr__(self, "payload", _freeze_json_mapping(self.payload))

    @property
    def fingerprint(self) -> str:
        return _document_digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "contributionId": self.contribution_id,
            "irVersion": self.ir_version,
            "kind": self.kind,
            "owner": self.owner,
            "payload": _thaw_json(self.payload),
            "pluginId": self.plugin_id,
            "reservationFingerprint": self.reservation_fingerprint,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginDeclaration:
        document = _exact_document(
            value,
            name="Plugin declaration",
            keys={
                "contributionId",
                "irVersion",
                "kind",
                "owner",
                "payload",
                "pluginId",
                "reservationFingerprint",
            },
        )
        plugin_id = document["pluginId"]
        contribution_id = document["contributionId"]
        kind = document["kind"]
        owner = document["owner"]
        reservation_fingerprint = document["reservationFingerprint"]
        payload = document["payload"]
        ir_version = document["irVersion"]
        if not all(
            isinstance(item, str)
            for item in (
                plugin_id,
                contribution_id,
                kind,
                owner,
                reservation_fingerprint,
            )
        ):
            raise ValueError("Plugin declaration identity fields must be strings")
        if not isinstance(payload, dict):
            raise ValueError("Plugin declaration payload must be an object")
        if not isinstance(ir_version, int) or isinstance(ir_version, bool):
            raise ValueError("Plugin declaration IR version must be an integer")
        assert isinstance(plugin_id, str)
        assert isinstance(contribution_id, str)
        assert isinstance(kind, str)
        assert isinstance(owner, str)
        assert isinstance(reservation_fingerprint, str)
        return cls(
            plugin_id=plugin_id,
            contribution_id=contribution_id,
            kind=cast(PluginContributionKind, kind),
            owner=owner,
            reservation_fingerprint=reservation_fingerprint,
            payload=payload,
            ir_version=ir_version,
        )


def _entrypoint_path_and_symbol(value: str) -> tuple[PurePosixPath, str]:
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("Plugin contribution entrypoint must be a string")
    raw_path, separator, symbol = value.rpartition(":")
    path = PurePosixPath(raw_path)
    if (
        separator != ":"
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or not _SYMBOL.fullmatch(symbol)
    ):
        raise ValueError("Plugin entrypoint must use contained path.py:symbol syntax")
    return path, symbol


def _require_identifier(value: object, *, name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid {name}")


def _require_sha256(value: object, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _freeze_json_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("Plugin declaration data must be a mapping")
    frozen = {
        key: _freeze_json_value(item)
        for key, item in value.items()
        if isinstance(key, str)
    }
    if len(frozen) != len(value):
        raise ValueError("Plugin declaration object keys must be strings")
    _canonical_json(frozen)
    return MappingProxyType(frozen)


def _freeze_json_value(value: object) -> object:
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, Mapping):
        return _freeze_json_mapping(value)
    if isinstance(value, list | tuple):
        return tuple(_freeze_json_value(item) for item in value)
    raise ValueError("Plugin declaration data must contain only JSON values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            _thaw_json(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Plugin declaration data is not canonical JSON") from exc


def _document_digest(value: object) -> str:
    return sha256(_canonical_json(value)).hexdigest()


def _exact_document(
    value: object,
    *,
    name: str,
    keys: set[str],
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{name} fields do not match the supported format")
    return value


__all__ = [
    "PLUGIN_CONTRIBUTION_INDEX_VERSION",
    "PLUGIN_DECLARATION_IR_VERSION",
    "PluginContributionIndex",
    "PluginContributionKind",
    "PluginContributionReservation",
    "PluginDeclaration",
    "PluginExecutionModel",
]
