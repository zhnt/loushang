"""Product-hosted source adapter manifest and conformance contracts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, TypeVar, runtime_checkable

from loushang.foundation.json import JSONValue, dump_json_value, require_json_mapping
from loushang.ontology.schema.identity import SchemaIdentity
from loushang.ontology.source.model import (
    MappedSourceInput,
    SourceBinding,
    SourceInputRevision,
)

SOURCE_ADAPTER_MANIFEST_FORMAT = "loushang.ontology.source-adapter-manifest/v1"
_AdapterOutput = TypeVar(
    "_AdapterOutput",
    MappedSourceInput,
    SourceInputRevision,
)


@dataclass(frozen=True, slots=True)
class ApplicationSchemaIdentity:
    """Vendor application schema selected by one adapter artifact."""

    application_id: str
    schema_version: str

    def __post_init__(self) -> None:
        _non_empty_text("application_id", self.application_id)
        _non_empty_text("schema_version", self.schema_version)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "application_id": self.application_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> ApplicationSchemaIdentity:
        document = require_json_mapping(value, name="application schema identity")
        return cls(
            application_id=_document_text(document, "application_id"),
            schema_version=_document_text(document, "schema_version"),
        )


@dataclass(frozen=True, slots=True)
class SourceAdapterManifest:
    """Immutable artifact metadata; contains no credentials or endpoint state."""

    adapter_id: str
    adapter_version: str
    application_schema: ApplicationSchemaIdentity
    target_schema: SchemaIdentity
    bindings: tuple[SourceBinding, ...] | list[SourceBinding]

    def __post_init__(self) -> None:
        _non_empty_text("adapter_id", self.adapter_id)
        _non_empty_text("adapter_version", self.adapter_version)
        if not isinstance(self.application_schema, ApplicationSchemaIdentity):
            raise TypeError("application_schema must be an ApplicationSchemaIdentity")
        if not isinstance(self.target_schema, SchemaIdentity):
            raise TypeError("target_schema must be a SchemaIdentity")
        bindings = tuple(self.bindings)
        if not bindings:
            raise ValueError("source adapter manifest must declare at least one binding")
        if any(not isinstance(item, SourceBinding) for item in bindings):
            raise TypeError("bindings must contain SourceBinding values")
        values = tuple(sorted(bindings, key=lambda item: item.binding_id))
        binding_ids = [item.binding_id for item in values]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("source adapter manifest contains duplicate binding IDs")
        if any(item.schema_identity != self.target_schema for item in values):
            raise ValueError(
                "source adapter bindings must target the manifest schema identity"
            )
        object.__setattr__(self, "bindings", values)

    def binding(self, binding_id: str) -> SourceBinding | None:
        return next((item for item in self.bindings if item.binding_id == binding_id), None)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "format": SOURCE_ADAPTER_MANIFEST_FORMAT,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "application_schema": self.application_schema.to_dict(),
            "target_schema": self.target_schema.to_dict(),
            "bindings": [item.to_dict() for item in self.bindings],
        }

    def to_json(self) -> str:
        return dump_json_value(
            self.to_dict(),
            name="source adapter manifest",
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, payload: str) -> SourceAdapterManifest:
        try:
            document = require_json_mapping(
                json.loads(payload),
                name="source adapter manifest",
            )
            if document.get("format") != SOURCE_ADAPTER_MANIFEST_FORMAT:
                raise ValueError("unsupported source adapter manifest format")
            raw_bindings = document["bindings"]
            if not isinstance(raw_bindings, list):
                raise ValueError("source adapter manifest bindings must be a list")
            return cls(
                adapter_id=_document_text(document, "adapter_id"),
                adapter_version=_document_text(document, "adapter_version"),
                application_schema=ApplicationSchemaIdentity.from_dict(
                    document["application_schema"]
                ),
                target_schema=SchemaIdentity.from_dict(document["target_schema"]),
                bindings=[SourceBinding.from_dict(item) for item in raw_bindings],
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid source adapter manifest JSON: {exc}") from exc


@runtime_checkable
class SourceAdapter(Protocol):
    """Structural contract implemented and executed by a Product host."""

    @property
    def manifest(self) -> SourceAdapterManifest: ...

    def read_snapshot(self, binding_id: str) -> MappedSourceInput: ...

    def observe_head(self, binding_id: str) -> SourceInputRevision: ...


class SourceAdapterContractError(ValueError):
    """Stable failure emitted by the adapter conformance boundary."""

    def __init__(self, code: str, message: str) -> None:
        self.code = _non_empty_text("code", code)
        super().__init__(message)


def validate_source_adapter_outputs(
    manifest: SourceAdapterManifest,
    *,
    source_inputs: Iterable[MappedSourceInput],
    observed_heads: Iterable[SourceInputRevision],
) -> None:
    """Validate detached adapter outputs without executing vendor code."""

    if not isinstance(manifest, SourceAdapterManifest):
        raise TypeError("manifest must be a SourceAdapterManifest")
    inputs = tuple(source_inputs)
    heads = tuple(observed_heads)
    if any(not isinstance(item, MappedSourceInput) for item in inputs):
        raise TypeError("source_inputs must contain MappedSourceInput values")
    if any(not isinstance(item, SourceInputRevision) for item in heads):
        raise TypeError("observed_heads must contain SourceInputRevision values")
    input_by_binding = _unique_by_binding(inputs, kind="source input")
    head_by_binding = _unique_by_binding(heads, kind="source head")
    expected = {item.binding_id: item for item in manifest.bindings}
    _require_binding_set(expected, input_by_binding, kind="input")
    _require_binding_set(expected, head_by_binding, kind="head")
    for binding_id, binding in expected.items():
        source_input = input_by_binding[binding_id]
        if source_input.mapping_version != binding.mapping_version:
            raise SourceAdapterContractError(
                "input_mapping_version_mismatch",
                f"source input '{binding_id}' mapping version does not match manifest",
            )
        if source_input.coverage is not binding.coverage:
            raise SourceAdapterContractError(
                "input_coverage_mismatch",
                f"source input '{binding_id}' coverage does not match manifest",
            )
        head = head_by_binding[binding_id]
        if head.mapping_version != binding.mapping_version:
            raise SourceAdapterContractError(
                "head_mapping_version_mismatch",
                f"source head '{binding_id}' mapping version does not match manifest",
            )


def _unique_by_binding(
    values: tuple[_AdapterOutput, ...],
    *,
    kind: str,
) -> dict[str, _AdapterOutput]:
    by_binding: dict[str, _AdapterOutput] = {}
    for item in values:
        if item.binding_id in by_binding:
            raise SourceAdapterContractError(
                f"duplicate_{kind.replace(' ', '_')}",
                f"adapter output contains duplicate {kind} '{item.binding_id}'",
            )
        by_binding[item.binding_id] = item
    return by_binding


def _require_binding_set(
    expected: dict[str, SourceBinding],
    actual: Mapping[str, object],
    *,
    kind: str,
) -> None:
    if set(expected) != set(actual):
        raise SourceAdapterContractError(
            f"{kind}_binding_set_mismatch",
            f"adapter {kind} bindings do not match the manifest",
        )


def _non_empty_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _document_text(document: dict[str, JSONValue], name: str) -> str:
    try:
        return _non_empty_text(name, document[name])
    except KeyError as exc:
        raise ValueError(f"source adapter manifest is missing {name}") from exc


__all__ = [
    "SOURCE_ADAPTER_MANIFEST_FORMAT",
    "ApplicationSchemaIdentity",
    "SourceAdapter",
    "SourceAdapterContractError",
    "SourceAdapterManifest",
    "validate_source_adapter_outputs",
]
