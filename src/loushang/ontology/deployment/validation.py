"""Pure compatibility validation for immutable deployment profiles."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from loushang.ontology.deployment.model import (
    DeploymentProfile,
    IdentityCrosswalkArtifactLock,
    SchemaArtifactLock,
    SourceAdapterArtifactLock,
)
from loushang.ontology.identity import IdentityCrosswalkSnapshot
from loushang.ontology.schema import CompiledOntologySchema, SchemaIdentity
from loushang.ontology.source.adapter import SourceAdapterManifest
from loushang.ontology.source.model import SourceBinding


class DeploymentProfileValidationError(ValueError):
    """Stable compatibility failure raised before Product composition."""

    def __init__(self, code: str, message: str) -> None:
        self.code = _non_empty_text("code", code)
        super().__init__(message)


def lock_schema_artifact(schema: CompiledOntologySchema) -> SchemaArtifactLock:
    """Create the exact identity and content lock for a compiled schema."""

    if not isinstance(schema, CompiledOntologySchema):
        raise TypeError("schema must be a CompiledOntologySchema")
    return SchemaArtifactLock(
        schema_identity=SchemaIdentity.from_schema(schema),
        content_digest=_sha256_text(schema.to_json()),
    )


def lock_source_adapter_artifact(
    manifest: SourceAdapterManifest,
) -> SourceAdapterArtifactLock:
    """Create the exact identity and content lock for an adapter manifest."""

    if not isinstance(manifest, SourceAdapterManifest):
        raise TypeError("manifest must be a SourceAdapterManifest")
    return SourceAdapterArtifactLock(
        adapter_id=manifest.adapter_id,
        adapter_version=manifest.adapter_version,
        manifest_digest=_sha256_text(manifest.to_json()),
    )


def lock_identity_crosswalk(
    snapshot: IdentityCrosswalkSnapshot,
) -> IdentityCrosswalkArtifactLock:
    """Create the exact identity and content lock for one Crosswalk snapshot."""

    if not isinstance(snapshot, IdentityCrosswalkSnapshot):
        raise TypeError("snapshot must be an IdentityCrosswalkSnapshot")
    return IdentityCrosswalkArtifactLock(
        identity_namespace=snapshot.identity_namespace,
        revision=snapshot.revision,
        content_digest=snapshot.crosswalk_digest,
    )


def validate_deployment_profile(
    profile: DeploymentProfile,
    *,
    schema: CompiledOntologySchema,
    adapter_manifests: Iterable[SourceAdapterManifest],
    identity_crosswalk: IdentityCrosswalkSnapshot | None,
) -> tuple[SourceBinding, ...]:
    """Validate exact artifacts and return the enabled detached bindings."""

    if not isinstance(profile, DeploymentProfile):
        raise TypeError("profile must be a DeploymentProfile")
    if not isinstance(schema, CompiledOntologySchema):
        raise TypeError("schema must be a CompiledOntologySchema")
    manifests = tuple(adapter_manifests)
    if any(not isinstance(item, SourceAdapterManifest) for item in manifests):
        raise TypeError("adapter_manifests must contain SourceAdapterManifest values")
    if identity_crosswalk is not None and not isinstance(
        identity_crosswalk,
        IdentityCrosswalkSnapshot,
    ):
        raise TypeError(
            "identity_crosswalk must be an IdentityCrosswalkSnapshot or None"
        )

    actual_schema_lock = lock_schema_artifact(schema)
    if profile.schema_lock.schema_identity != actual_schema_lock.schema_identity:
        raise DeploymentProfileValidationError(
            "schema_identity_mismatch",
            "compiled schema identity does not match the deployment lock",
        )
    if profile.schema_lock.content_digest != actual_schema_lock.content_digest:
        raise DeploymentProfileValidationError(
            "schema_digest_mismatch",
            "compiled schema content does not match the deployment lock",
        )

    identity_lock = profile.identity_crosswalk_lock
    if (identity_lock is None) != (identity_crosswalk is None):
        raise DeploymentProfileValidationError(
            "identity_crosswalk_selection_mismatch",
            "supplied Identity Crosswalk does not match the deployment selection",
        )
    if identity_lock is not None and identity_crosswalk is not None:
        if identity_crosswalk.deployment_id != profile.deployment_id:
            raise DeploymentProfileValidationError(
                "identity_crosswalk_deployment_mismatch",
                "Identity Crosswalk targets a different deployment",
            )
        actual_identity_lock = lock_identity_crosswalk(identity_crosswalk)
        if identity_lock.identity_namespace != actual_identity_lock.identity_namespace:
            raise DeploymentProfileValidationError(
                "identity_crosswalk_namespace_mismatch",
                "Identity Crosswalk namespace does not match the deployment lock",
            )
        if identity_lock.revision != actual_identity_lock.revision:
            raise DeploymentProfileValidationError(
                "identity_crosswalk_revision_mismatch",
                "Identity Crosswalk revision does not match the deployment lock",
            )
        if identity_lock.content_digest != actual_identity_lock.content_digest:
            raise DeploymentProfileValidationError(
                "identity_crosswalk_digest_mismatch",
                "Identity Crosswalk content does not match the deployment lock",
            )

    manifest_by_id: dict[str, SourceAdapterManifest] = {}
    for manifest in manifests:
        if manifest.adapter_id in manifest_by_id:
            raise DeploymentProfileValidationError(
                "duplicate_adapter_manifest",
                f"adapter manifest '{manifest.adapter_id}' was supplied more than once",
            )
        manifest_by_id[manifest.adapter_id] = manifest
    lock_by_id = {item.adapter_id: item for item in profile.adapter_locks}
    if set(lock_by_id) != set(manifest_by_id):
        raise DeploymentProfileValidationError(
            "adapter_set_mismatch",
            "supplied adapter manifests do not match the deployment locks",
        )

    bindings_by_id: dict[str, tuple[str, SourceBinding]] = {}
    adapter_binding_ids: dict[str, set[str]] = {}
    for adapter_id in sorted(lock_by_id):
        lock = lock_by_id[adapter_id]
        manifest = manifest_by_id[adapter_id]
        actual_lock = lock_source_adapter_artifact(manifest)
        if lock.adapter_version != actual_lock.adapter_version:
            raise DeploymentProfileValidationError(
                "adapter_version_mismatch",
                f"adapter '{adapter_id}' version does not match the deployment lock",
            )
        if lock.manifest_digest != actual_lock.manifest_digest:
            raise DeploymentProfileValidationError(
                "adapter_digest_mismatch",
                f"adapter '{adapter_id}' manifest does not match the deployment lock",
            )
        if manifest.target_schema != profile.schema_lock.schema_identity:
            raise DeploymentProfileValidationError(
                "adapter_target_schema_mismatch",
                f"adapter '{adapter_id}' targets a different Ontology schema",
            )
        adapter_binding_ids[adapter_id] = {
            binding.binding_id for binding in manifest.bindings
        }
        for binding in manifest.bindings:
            if binding.binding_id in bindings_by_id:
                raise DeploymentProfileValidationError(
                    "duplicate_binding_id",
                    f"binding '{binding.binding_id}' is declared by multiple adapters",
                )
            bindings_by_id[binding.binding_id] = (adapter_id, binding)

    enabled: set[str] = set()
    selected_source_scopes: set[tuple[str, str]] = set()
    for source_instance in profile.source_instances:
        if source_instance.adapter_id not in manifest_by_id:
            raise DeploymentProfileValidationError(
                "source_instance_adapter_missing",
                f"source instance '{source_instance.source_instance_id}' references "
                f"unknown adapter '{source_instance.adapter_id}'",
            )
        for binding_id in source_instance.binding_ids:
            binding_entry = bindings_by_id.get(binding_id)
            if binding_entry is None:
                raise DeploymentProfileValidationError(
                    "source_instance_binding_missing",
                    f"source instance '{source_instance.source_instance_id}' "
                    f"references unknown binding '{binding_id}'",
                )
            binding_adapter_id, _binding = binding_entry
            if binding_adapter_id != source_instance.adapter_id:
                raise DeploymentProfileValidationError(
                    "source_instance_binding_adapter_mismatch",
                    f"binding '{binding_id}' belongs to adapter "
                    f"'{binding_adapter_id}', not '{source_instance.adapter_id}'",
                )
            enabled.add(binding_id)
            selected_source_scopes.add((source_instance.source_instance_id, binding_id))

    for adapter_id, binding_ids in adapter_binding_ids.items():
        if not enabled.intersection(binding_ids):
            raise DeploymentProfileValidationError(
                "unused_adapter_lock",
                f"adapter '{adapter_id}' contributes no enabled binding",
            )

    if identity_crosswalk is not None:
        for resolution in identity_crosswalk.entries:
            source_identity = resolution.source_identity
            if (
                source_identity.source_instance_id,
                source_identity.binding_id,
            ) not in selected_source_scopes:
                raise DeploymentProfileValidationError(
                    "identity_source_scope_unselected",
                    "Identity Crosswalk contains a record outside the selected "
                    "source-instance bindings",
                )

    return tuple(bindings_by_id[item][1] for item in sorted(enabled))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _non_empty_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


__all__ = [
    "DeploymentProfileValidationError",
    "lock_identity_crosswalk",
    "lock_schema_artifact",
    "lock_source_adapter_artifact",
    "validate_deployment_profile",
]
