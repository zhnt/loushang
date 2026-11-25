"""Synchronous Catalog projection for installed previews and Extension startup."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypeVar, cast

from loushang.harness.plugin_management.current_preview import (
    PluginCurrentCompositionPreviewV1,
    PluginCurrentResourceSelectionV1,
    project_current_product_resource_facts,
    project_current_product_resource_selections,
    project_current_selection_evidence,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resource_catalog.inputs import AdmittedPackageResource
from loushang.harness.resource_catalog.product_snapshot_source import (
    ProductSelectedResourceInput,
    ProductSelectedResourceSource,
    product_snapshot_source_policy_fingerprint,
)
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
    ResourceSourceGenerationRef,
    ResourceSourceSnapshot,
    build_activation_policy_snapshot,
    fingerprint_catalog_value,
)
from loushang.harness.resources._discovery_conventions import (
    DEFAULT_CONTEXT_FILE_NAMES,
)
from loushang.harness.resources.types import ResourceBundle, SkillDescriptor

if TYPE_CHECKING:
    from loushang.harness.capabilities.consumer_requirements import (
        ProductCompositionCompilation,
    )
    from loushang.harness.package_product.product_local_wheel_runtime import (
        PackageProductSelectedPluginManifestV1,
        _LocalWheelSelectedManifestReader,
    )
    from loushang.harness.resources.packages.product_epoch_guard import (
        PackageProductPosixFencedRuntimeOwner,
    )
    from loushang.harness.resources.packages.product_local_wheel_policy import (
        PackageProductLocalWheelPolicy,
    )
    from loushang.harness.resources.plugins.selection import PluginSelectionPlanV2

_PREFLIGHT_GENERATION = 1


@dataclass(frozen=True, slots=True)
class ResourceCatalogBootstrapResult:
    """Disposable projection paired with its exact Catalog selection receipt."""

    bundle: ResourceBundle
    catalog: ResourceCatalogSnapshot


class _InstalledResourceCompilation(Protocol):
    @property
    def product_composition(self) -> ProductCompositionCompilation: ...

    def product_resource_inputs(self) -> tuple[ProductSelectedResourceInput, ...]: ...


class _PreviewCompositionFailure(Protocol):
    @property
    def code(self) -> str: ...


class _InstalledBaseCompilation(_InstalledResourceCompilation, Protocol):
    @property
    def plan(self) -> PluginSelectionPlanV2: ...


_InstalledBaseT = TypeVar("_InstalledBaseT", bound=_InstalledBaseCompilation)


def preview_fenced_product_resources(
    epoch: PackageProductPosixFencedRuntimeOwner,
    policy: PackageProductLocalWheelPolicy,
    manifests: _LocalWheelSelectedManifestReader,
    *,
    base_plugin_id: str,
    composition_set_id: str,
    requested_plugin_ids: tuple[str, ...],
    disabled_skills_known: bool,
    executable_trust_classes: frozenset[str],
    max_files: int,
    max_total_bytes: int,
    evaluation_clock: Callable[[], float],
    observe_clock: Callable[[], int],
    compile_base: Callable[
        [PackageProductSelectedPluginManifestV1, int], _InstalledBaseT
    ],
    compile_data: Callable[
        [_InstalledBaseT | None, tuple[PackageProductSelectedPluginManifestV1, ...], int],
        tuple[_InstalledBaseT | None, _InstalledResourceCompilation | None],
    ],
    prepare_catalog: Callable[
        [_InstalledResourceCompilation | None, int],
        tuple[ResourceCatalogBootstrapResult, tuple[ProductSelectedResourceInput, ...]],
    ],
    base_missing: Callable[[], Exception],
    composition_errors: tuple[type[Exception], ...],
) -> PluginCurrentCompositionPreviewV1:
    """Project exact installed Resources using the caller's read-only Product authority."""
    desired = manifests.root_reader.desired_state
    before, _ = desired.capture_read_only()
    base_key = PluginInstallationKeyV1.workspace(
        policy.product_id, policy.project_scope_id, base_plugin_id
    )
    base_state = before.installation(base_key).selection.desired_state
    external_ids = manifests.selected_external_data_plugin_ids()
    evaluated_at = int(evaluation_clock())
    read_manifest = manifests.capture_selected_manifest_for_plugin

    def capture(
        ids: tuple[str, ...],
    ) -> tuple[PackageProductSelectedPluginManifestV1, ...]:
        return tuple(
            read_manifest(
                plugin_id, max_files=max_files, max_total_bytes=max_total_bytes
            )
            for plugin_id in ids
        )

    def project(
        bundle: ResourceBundle | None = None,
        catalog: ResourceCatalogSnapshot | None = None,
        product_inputs: tuple[ProductSelectedResourceInput, ...] = (),
        compilation: _InstalledResourceCompilation | None = None,
        blocker: _PreviewCompositionFailure | None = None,
    ) -> PluginCurrentCompositionPreviewV1:
        from loushang.harness.capabilities.consumer_requirements import (
            ProductCompositionError,
        )

        selections: list[PluginCurrentResourceSelectionV1] = []
        if bundle is not None and catalog is not None:
            selections = project_current_product_resource_selections(
                catalog, product_inputs
            )
        after, _ = desired.capture_read_only()
        epoch.assert_current()
        executable, gaps = project_current_selection_evidence(
            policy,
            before,
            requested_plugin_ids,
            executable_trust_classes=executable_trust_classes,
            excluded_plugin_id=base_plugin_id,
        )
        if disabled_skills_known:
            gaps.discard("disabled_skill_settings")
        if blocker is not None:
            gaps.add("resource_catalog_not_reached")
        if before.inventory_revision != after.inventory_revision:
            gaps.add("stale_snapshot")
        admissions, catalog_resources = (
            project_current_product_resource_facts(
                compilation.product_composition.resource_admissions
                if compilation is not None
                else (),
                bundle,
            )
            if bundle is not None
            else ((), ())
        )
        return PluginCurrentCompositionPreviewV1(
            product_id=policy.product_id,
            scope_id=policy.project_scope_id,
            composition_set_id=composition_set_id,
            observed_at_unix_ns=observe_clock(),
            desired_inventory_revision=before.inventory_revision,
            product_policy_revision=policy.policy_revision,
            product_authority_revision=policy.authority_revision,
            compiled_plugin_ids=plugin_ids,
            admitted_resources=admissions,
            catalog_resources=catalog_resources,
            catalog_diagnostic_codes=(
                tuple(sorted({item.code for item in bundle.diagnostics}))
                if bundle is not None
                else ()
            ),
            catalog_generation=catalog.catalog_generation
            if catalog is not None
            else None,
            catalog_snapshot_fingerprint=(
                catalog.snapshot_fingerprint if catalog is not None else None
            ),
            selected_resources=tuple(
                sorted(
                    selections,
                    key=lambda item: (
                        item.installation_key.plugin_id,
                        item.contribution_id,
                    ),
                )
            ),
            requires_authorized_preflight=tuple(sorted(executable)),
            evidence_gaps=tuple(sorted(gaps)),
            disposition="blocked" if blocker is not None else "projected",
            blocking_owner="product_composition" if blocker is not None else None,
            blocking_code=blocker.code if blocker is not None else None,
            blocking_admission_fingerprints=(
                blocker.admission_fingerprints
                if isinstance(blocker, ProductCompositionError)
                else ()
            ),
        )

    compiled: _InstalledResourceCompilation | None = None
    plugin_ids: tuple[str, ...] = ()
    try:
        if base_state == "absent":
            raise base_missing()
        if base_state == "installed_disabled":
            if external_ids:
                plugin_ids = external_ids
                _, compiled = compile_data(None, capture(external_ids), evaluated_at)
        else:
            (base,) = capture((base_plugin_id,))
            compiled_base = compile_base(base, evaluated_at)
            plugin_ids = compiled_base.plan.selected_plugin_ids
            if external_ids:
                plugin_ids = tuple(sorted((*plugin_ids, *external_ids)))
                extended, _ = compile_data(
                    compiled_base, capture(external_ids), evaluated_at
                )
                assert extended is not None
                compiled_base = extended
                plugin_ids = compiled_base.plan.selected_plugin_ids
            compiled = compiled_base
    except composition_errors as error:
        return project(blocker=cast(_PreviewCompositionFailure, error))
    projection, inputs = prepare_catalog(compiled, evaluated_at)
    return project(projection.bundle, projection.catalog, inputs, compiled)


