"""Source-neutral semantic fingerprints for frozen Plugin declarations."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from types import MappingProxyType
from typing import cast

from loushang.harness.plugin_authoring.capability_provider import (
    _capability_provider_payload_from_declaration,
)
from loushang.harness.plugin_authoring.consumer_pack import (
    CommandPackDeclarationPayload,
    ToolPackDeclarationPayload,
)
from loushang.harness.plugin_authoring.resource_item import (
    _payload_from_declaration,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.continuity_provider import (
    CONTINUITY_PROVIDER_DECLARATION_OWNER,
    CONTINUITY_PROVIDER_SEMANTIC_SCHEMA_ID,
    decode_continuity_provider_declaration_payload,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionKind,
    PluginDeclaration,
    _freeze_json_mapping,
    _require_identifier,
    _thaw_json,
)

PLUGIN_CONTRIBUTION_SEMANTIC_FINGERPRINT_VERSION = 1
_SEMANTIC_FINGERPRINT_DOMAIN = "loushang.plugin-contribution-semantic/v1"


@dataclass(frozen=True, slots=True)
class _CatalogRevision:
    catalog: str
    revision: int

    def __post_init__(self) -> None:
        _require_identifier(self.catalog, name="Plugin semantic catalog identity")
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision <= 0
        ):
            raise ValueError("Plugin semantic catalog revision must be positive")

    def to_dict(self) -> dict[str, object]:
        return {"catalog": self.catalog, "revision": self.revision}


@dataclass(frozen=True, slots=True, init=False)
class PluginContributionSemanticFingerprint:
    """Compiler-owned v1 diagnostic; never an admission or identity token."""

    digest: str
    canonical_bytes: bytes = field(repr=False)
    _record: MappingProxyType[str, object] = field(repr=False)

    def __init__(self) -> None:
        raise TypeError(
            "Plugin semantic fingerprints are declaration-compiler constructed"
        )

    @classmethod
    def _from_compiled_record(
        cls,
        record: dict[str, object],
    ) -> PluginContributionSemanticFingerprint:
        canonical_bytes = StrictPluginJsonCodec.encode(record)
        fingerprint = object.__new__(cls)
        object.__setattr__(
            fingerprint,
            "digest",
            sha256(canonical_bytes).hexdigest(),
        )
        object.__setattr__(fingerprint, "canonical_bytes", canonical_bytes)
        object.__setattr__(
            fingerprint,
            "_record",
            cast(MappingProxyType[str, object], _freeze_json_mapping(record)),
        )
        return fingerprint

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], _thaw_json(self._record))


@dataclass(frozen=True, slots=True)
class _SemanticProjection:
    payload_schema_id: str
    payload_schema_version: int
    catalog_revisions: tuple[_CatalogRevision, ...]
    payload: dict[str, object]

    def __post_init__(self) -> None:
        _require_identifier(
            self.payload_schema_id,
            name="Plugin semantic payload schema identity",
        )
        if (
            not isinstance(self.payload_schema_version, int)
            or isinstance(self.payload_schema_version, bool)
            or self.payload_schema_version <= 0
        ):
            raise ValueError("Plugin semantic payload schema version must be positive")
        if any(
            not isinstance(item, _CatalogRevision) for item in self.catalog_revisions
        ):
            raise TypeError("Plugin semantic catalog revisions must be typed records")
        identities = tuple(item.catalog for item in self.catalog_revisions)
        if identities != tuple(sorted(identities)):
            raise ValueError("Plugin semantic catalog revisions must be sorted")
        if len(identities) != len(set(identities)):
            raise ValueError("Plugin semantic catalog revisions must be unique")
        object.__setattr__(
            self,
            "payload",
            cast(dict[str, object], _thaw_json(_freeze_json_mapping(self.payload))),
        )


def compile_plugin_contribution_semantic_fingerprint(
    declaration: PluginDeclaration,
) -> PluginContributionSemanticFingerprint:
    """Compile the one source-neutral diagnostic from strict typed payload IR."""

    if not isinstance(declaration, PluginDeclaration):
        raise TypeError("Plugin semantic fingerprint requires PluginDeclaration")
    projection = _project_declaration(declaration)
    return PluginContributionSemanticFingerprint._from_compiled_record(
        {
            "catalogRevisions": [
                item.to_dict() for item in projection.catalog_revisions
            ],
            "domain": _SEMANTIC_FINGERPRINT_DOMAIN,
            "kind": declaration.kind,
            "owner": declaration.owner,
            "payload": projection.payload,
            "payloadSchema": {
                "id": projection.payload_schema_id,
                "version": projection.payload_schema_version,
            },
        }
    )


def _project_declaration(declaration: PluginDeclaration) -> _SemanticProjection:
    if declaration.kind == "resource_item":
        resource_payload = _payload_from_declaration(declaration)
        return _SemanticProjection(
            payload_schema_id=resource_payload.schema_id,
            payload_schema_version=resource_payload.schema_version,
            catalog_revisions=(),
            payload=resource_payload.to_dict(),
        )
    if declaration.kind == "tool_pack":
        tool_payload = ToolPackDeclarationPayload._from_declaration(declaration)
        return _catalog_consumer_projection(
            declaration.kind,
            owner=declaration.owner,
            catalog_id=tool_payload.catalog_id,
            catalog_revision=tool_payload.catalog_revision,
            payload_version=tool_payload.payload_version,
            payload=tool_payload.to_dict(),
        )
    if declaration.kind == "command_pack":
        command_payload = CommandPackDeclarationPayload._from_declaration(declaration)
        return _catalog_consumer_projection(
            declaration.kind,
            owner=declaration.owner,
            catalog_id=command_payload.catalog_id,
            catalog_revision=command_payload.catalog_revision,
            payload_version=command_payload.payload_version,
            payload=command_payload.to_dict(),
        )
    if declaration.kind == "continuity_provider":
        if declaration.owner != CONTINUITY_PROVIDER_DECLARATION_OWNER:
            raise ValueError("Continuity Provider semantic owner is invalid")
        continuity_payload = decode_continuity_provider_declaration_payload(
            declaration.to_dict()["payload"]
        )
        return _SemanticProjection(
            payload_schema_id=CONTINUITY_PROVIDER_SEMANTIC_SCHEMA_ID,
            payload_schema_version=continuity_payload.payload_version,
            catalog_revisions=(),
            payload=continuity_payload.to_dict(),
        )
    provider_payload = _capability_provider_payload_from_declaration(declaration)
    return _SemanticProjection(
        payload_schema_id=f"{declaration.owner}.capability-provider",
        payload_schema_version=provider_payload.payload_version,
        catalog_revisions=(),
        payload=provider_payload.to_dict(),
    )


def _catalog_consumer_projection(
    kind: PluginContributionKind,
    *,
    owner: str,
    catalog_id: str,
    catalog_revision: int,
    payload_version: int,
    payload: dict[str, object],
) -> _SemanticProjection:
    if kind not in {"command_pack", "tool_pack"}:
        raise ValueError("Plugin semantic catalog projection requires a pack kind")
    schema_suffix = "command-pack" if kind == "command_pack" else "tool-pack"
    return _SemanticProjection(
        payload_schema_id=f"{owner}.{schema_suffix}",
        payload_schema_version=payload_version,
        catalog_revisions=(
            _CatalogRevision(catalog=catalog_id, revision=catalog_revision),
        ),
        payload=payload,
    )


__all__ = [
    "PLUGIN_CONTRIBUTION_SEMANTIC_FINGERPRINT_VERSION",
    "PluginContributionSemanticFingerprint",
    "compile_plugin_contribution_semantic_fingerprint",
]
