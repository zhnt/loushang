"""Canonical, side-effect-free package compiler for the public Plugin SDK."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from loushang.harness.plugin_authoring.resource_item import (
    ResourceItemDeclarationPayload,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.declarations import (
    PLUGIN_DECLARATION_IR_VERSION,
    PluginContributionIndex,
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationDocument,
    PluginDeclarationDocumentCodec,
    PluginDeclarationSource,
)
from loushang.harness.resources.plugins.engine import (
    MANAGED_SKILL_ACTION_CONFIGURATION_KEY,
    PLUGIN_ENGINE_API_VERSION,
    PLUGIN_MANIFEST_VERSION,
)
from loushang.harness.resources.plugins.locators import parse_plugin_entrypoint
from loushang.harness.resources.skill_actions import (
    SkillActionDocument,
    SkillActionDocumentCodec,
)
from loushang.plugin._authoring import CapabilityProviderSpec, ResourceItemSpec

_RESOURCE_DOCUMENT = "declarations/resources.json"


@dataclass(frozen=True, slots=True)
class PluginPackageArtifact:
    """One canonical package-relative file generated from author intent."""

    path: str
    content: bytes


@dataclass(frozen=True, slots=True)
class PluginPackageSpec:
    """Immutable generated files for one independently selectable Plugin."""

    plugin_id: str
    version: str
    artifacts: tuple[PluginPackageArtifact, ...]

    def read(self, path: str) -> bytes:
        matches = tuple(item.content for item in self.artifacts if item.path == path)
        if len(matches) != 1:
            raise KeyError(path)
        return matches[0]


def package(
    *,
    id: str,
    version: str,
    contributions: Sequence[CapabilityProviderSpec | ResourceItemSpec],
    definition: str = "definition.py:declare",
) -> PluginPackageSpec:
    """Compile author intent to the sole canonical manifest and declaration IR."""

    if not isinstance(id, str) or not id.strip():
        raise ValueError("Plugin package id must be a non-empty string")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Plugin package version must be a non-empty string")
    if isinstance(contributions, CapabilityProviderSpec | ResourceItemSpec):
        raise TypeError("Plugin package contributions must be a sequence")
    contribution_specs = tuple(contributions)
    if not contribution_specs:
        raise ValueError("Plugin package must declare at least one contribution")
    if any(
        not isinstance(item, CapabilityProviderSpec | ResourceItemSpec)
        for item in contribution_specs
    ):
        raise TypeError("Plugin package contains an unsupported contribution spec")
    contribution_specs = tuple(
        sorted(contribution_specs, key=lambda item: item.contribution_id)
    )
    identities = tuple(item.contribution_id for item in contribution_specs)
    if len(identities) != len(set(identities)):
        raise ValueError("Plugin package contribution identities must be unique")
    definition_path, definition_symbol = parse_plugin_entrypoint(definition)
    definition_entrypoint = f"{definition_path.as_posix()}:{definition_symbol}"

    reservations = tuple(
        _reservation(spec, definition=definition_entrypoint)
        for spec in contribution_specs
    )
    index = PluginContributionIndex(items=reservations)
    features = _required_features(contribution_specs)
    manifest = {
        "contributionIndex": index.to_dict(),
        "engine": {
            "apiVersion": PLUGIN_ENGINE_API_VERSION,
            "declarationIrVersion": PLUGIN_DECLARATION_IR_VERSION,
            "requiredFeatures": list(features),
        },
        "manifestVersion": PLUGIN_MANIFEST_VERSION,
        "name": id,
        "packageRoot": ".",
        "version": version,
    }
    artifacts = [
        PluginPackageArtifact(
            path="plugin.json",
            content=StrictPluginJsonCodec.encode(manifest),
        )
    ]
    resource_declarations = tuple(
        _resource_declaration(id, spec, reservation)
        for spec, reservation in zip(
            contribution_specs,
            reservations,
            strict=True,
        )
        if isinstance(spec, ResourceItemSpec)
    )
    if resource_declarations:
        artifacts.append(
            PluginPackageArtifact(
                path=_RESOURCE_DOCUMENT,
                content=PluginDeclarationDocumentCodec.encode_bytes(
                    PluginDeclarationDocument(declarations=resource_declarations)
                ),
            )
        )
    for spec in contribution_specs:
        if not isinstance(spec, ResourceItemSpec) or not spec.actions:
            continue
        locator = PurePosixPath(spec.locator)
        skill_root = locator if spec.locator_kind == "directory" else locator.parent
        artifacts.append(
            PluginPackageArtifact(
                path=(skill_root / "actions.json").as_posix(),
                content=SkillActionDocumentCodec.encode_bytes(
                    SkillActionDocument(actions=spec.actions)
                ),
            )
        )
    artifact_paths = tuple(item.path for item in artifacts)
    if len(artifact_paths) != len(set(artifact_paths)):
        raise ValueError("Plugin package generated duplicate artifact paths")
    return PluginPackageSpec(
        plugin_id=id,
        version=version,
        artifacts=tuple(artifacts),
    )


def _reservation(
    spec: CapabilityProviderSpec | ResourceItemSpec,
    *,
    definition: str,
) -> PluginContributionReservation:
    if isinstance(spec, CapabilityProviderSpec):
        return PluginContributionReservation(
            contribution_id=spec.contribution_id,
            kind="capability_provider",
            owner=spec.capability,
            declaration_source=PluginDeclarationSource.in_process(definition),
            contribution_execution_model="in_process",
            requested_authorities=tuple(sorted(spec.authorities)),
            configuration={},
            required=True,
        )
    return PluginContributionReservation(
        contribution_id=spec.contribution_id,
        kind="resource_item",
        owner=spec.owner_namespace,
        declaration_source=PluginDeclarationSource.document(_RESOURCE_DOCUMENT),
        contribution_execution_model="data_only",
        requested_authorities=(),
        configuration=(
            {MANAGED_SKILL_ACTION_CONFIGURATION_KEY: True}
            if spec.actions
            else {}
        ),
        required=False,
    )


def _resource_declaration(
    plugin_id: str,
    spec: CapabilityProviderSpec | ResourceItemSpec,
    reservation: PluginContributionReservation,
) -> PluginDeclaration:
    assert isinstance(spec, ResourceItemSpec)
    payload = ResourceItemDeclarationPayload(
        locator=spec.locator,
        locator_kind=spec.locator_kind,
        media_type=spec.media_type,
        owner_namespace=spec.owner_namespace,
        resource_kind=spec.resource_kind,
        schema_id=spec.schema_id,
        schema_version=spec.schema_version,
    )
    return PluginDeclaration(
        plugin_id=plugin_id,
        contribution_id=spec.contribution_id,
        kind="resource_item",
        owner=spec.owner_namespace,
        reservation_fingerprint=reservation.fingerprint,
        source_descriptor_fingerprint=reservation.source_descriptor_fingerprint,
        source_kind="document",
        payload=payload.to_dict(),
    )


def _required_features(
    contributions: tuple[CapabilityProviderSpec | ResourceItemSpec, ...],
) -> tuple[str, ...]:
    features: set[str] = set()
    if any(isinstance(item, CapabilityProviderSpec) for item in contributions):
        features.update(
            {
                "capability-provider-v2",
                "in-process-definition-v1",
                "symbol-reference-v2",
            }
        )
    if any(isinstance(item, ResourceItemSpec) for item in contributions):
        features.update({"declaration-document-v1", "resource-item-v1"})
    if any(
        isinstance(item, ResourceItemSpec) and item.actions for item in contributions
    ):
        features.add("managed-skill-action-v1")
    return tuple(sorted(features))


__all__ = ["PluginPackageArtifact", "PluginPackageSpec", "package"]
