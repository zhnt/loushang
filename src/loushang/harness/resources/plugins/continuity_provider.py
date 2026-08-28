"""Owner-neutral wire projection for Continuity Provider declarations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Literal, Never, Self

from loushang.harness.resources.plugins.declarations import (
    PluginDeclarationCodecError,
    _freeze_json_mapping,
    _thaw_json,
)
from loushang.harness.resources.plugins.symbol_reference import (
    PluginSymbolReference,
)

CONTINUITY_PROVIDER_DECLARATION_OWNER = "harness.continuity"
CONTINUITY_PROVIDER_PAYLOAD_VERSION_V1 = 1
CONTINUITY_PROVIDER_PAYLOAD_VERSION_V2 = 2
CONTINUITY_PROVIDER_PAYLOAD_VERSION = CONTINUITY_PROVIDER_PAYLOAD_VERSION_V2
CONTINUITY_PROVIDER_SEMANTIC_SCHEMA_ID = "harness.continuity.continuity-provider"

ContinuityProviderDeclaredAction = Literal["activate", "delete"]


@dataclass(frozen=True, slots=True)
class ContinuityProviderDeclarationWirePayloadV1:
    """Strict inert wire record shared by declaration compilation consumers."""

    factory: PluginSymbolReference
    disposer: PluginSymbolReference
    binding_inputs: Mapping[str, object] = field(default_factory=dict)
    continuity_profile_version: int = 1
    payload_version: int = CONTINUITY_PROVIDER_PAYLOAD_VERSION_V1

    def __post_init__(self) -> None:
        if not isinstance(self.factory, PluginSymbolReference):
            raise TypeError("Continuity Provider payload requires a factory reference")
        if not isinstance(self.disposer, PluginSymbolReference):
            raise TypeError("Continuity Provider payload requires a disposer reference")
        if self.factory.execution_model != self.disposer.execution_model:
            raise ValueError(
                "Continuity Provider factory and disposer must share execution model"
            )
        if self.factory.execution_model != "in_process":
            raise ValueError("Continuity Provider v1 requires in-process symbols")
        if (
            isinstance(self.continuity_profile_version, bool)
            or not isinstance(self.continuity_profile_version, int)
            or self.continuity_profile_version != 1
        ):
            raise ValueError("Unsupported Continuity Provider profile version")
        if self.payload_version != CONTINUITY_PROVIDER_PAYLOAD_VERSION_V1:
            raise ValueError("Unsupported Continuity Provider payload version")
        try:
            binding_inputs = _freeze_json_mapping(self.binding_inputs)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Continuity Provider binding inputs must be strict JSON data"
            ) from exc
        object.__setattr__(self, "binding_inputs", binding_inputs)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return sha256(
            b"loushang.continuity-provider-payload/v1\0" + payload
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "bindingInputs": _thaw_json(self.binding_inputs),
            "continuityProfileVersion": self.continuity_profile_version,
            "disposer": self.disposer.to_dict(),
            "factory": self.factory.to_dict(),
            "payloadVersion": self.payload_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if not isinstance(value, dict):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Continuity Provider payload must be an object",
            )
        version = value.get("payloadVersion")
        if version != CONTINUITY_PROVIDER_PAYLOAD_VERSION_V1:
            _raise_codec(
                "unsupported_continuity_provider_declaration_payload_version",
                "Unsupported Continuity Provider payload version",
            )
        expected = {
            "bindingInputs",
            "continuityProfileVersion",
            "disposer",
            "factory",
            "payloadVersion",
        }
        if set(value) != expected:
            _raise_codec(
                "plugin_declaration_field_set_mismatch",
                "Continuity Provider payload has invalid fields",
            )
        if not isinstance(value["bindingInputs"], dict):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Continuity Provider bindingInputs must be an object",
            )
        if not isinstance(value["factory"], dict) or not isinstance(
            value["disposer"], dict
        ):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Continuity Provider symbols must be objects",
            )
        try:
            return cls(
                factory=PluginSymbolReference.from_dict(value["factory"]),
                disposer=PluginSymbolReference.from_dict(value["disposer"]),
                binding_inputs=value["bindingInputs"],
                continuity_profile_version=value["continuityProfileVersion"],
                payload_version=version,
            )
        except PluginDeclarationCodecError:
            raise
        except (TypeError, ValueError) as exc:
            _raise_codec(
                "plugin_declaration_field_value_mismatch",
                f"Invalid Continuity Provider payload: {exc}",
                cause=exc,
            )


@dataclass(frozen=True, slots=True)
class ContinuityProviderDeclarationWirePayloadV2:
    """Strict declaration whose admitted actions cannot change at runtime."""

    factory: PluginSymbolReference
    disposer: PluginSymbolReference
    supported_actions: tuple[ContinuityProviderDeclaredAction, ...] = ("activate",)
    binding_inputs: Mapping[str, object] = field(default_factory=dict)
    continuity_profile_version: int = 1
    payload_version: int = CONTINUITY_PROVIDER_PAYLOAD_VERSION_V2

    def __post_init__(self) -> None:
        if not isinstance(self.factory, PluginSymbolReference):
            raise TypeError("Continuity Provider payload requires a factory reference")
        if not isinstance(self.disposer, PluginSymbolReference):
            raise TypeError("Continuity Provider payload requires a disposer reference")
        if self.factory.execution_model != self.disposer.execution_model:
            raise ValueError(
                "Continuity Provider factory and disposer must share execution model"
            )
        if self.factory.execution_model != "in_process":
            raise ValueError("Continuity Provider v2 requires in-process symbols")
        actions = tuple(self.supported_actions)
        if actions not in {("activate",), ("activate", "delete")}:
            raise ValueError("Continuity Provider actions must be explicitly ordered")
        if (
            isinstance(self.continuity_profile_version, bool)
            or not isinstance(self.continuity_profile_version, int)
            or self.continuity_profile_version != 1
        ):
            raise ValueError("Unsupported Continuity Provider profile version")
        if self.payload_version != CONTINUITY_PROVIDER_PAYLOAD_VERSION_V2:
            raise ValueError("Unsupported Continuity Provider payload version")
        try:
            binding_inputs = _freeze_json_mapping(self.binding_inputs)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Continuity Provider binding inputs must be strict JSON data"
            ) from exc
        object.__setattr__(self, "supported_actions", actions)
        object.__setattr__(self, "binding_inputs", binding_inputs)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return sha256(
            b"loushang.continuity-provider-payload/v2\0" + payload
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "bindingInputs": _thaw_json(self.binding_inputs),
            "continuityProfileVersion": self.continuity_profile_version,
            "disposer": self.disposer.to_dict(),
            "factory": self.factory.to_dict(),
            "payloadVersion": self.payload_version,
            "supportedActions": list(self.supported_actions),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if not isinstance(value, dict):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Continuity Provider payload must be an object",
            )
        version = value.get("payloadVersion")
        if version != CONTINUITY_PROVIDER_PAYLOAD_VERSION_V2:
            _raise_codec(
                "unsupported_continuity_provider_declaration_payload_version",
                "Unsupported Continuity Provider payload version",
            )
        expected = {
            "bindingInputs",
            "continuityProfileVersion",
            "disposer",
            "factory",
            "payloadVersion",
            "supportedActions",
        }
        if set(value) != expected:
            _raise_codec(
                "plugin_declaration_field_set_mismatch",
                "Continuity Provider payload has invalid fields",
            )
        if not isinstance(value["bindingInputs"], dict):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Continuity Provider bindingInputs must be an object",
            )
        raw_actions = value["supportedActions"]
        if not isinstance(raw_actions, list) or any(
            not isinstance(item, str) for item in raw_actions
        ):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Continuity Provider supportedActions must be a string array",
            )
        if not isinstance(value["factory"], dict) or not isinstance(
            value["disposer"], dict
        ):
            _raise_codec(
                "plugin_declaration_field_type_mismatch",
                "Continuity Provider symbols must be objects",
            )
        try:
            return cls(
                factory=PluginSymbolReference.from_dict(value["factory"]),
                disposer=PluginSymbolReference.from_dict(value["disposer"]),
                supported_actions=tuple(raw_actions),  # type: ignore[arg-type]
                binding_inputs=value["bindingInputs"],
                continuity_profile_version=value["continuityProfileVersion"],
                payload_version=version,
            )
        except PluginDeclarationCodecError:
            raise
        except (TypeError, ValueError) as exc:
            _raise_codec(
                "plugin_declaration_field_value_mismatch",
                f"Invalid Continuity Provider payload: {exc}",
                cause=exc,
            )


def decode_continuity_provider_declaration_payload(
    value: object,
) -> (
    ContinuityProviderDeclarationWirePayloadV1
    | ContinuityProviderDeclarationWirePayloadV2
):
    if not isinstance(value, dict):
        _raise_codec(
            "plugin_declaration_field_type_mismatch",
            "Continuity Provider payload must be an object",
        )
    version = value.get("payloadVersion")
    if version == CONTINUITY_PROVIDER_PAYLOAD_VERSION_V1:
        return ContinuityProviderDeclarationWirePayloadV1.from_dict(value)
    if version == CONTINUITY_PROVIDER_PAYLOAD_VERSION_V2:
        return ContinuityProviderDeclarationWirePayloadV2.from_dict(value)
    _raise_codec(
        "unsupported_continuity_provider_declaration_payload_version",
        "Unsupported Continuity Provider payload version",
    )


def _raise_codec(
    code: str,
    message: str,
    *,
    cause: BaseException | None = None,
) -> Never:
    error = PluginDeclarationCodecError(message, code=code)
    if cause is None:
        raise error
    raise error from cause


__all__ = [
    "CONTINUITY_PROVIDER_DECLARATION_OWNER",
    "CONTINUITY_PROVIDER_PAYLOAD_VERSION",
    "CONTINUITY_PROVIDER_PAYLOAD_VERSION_V1",
    "CONTINUITY_PROVIDER_PAYLOAD_VERSION_V2",
    "CONTINUITY_PROVIDER_SEMANTIC_SCHEMA_ID",
    "ContinuityProviderDeclaredAction",
    "ContinuityProviderDeclarationWirePayloadV1",
    "ContinuityProviderDeclarationWirePayloadV2",
    "decode_continuity_provider_declaration_payload",
]