def prepare_resource_catalog_bootstrap_projection(
    *,
    product_id: str,
    runtime_id: str,
    product_policy_revision: str,
    cwd: Path,
    root_handles: tuple[NativeResourceRootHandle, ...],
    package_resources: tuple[AdmittedPackageResource, ...] = (),
    product_snapshot_resources: tuple[ProductSelectedResourceInput, ...] = (),
    embedded_collections: tuple[EmbeddedResourceCollectionHandle, ...] = (),
    context_file_names: tuple[str, ...] = DEFAULT_CONTEXT_FILE_NAMES,
    disabled_skill_selectors: Sequence[str] = (),
) -> ResourceBundle:
    return prepare_resource_catalog_bootstrap_result(
        product_id=product_id,
        runtime_id=runtime_id,
        product_policy_revision=product_policy_revision,
        cwd=cwd,
        root_handles=root_handles,
        package_resources=package_resources,
        product_snapshot_resources=product_snapshot_resources,
        embedded_collections=embedded_collections,
        context_file_names=context_file_names,
        disabled_skill_selectors=disabled_skill_selectors,
    ).bundle


def prepare_resource_catalog_bootstrap_result(
    *,
    product_id: str,
    runtime_id: str,
    product_policy_revision: str,
    cwd: Path,
    root_handles: tuple[NativeResourceRootHandle, ...],
    package_resources: tuple[AdmittedPackageResource, ...] = (),
    product_snapshot_resources: tuple[ProductSelectedResourceInput, ...] = (),
    embedded_collections: tuple[EmbeddedResourceCollectionHandle, ...] = (),
    context_file_names: tuple[str, ...] = DEFAULT_CONTEXT_FILE_NAMES,
    disabled_skill_selectors: Sequence[str] = (),
) -> ResourceCatalogBootstrapResult:
    """Build a disposable Catalog projection for synchronous Session bootstrap.

    This projection exists only to seed Extension activation and initial prompt
    construction.  It uses the same Catalog sources and merge policy as the
    owner generation, owns no live publication, and disposes every source lease
    before returning the immutable compatibility copy.
    """

    if any(item.admission.product_id != product_id for item in product_snapshot_resources):
        raise ValueError("Product snapshot Resources must match Product")
    if package_resources and product_snapshot_resources:
        raise ValueError("Legacy package and Product snapshot routes cannot mix")

    source_snapshots: list[ResourceSourceSnapshot] = []
    descriptor_bindings: list[ResourceProjectionDescriptorBinding] = []
    sources: list[
        NativeFilesystemResourceSource
        | AdmittedPackageResourceSource
        | ProductSelectedResourceSource
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

        if product_snapshot_resources:
            binding = _preflight_binding_fingerprint(
                product_id=product_id,
                runtime_id=runtime_id,
                source_id="harness.resources.source.product_snapshot",
            )
            source_ref = ResourceSourceGenerationRef(
                source_id="harness.resources.source.product_snapshot",
                product_id=product_id,
                generation=f"{runtime_id}:{_PREFLIGHT_GENERATION}",
                source_policy_fingerprint=product_snapshot_source_policy_fingerprint(
                    product_id=product_id,
                    resources=product_snapshot_resources,
                ),
                producer=_preflight_producer(binding, "product_snapshot"),
            )
            product_source = ProductSelectedResourceSource(
                source_generation_ref=source_ref,
                resources=product_snapshot_resources,
            )
            sources.append(product_source)
            source_snapshots.append(
                product_source.discover_initial(
                    build_package_resource_discovery_request(
                        product_id=product_id,
                        source_generation_ref=source_ref,
                        admission_fingerprints=tuple(
                            item.admission.fingerprint
                            for item in product_snapshot_resources
                        ),
                    )
                )
            )
            descriptor_bindings.extend(product_source.projection_bindings)

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
        return ResourceCatalogBootstrapResult(bundle=bundle, catalog=snapshot)
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
