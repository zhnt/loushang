"""Synchronous Catalog-owned projection used before Extension activation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from loushang.harness.resource_catalog.inputs import AdmittedPackageResource
from loushang.harness.resources._catalog_embedded_source import (
    EmbeddedOemResourceSource,
    EmbeddedResourceCollectionHandle,
    build_embedded_resource_discovery_request,
    build_embedded_source_generation_ref,
)
from loushang.harness.resources._catalog_engine import (
    compose_resource_catalog,
    default_resource_merge_policy,
)
from loushang.harness.resources._catalog_native_source import (
    NativeFilesystemResourceSource,
    NativeResourceRootHandle,
    build_native_resource_discovery_request,
    build_native_source_generation_ref,
)
from loushang.harness.resources._catalog_package_source import (
    AdmittedPackageResourceSource,
    build_package_resource_discovery_request,
    build_package_source_generation_ref,
)
from loushang.harness.resources._catalog_projection import (
    ResourceProjectionDescriptorBinding,
    project_resource_catalog,
)
from loushang.harness.resources._catalog_records import (
    ResourceCatalogSnapshot,
    ResourceComponentProducer,
    ResourceIdentity,
    ResourceSourceSnapshot,
    build_activation_policy_snapshot,
    fingerprint_catalog_value,
)
from loushang.harness.resources._discovery_conventions import (
    DEFAULT_CONTEXT_FILE_NAMES,
)
from loushang.harness.resources.types import ResourceBundle, SkillDescriptor

_PREFLIGHT_GENERATION = 1


def prepare_resource_catalog_bootstrap_projection(
    *,
    product_id: str,
    runtime_id: str,
    product_policy_revision: str,
    cwd: Path,
    root_handles: tuple[NativeResourceRootHandle, ...],
    package_resources: tuple[AdmittedPackageResource, ...] = (),
    embedded_collections: tuple[EmbeddedResourceCollectionHandle, ...] = (),
    context_file_names: tuple[str, ...] = DEFAULT_CONTEXT_FILE_NAMES,
    disabled_skill_selectors: Sequence[str] = (),
) -> ResourceBundle:
    """Build a disposable Catalog projection for synchronous Session bootstrap.

    This projection exists only to seed Extension activation and initial prompt
    construction.  It uses the same Catalog sources and merge policy as the
    owner generation, owns no live publication, and disposes every source lease
    before returning the immutable compatibility copy.
    """

    source_snapshots: list[ResourceSourceSnapshot] = []
    descriptor_bindings: list[ResourceProjectionDescriptorBinding] = []
    sources: list[
        NativeFilesystemResourceSource
        | AdmittedPackageResourceSource
        | EmbeddedOemResourceSource
    ] = []
    unclaimed_packages = list(package_resources)
    unclaimed_embedded = list(embedded_collections)
    try:
        if root_handles:
            binding = _preflight_binding_fingerprint(
                product_id=product_id,
                runtime_id=runtime_id,
                source_id="harness.resources.source.native",
            )
            source_ref = build_native_source_generation_ref(
                source_id="harness.resources.source.native",
                product_id=product_id,
                runtime_id=runtime_id,
                owner_generation=_PREFLIGHT_GENERATION,
                producer=_preflight_producer(binding, "native"),
                component_binding_fingerprint=binding,
                root_handles=root_handles,
            )
            native_source = NativeFilesystemResourceSource(
                source_generation_ref=source_ref,
                root_handles=root_handles,
            )
            sources.append(native_source)
            source_snapshots.append(
                native_source.discover_initial(
                    build_native_resource_discovery_request(
                        product_id=product_id,
                        source_generation_ref=source_ref,
                        root_handle_ids=tuple(item.handle_id for item in root_handles),
                        context_file_names=context_file_names,
                    )
                )
            )
            descriptor_bindings.extend(native_source.projection_bindings)

        if package_resources:
            verified = tuple(item.verified_input for item in package_resources)
            binding = _preflight_binding_fingerprint(
                product_id=product_id,
                runtime_id=runtime_id,
                source_id="harness.resources.source.package",
            )
            source_ref = build_package_source_generation_ref(
                source_id="harness.resources.source.package",
                product_id=product_id,
                runtime_id=runtime_id,
                owner_generation=_PREFLIGHT_GENERATION,
                producer=_preflight_producer(binding, "package"),
                component_binding_fingerprint=binding,
                resources=verified,
            )
            package_source = AdmittedPackageResourceSource(
                source_generation_ref=source_ref,
                resources=verified,
            )
            sources.append(package_source)
            unclaimed_packages.clear()
            source_snapshots.append(
                package_source.discover_initial(
                    build_package_resource_discovery_request(
                        product_id=product_id,
                        source_generation_ref=source_ref,
                        admission_fingerprints=tuple(
                            sorted(
                                item.admission.fingerprint for item in package_resources
                            )
                        ),
                    )
                )
            )
            descriptor_bindings.extend(package_source.projection_bindings)

        if embedded_collections:
            binding = _preflight_binding_fingerprint(
                product_id=product_id,
                runtime_id=runtime_id,
                source_id="harness.resources.source.embedded",
            )
            source_ref = build_embedded_source_generation_ref(
                source_id="harness.resources.source.embedded",
                product_id=product_id,
                runtime_id=runtime_id,
                owner_generation=_PREFLIGHT_GENERATION,
                producer=_preflight_producer(binding, "embedded"),
                component_binding_fingerprint=binding,
                collections=embedded_collections,
            )
            embedded_source = EmbeddedOemResourceSource(
                source_generation_ref=source_ref,
                collections=embedded_collections,
            )
            sources.append(embedded_source)
            unclaimed_embedded.clear()
            source_snapshots.append(
                embedded_source.discover_initial(
                    build_embedded_resource_discovery_request(
                        product_id=product_id,
                        source_generation_ref=source_ref,
                        collection_handle_ids=tuple(
                            sorted(item.handle_id for item in embedded_collections)
                        ),
                    )
                )
            )
            descriptor_bindings.extend(embedded_source.projection_bindings)

        engine_binding = fingerprint_catalog_value(
            "loushang.resource-bootstrap-engine-binding/v1",
            {
                "productId": product_id,
                "productPolicyRevision": product_policy_revision,
                "runtimeId": runtime_id,
            },
        )
        merge_policy = default_resource_merge_policy()
        selection_snapshot = compose_resource_catalog(
            source_snapshots,
            catalog_generation=_PREFLIGHT_GENERATION,
            engine_binding_fingerprint=engine_binding,
            merge_policy=merge_policy,
            activation_policy=build_activation_policy_snapshot(
                policy_revision=f"{product_policy_revision}:skill-selection",
            ),
        )
        disabled = _disabled_skill_identities(
            selection_snapshot,
            descriptor_bindings,
            selectors=disabled_skill_selectors,
        )
        snapshot = compose_resource_catalog(
            source_snapshots,
            catalog_generation=_PREFLIGHT_GENERATION,
            engine_binding_fingerprint=engine_binding,
            merge_policy=merge_policy,
            activation_policy=build_activation_policy_snapshot(
                policy_revision=f"{product_policy_revision}:skill-activation",
                disabled_identities=disabled,
            ),
        )
        bundle = project_resource_catalog(
            catalog_snapshot=snapshot,
            cwd=cwd,
            descriptor_bindings=tuple(descriptor_bindings),
        ).to_compatibility_bundle()
        selected_skill_ids = {skill.id or skill.name for skill in bundle.skills}
        bundle.skills.extend(
            replace(descriptor, enabled=False)
            for descriptor in _disabled_skill_winner_descriptors(
                selection_snapshot,
                descriptor_bindings,
                disabled_identities=disabled,
            )
            if (descriptor.id or descriptor.name) not in selected_skill_ids
        )
        return bundle
    finally:
        for source in reversed(sources):
            source.dispose()
        for resource in reversed(unclaimed_packages):
            resource.close()
        for collection in reversed(unclaimed_embedded):
            collection.close()


def _disabled_skill_identities(
    selection_snapshot: ResourceCatalogSnapshot,
    bindings: Sequence[ResourceProjectionDescriptorBinding],
    *,
    selectors: Sequence[str],
) -> tuple[ResourceIdentity, ...]:
    disabled = {item for item in selectors if item}
    if not disabled:
        return ()
    by_fingerprint = {binding.candidate_fingerprint: binding for binding in bindings}
    identities: list[ResourceIdentity] = []
    for entry in selection_snapshot.effective_entries:
        if entry.identity.resource_kind != "skill":
            continue
        binding = by_fingerprint.get(entry.primary_candidate_fingerprint)
        if binding is None:
            continue
        descriptor = binding.descriptor
        if not isinstance(descriptor, SkillDescriptor):
            continue
        if disabled.intersection(
            {
                descriptor.name,
                descriptor.id,
                descriptor.canonical_name,
                str(descriptor.source_path),
            }
        ):
            identities.append(entry.identity)
    return tuple(sorted(set(identities)))


def _disabled_skill_winner_descriptors(
    selection_snapshot: ResourceCatalogSnapshot,
    bindings: Sequence[ResourceProjectionDescriptorBinding],
    *,
    disabled_identities: Sequence[ResourceIdentity],
) -> tuple[SkillDescriptor, ...]:
    disabled = frozenset(disabled_identities)
    winners = {
        entry.primary_candidate_fingerprint
        for entry in selection_snapshot.effective_entries
        if entry.identity.resource_kind == "skill" and entry.identity in disabled
    }
    by_fingerprint = {binding.candidate_fingerprint: binding for binding in bindings}
    descriptors: list[SkillDescriptor] = []
    for fingerprint in sorted(winners):
        binding = by_fingerprint.get(fingerprint)
        if binding is not None and isinstance(binding.descriptor, SkillDescriptor):
            descriptors.append(binding.descriptor)
    return tuple(descriptors)


def _preflight_binding_fingerprint(
    *,
    product_id: str,
    runtime_id: str,
    source_id: str,
) -> str:
    return fingerprint_catalog_value(
        "loushang.resource-bootstrap-source-binding/v1",
        {
            "productId": product_id,
            "runtimeId": runtime_id,
            "sourceId": source_id,
        },
    )


def _preflight_producer(
    binding_fingerprint: str,
    source_kind: str,
) -> ResourceComponentProducer:
    candidate = fingerprint_catalog_value(
        "loushang.resource-bootstrap-source-candidate/v1",
        {"bindingFingerprint": binding_fingerprint, "sourceKind": source_kind},
    )
    admission = fingerprint_catalog_value(
        "loushang.resource-bootstrap-source-admission/v1",
        {"candidateFingerprint": candidate},
    )
    package = fingerprint_catalog_value(
        "loushang.resource-bootstrap-source-package/v1",
        {"sourceKind": source_kind},
    )
    return ResourceComponentProducer(
        component_contribution_id=f"harness.resources.bootstrap.{source_kind}",
        component_candidate_fingerprint=candidate,
        component_admission_fingerprint=admission,
        binding_fingerprint=binding_fingerprint,
        plugin_instance_revision_ref="first-party-resource-bootstrap-v1",
        package_content_digest=package,
    )


__all__ = ["prepare_resource_catalog_bootstrap_projection"]
