"""Versioned facts for durable model-input reconstruction."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, TypeAlias, cast

from loushang.ai import AIError, AIErrorCode
from loushang.foundation.json import JSONValue, dump_json_value

MODEL_INPUT_SCHEMA_VERSION = 1
MODEL_INPUT_PROJECTION_VERSION = "harness.model-input.v1"
MODEL_INPUT_MAX_ENCODED_RECORD_BYTES = 1024 * 1024
_MODEL_INPUT_V1_REQUIRED_LOGICAL_COMPONENTS = (
    "system_prompt",
    "messages",
    "tools",
    "request_options",
)

FrozenModelInputPrimitive: TypeAlias = str | int | float | bool | None
FrozenModelInputValue: TypeAlias = (
    FrozenModelInputPrimitive
    | tuple["FrozenModelInputValue", ...]
    | Mapping[str, "FrozenModelInputValue"]
)
ModelInputOutcome: TypeAlias = Literal["prepared"]


class ModelInputRecordSizeError(AIError, ValueError):
    """A Model Input fact cannot fit inside the declared record ceiling."""

    default_code = AIErrorCode.REQUEST_VALIDATION
    default_source = "loushang.harness.transcript"


class ModelInputIntegrityError(RuntimeError):
    """Committed facts cannot prove the requested model input."""


def canonical_model_input_json(value: object, *, name: str) -> str:
    return dump_json_value(
        thaw_model_input_json(freeze_model_input_json(value, name=name)),
        name=name,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def hash_model_input_json(value: object, *, name: str) -> str:
    canonical = canonical_model_input_json(value, name=name)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def freeze_model_input_json(
    value: object,
    *,
    name: str,
) -> FrozenModelInputValue:
    return _freeze_json(value, path=name, seen=set())


def thaw_model_input_json(value: object) -> JSONValue:
    if isinstance(value, Mapping):
        projected: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("model-input JSON keys must be strings")
            projected[key] = thaw_model_input_json(item)
        return projected
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [thaw_model_input_json(item) for item in value]
    if value is None or type(value) in {str, bool, int, float}:
        return cast(JSONValue, value)
    raise TypeError(f"model-input value is outside strict JSON: {type(value).__name__}")


@dataclass(frozen=True)
class ModelInputComponent:
    """Canonical inline bytes retained once and referenced by later snapshots."""

    content_hash: str
    content: FrozenModelInputValue = field(repr=False)
    schema_version: int = MODEL_INPUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        frozen = freeze_model_input_json(self.content, name="model input component")
        expected = hash_model_input_json(frozen, name="model input component")
        if self.content_hash != expected:
            raise ValueError("model input component hash does not match its content")
        object.__setattr__(self, "content", frozen)


@dataclass(frozen=True)
class ModelInputComponentReference:
    name: str
    record_id: str
    content_hash: str

    def __post_init__(self) -> None:
        _require_text(self.name, name="model input component reference name")
        _require_text(self.record_id, name="model input component record id")
        _require_sha256(self.content_hash, name="model input component hash")


@dataclass(frozen=True)
class ModelInputSnapshot:
    """One prepared provider request and its reconstructable fact references."""

    snapshot_id: str
    invocation_id: str
    attempt: int
    purpose: str
    product_id: str
    runtime_id: str
    mount_generation: int
    profile_fingerprint: str
    registration_revision: str
    conversation_id: str
    source_leaf_id: str
    source_revision: int
    commit_revision: int
    provider_id: str
    model_id: str
    api_id: str
    endpoint_id: str
    logical_components: tuple[ModelInputComponentReference, ...]
    prepared_payload_components: tuple[ModelInputComponentReference, ...]
    model_visible_headers_component: ModelInputComponentReference
    logical_input_hash: str
    prepared_payload_hash: str
    schema_version: int = MODEL_INPUT_SCHEMA_VERSION
    projection_version: str = MODEL_INPUT_PROJECTION_VERSION
    outcome: ModelInputOutcome = "prepared"

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        if self.projection_version != MODEL_INPUT_PROJECTION_VERSION:
            raise ValueError(
                "unsupported Model Input projection version: "
                f"{self.projection_version}"
            )
        for attribute in (
            "snapshot_id",
            "invocation_id",
            "purpose",
            "product_id",
            "runtime_id",
            "profile_fingerprint",
            "registration_revision",
            "conversation_id",
            "source_leaf_id",
            "provider_id",
            "model_id",
            "api_id",
            "endpoint_id",
        ):
            _require_text(getattr(self, attribute), name=f"ModelInputSnapshot.{attribute}")
        _require_positive_int(self.attempt, name="ModelInputSnapshot.attempt")
        _require_non_negative_int(
            self.mount_generation,
            name="ModelInputSnapshot.mount_generation",
        )
        _require_positive_int(
            self.source_revision,
            name="ModelInputSnapshot.source_revision",
        )
        _require_positive_int(
            self.commit_revision,
            name="ModelInputSnapshot.commit_revision",
        )
        if self.source_revision >= self.commit_revision:
            raise ValueError(
                "ModelInputSnapshot source revision must precede commit revision"
            )
        _require_sha256(
            self.profile_fingerprint,
            name="ModelInputSnapshot.profile_fingerprint",
        )
        _require_sha256(
            self.registration_revision,
            name="ModelInputSnapshot.registration_revision",
        )
        _require_sha256(
            self.logical_input_hash,
            name="ModelInputSnapshot.logical_input_hash",
        )
        _require_sha256(
            self.prepared_payload_hash,
            name="ModelInputSnapshot.prepared_payload_hash",
        )
        if self.outcome != "prepared":
            raise ValueError("Model Input snapshot outcome must be 'prepared'")
        logical = _require_references(
            self.logical_components,
            name="logical components",
        )
        prepared = _require_references(
            self.prepared_payload_components,
            name="prepared payload components",
        )
        logical_names = {reference.name for reference in logical}
        missing = [
            name
            for name in _MODEL_INPUT_V1_REQUIRED_LOGICAL_COMPONENTS
            if name not in logical_names
        ]
        if missing:
            raise ValueError(
                "Model Input logical components are missing: " + ", ".join(missing)
            )
        if not isinstance(
            self.model_visible_headers_component,
            ModelInputComponentReference,
        ):
            raise TypeError("model-visible headers must use a component reference")
        if self.model_visible_headers_component.name != "model_visible_headers":
            raise ValueError(
                "Model Input headers component must be named model_visible_headers"
            )
        object.__setattr__(self, "logical_components", logical)
        object.__setattr__(self, "prepared_payload_components", prepared)


def _freeze_json(
    value: object,
    *,
    path: str,
    seen: set[int],
) -> FrozenModelInputValue:
    if value is None or type(value) in {str, bool, int, float}:
        # The canonical strict encoder rejects non-finite floats and invalid
        # UTF-8 below, so primitives still receive one authoritative check.
        canonical_model_input_json_primitive(value, name=path)
        return cast(FrozenModelInputPrimitive, value)
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in seen:
            raise TypeError(f"{path} must not contain a cycle")
        seen.add(identity)
        try:
            frozen: dict[str, FrozenModelInputValue] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError(f"{path} keys must be strings")
                frozen[key] = _freeze_json(
                    item,
                    path=f"{path}.{key}",
                    seen=seen,
                )
            return MappingProxyType(frozen)
        finally:
            seen.remove(identity)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        identity = id(value)
        if identity in seen:
            raise TypeError(f"{path} must not contain a cycle")
        seen.add(identity)
        try:
            return tuple(
                _freeze_json(item, path=f"{path}[{index}]", seen=seen)
                for index, item in enumerate(value)
            )
        finally:
            seen.remove(identity)
    raise TypeError(f"{path} is outside strict JSON: {type(value).__name__}")


def canonical_model_input_json_primitive(value: object, *, name: str) -> None:
    dump_json_value(value, name=name, ensure_ascii=False, separators=(",", ":"))


def _require_references(
    references: object,
    *,
    name: str,
) -> tuple[ModelInputComponentReference, ...]:
    if not isinstance(references, tuple | list) or any(
        not isinstance(item, ModelInputComponentReference) for item in references
    ):
        raise TypeError(f"{name} must contain ModelInputComponentReference values")
    resolved = tuple(cast(Sequence[ModelInputComponentReference], references))
    names = [item.name for item in resolved]
    if len(names) != len(set(names)):
        raise ValueError(f"{name} must use unique names")
    return resolved


def _require_schema_version(value: object) -> None:
    if value != MODEL_INPUT_SCHEMA_VERSION:
        raise ValueError(f"unsupported Model Input schema version: {value}")


def _require_text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _require_positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _require_non_negative_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _require_sha256(value: object, *, name: str) -> str:
    text = _require_text(value, name=name)
    prefix = "sha256:"
    digest = text[len(prefix) :] if text.startswith(prefix) else text
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{name} must be a lowercase SHA-256 fingerprint")
    return text


__all__ = [
    "MODEL_INPUT_MAX_ENCODED_RECORD_BYTES",
    "MODEL_INPUT_PROJECTION_VERSION",
    "MODEL_INPUT_SCHEMA_VERSION",
    "FrozenModelInputValue",
    "ModelInputComponent",
    "ModelInputComponentReference",
    "ModelInputIntegrityError",
    "ModelInputOutcome",
    "ModelInputRecordSizeError",
    "ModelInputSnapshot",
    "canonical_model_input_json",
    "freeze_model_input_json",
    "hash_model_input_json",
    "thaw_model_input_json",
]
