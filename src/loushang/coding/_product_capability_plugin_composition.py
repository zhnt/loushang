"""Approved first-party Capability declarations from a live Product Store."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority,
    OwnerContributionCandidateEnvelope,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.machine_resources.control_plane import (
    prepare_private_directory_chain,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.plugin_authoring.contribution_admission import (
    prepare_owner_contribution_candidate,
)
from loushang.harness.resources.plugins.authority import PluginRuntimeResolution
from loushang.harness.resources.plugins.contribution_types import (
    PLUGIN_OWNER_CONTRIBUTION_KINDS,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginPreflightContextV1,
    PluginSelection,
    PluginSelectionPlanV2,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.session.product_composition_assembly import (
    ProductContributionOwnerBinding,
    ProductPluginPlanSeed,
    prepare_product_plugin_composition,
)

from ._base_product_composition import (
    CodingBaseProductCompilation,
    CodingBaseProductSessionAssembly,
    _resource_bodies,
)
from ._capability_plugin_composition import (
    CodingCapabilityPluginCompositionAssembly,
    CodingCapabilityPluginCompositionPreparation,
    _assembly_request,
    _bind_default_approval_request_to_plan,
    _finalize_selection,
    _provider_owner_authorities,
    _read_clock,
    _tool_owner_authority,
    create_coding_capability_plugin_composition_request,
)
from ._capability_plugin_specs import (
    CodingCapabilityPluginConfig,
    ordered_coding_capability_plugin_specs,
)
from ._resource_catalog_shadow import (
    complete_coding_package_plugin_selection_seed,
)
from .package_product_revisions import (
    open_coding_product_builtin_resolution,
    open_coding_product_capability_resolution,
)

_MAX_FILES = 64
_MAX_BYTES = 1024 * 1024


@dataclass(slots=True)
class CodingBuiltinProductCompositionPreparation:
    """One Product composition shared by base resources and Capability owners."""

    base_compilation: CodingBaseProductCompilation
    capability_preparation: CodingCapabilityPluginCompositionPreparation = field(
        repr=False
    )

    def bind_workspace(
        self,
        workspace_binding: CapabilityBundleProviderBinding,
        *,
        host_boot_id: str,
        tool_modes: Mapping[str, CapabilityMountMode],
        clock: Callable[[], int],
    ) -> CodingBuiltinProductSessionAssembly:
        capability_assembly = self.capability_preparation.bind_workspace(
            workspace_binding,
            host_boot_id=host_boot_id,
            tool_modes=tool_modes,
            clock=clock,
        )
        return CodingBuiltinProductSessionAssembly(
            base_session=CodingBaseProductSessionAssembly(
                compilation=self.base_compilation,
                workspace_binding=workspace_binding,
                session_inputs=capability_assembly.session_inputs,
            ),
            capability_assembly=capability_assembly,
        )

    def close(self) -> None:
        self.capability_preparation.close()


@dataclass(slots=True)
class CodingBuiltinProductSessionAssembly:
    base_session: CodingBaseProductSessionAssembly
    capability_assembly: CodingCapabilityPluginCompositionAssembly

    def abort_unpublished(self) -> None:
        self.capability_assembly.abort_unpublished()


def prepare_coding_builtin_product_composition(
    product_runtime: PackageProductRuntimeBindingV1,
    *,
    base_compilation: CodingBaseProductCompilation,
    session_id: str,
    configurations: Mapping[str, CodingCapabilityPluginConfig],
    state_root: Path,
    clock: Callable[[], int],
) -> CodingBuiltinProductCompositionPreparation:
    """Compile all first-party Product selections before binding host Providers."""

    if not isinstance(base_compilation, CodingBaseProductCompilation):
        raise TypeError("Coding Product base compilation is invalid")
    if os.name != "posix":
        raise RuntimeError("Coding Product composition requires POSIX")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Coding Product Session id is invalid")
    if not isinstance(configurations, Mapping) or frozenset(configurations) != {
        "coding.lsp.default",
        "coding.arch.default",
    }:
        raise ValueError("Coding Product Capability configuration is incomplete")
    specs = ordered_coding_capability_plugin_specs(configurations)
    if any(
        not isinstance(configurations[spec.plugin_id], spec.configuration_type)
        for spec in specs
    ):
        raise TypeError("Coding Product Capability configuration type is invalid")
    _read_clock(clock)
    root = prepare_private_directory_chain(state_root)
    metadata = root.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise ValueError("Coding Product approval state is not private")

    runtime = open_coding_product_builtin_resolution(product_runtime)
    try:
        selected = tuple(
            product_runtime.capture_selected_plugin_manifest_for(
                package.manifest.name,
                max_files=_MAX_FILES,
                max_total_bytes=_MAX_BYTES,
            )
            for package in runtime.packages
        )
        _validate_product_lineage(runtime, selected)
        by_id = {item.manifest.name: item for item in selected}
        base = by_id["coding.base"]
        if (
            base != base_compilation.selected_manifest
            or base_compilation.plan.selected_plugin_ids != ("coding.base",)
            or base_compilation.plan.context.scope_id != f"session:{session_id.strip()}"
        ):
            raise ValueError("Coding Product base selection changed")
        trust_revisions = {
            _required_trust(item).source_trust_policy_revision for item in selected
        }
        if len(trust_revisions) != 1:
            raise ValueError("Coding Product trust policy changed")
        plugin_ids = frozenset(configurations)
        scope_id = base_compilation.plan.context.scope_id
        policy_revision = base_compilation.plan.context.policy_revision
        tool_authority = _tool_owner_authority(plugin_ids)
        seed = _builtin_plan_seed(
            runtime,
            selected,
            base_compilation=base_compilation,
            configurations=configurations,
            tool_authority=tool_authority,
        )
        request = _bind_default_approval_request_to_plan(
            create_coding_capability_plugin_composition_request(
                clock=clock,
                plugin_ids=plugin_ids,
                product_policy_revision=policy_revision,
                source_trust_policy_revision=next(iter(trust_revisions)),
            ),
            seed,
        )
        selection = _finalize_selection(
            seed,
            request=request,
            scope_id=scope_id,
            state_root=root,
            clock=clock,
        )
        provider_authorities = _provider_owner_authorities(plugin_ids)
        selected_seed = complete_coding_package_plugin_selection_seed(
            seed, selection=selection
        )
        product = prepare_product_plugin_composition(
            _assembly_request(
                selected_seed,
                provider_authorities=provider_authorities,
                owner_candidates=_selected_store_owner_candidates(selection, base=base),
            ),
            evaluated_at=_read_clock(clock),
        )

        def recheck_selected_revisions() -> None:
            for package in runtime.packages:
                package.revision_handle.verify()

        capability_preparation = CodingCapabilityPluginCompositionPreparation(
            request=request,
            runtime=runtime,
            selection=selection,
            product=product,
            provider_owner_authorities=provider_authorities,
            tool_owner_authority=tool_authority,
            scope_id=scope_id,
            state_root=root,
            selection_recheck=recheck_selected_revisions,
        )
        combined_base = replace(
            base_compilation,
            plan=selection.plan,
            product_composition=product.product_composition,
            owner_bindings=selected_seed.owner_bindings,
            resource_bodies=_resource_bodies(base, product.product_composition),
        )
        return CodingBuiltinProductCompositionPreparation(
            base_compilation=combined_base,
            capability_preparation=capability_preparation,
        )
    except BaseException:
        runtime.close()
        raise


def prepare_coding_product_capability_plugin_composition(
    product_runtime: PackageProductRuntimeBindingV1,
    *,
    session_id: str,
    configurations: Mapping[str, CodingCapabilityPluginConfig],
    state_root: Path,
    clock: Callable[[], int],
    product_policy_revision: str,
) -> CodingCapabilityPluginCompositionPreparation:
    """Approve exact B-selected Definitions and compile inert Provider inputs.

    The Product runtime owns Store selection and its lease. This preparation
    owns only verified revision handles and Approval journals; activation still
    requires the normal host-Provider binding and Session graph publication.
    """

    if os.name != "posix":
        raise RuntimeError("Coding Product Capability composition requires POSIX")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Coding Product Capability Session id is invalid")
    if not isinstance(configurations, Mapping) or not configurations:
        raise ValueError("Coding Product Capability configuration is invalid")
    specs = ordered_coding_capability_plugin_specs(configurations)
    if any(
        not isinstance(configurations[spec.plugin_id], spec.configuration_type)
        for spec in specs
    ):
        raise TypeError("Coding Product Capability configuration type is invalid")
    if not isinstance(product_policy_revision, str) or not product_policy_revision:
        raise ValueError("Coding Product Capability policy revision is invalid")
    _read_clock(clock)
    root = prepare_private_directory_chain(state_root)
    metadata = root.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise ValueError("Coding Product Capability approval state is not private")

    runtime = open_coding_product_capability_resolution(
        product_runtime, plugin_ids=tuple(spec.plugin_id for spec in specs)
    )
    try:
        selected = tuple(
            product_runtime.capture_selected_plugin_manifest_for(
                spec.plugin_id,
                max_files=_MAX_FILES,
                max_total_bytes=_MAX_BYTES,
            )
            for spec in specs
        )
        _validate_product_lineage(runtime, selected)
        trust_revisions = {
            item.source_trust_snapshot.source_trust_policy_revision
            for item in selected
            if item.source_trust_snapshot is not None
        }
        if len(trust_revisions) != 1:
            raise ValueError("Coding Product Capability trust policy changed")
        plugin_ids = frozenset(configurations)
        scope_id = f"session:{session_id.strip()}"
        tool_authority = _tool_owner_authority(plugin_ids)
        seed = _product_plan_seed(
            runtime,
            selected,
            configurations=configurations,
            scope_id=scope_id,
            product_policy_revision=product_policy_revision,
            tool_authority=tool_authority,
        )
        request = _bind_default_approval_request_to_plan(
            create_coding_capability_plugin_composition_request(
                clock=clock,
                plugin_ids=plugin_ids,
                product_policy_revision=product_policy_revision,
                source_trust_policy_revision=next(iter(trust_revisions)),
            ),
            seed,
        )
        selection = _finalize_selection(
            seed,
            request=request,
            scope_id=scope_id,
            state_root=root,
            clock=clock,
        )
        provider_authorities = _provider_owner_authorities(plugin_ids)
        product = prepare_product_plugin_composition(
            _assembly_request(
                complete_coding_package_plugin_selection_seed(
                    seed, selection=selection
                ),
                provider_authorities=provider_authorities,
            ),
            evaluated_at=_read_clock(clock),
        )

        def recheck_selected_revisions() -> None:
            for package in runtime.packages:
                package.revision_handle.verify()

        return CodingCapabilityPluginCompositionPreparation(
            request=request,
            runtime=runtime,
            selection=selection,
            product=product,
            provider_owner_authorities=provider_authorities,
            tool_owner_authority=tool_authority,
            scope_id=scope_id,
            state_root=root,
            selection_recheck=recheck_selected_revisions,
        )
    except BaseException:
        runtime.close()
        raise


def _validate_product_lineage(
    runtime: PluginRuntimeResolution,
    selected: tuple[PackageProductSelectedPluginManifestV1, ...],
) -> None:
    if len(runtime.packages) != len(selected):
        raise ValueError("Coding Product Capability selection is incomplete")
    for package, binding, item in zip(
        runtime.packages, runtime.bindings, selected, strict=True
    ):
        item.verified_manifest()
        if (
            package.manifest.name != item.manifest.name
            or package.content_digest != item.snapshot.root_ref.artifact_digest
            or binding.source_identity
            != item.snapshot.package_revision.package_source_identity
            or item.source_trust_snapshot is None
        ):
            raise ValueError("Coding Product Capability revision changed")
        package.revision_handle.verify()


def _product_plan_seed(
    runtime: PluginRuntimeResolution,
    selected: tuple[PackageProductSelectedPluginManifestV1, ...],
    *,
    configurations: Mapping[str, CodingCapabilityPluginConfig],
    scope_id: str,
    product_policy_revision: str,
    tool_authority: OwnerContributionAuthority,
) -> ProductPluginPlanSeed:
    by_id = {item.manifest.name: item for item in selected}
    pairs = tuple(
        sorted(
            zip(runtime.packages, runtime.bindings, strict=True),
            key=lambda item: item[0].manifest.name,
        )
    )
    plan = PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="coding",
            scope_id=scope_id,
            policy_revision=product_policy_revision,
            instance_revision_refs=tuple(
                by_id[plugin_id].snapshot.instance_revision_ref
                for plugin_id in sorted(by_id)
            ),
        ),
        selected_plugin_ids=tuple(sorted(by_id)),
        selected_contributions=tuple(
            sorted(
                PluginContributionRef(package.manifest.name, item.contribution_id)
                for package, _ in pairs
                for item in package.contribution_index.items
            )
        ),
        source_trust_snapshots=tuple(
            _required_trust(by_id[plugin_id]) for plugin_id in sorted(by_id)
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(
                sorted(
                    (
                        PluginEffectiveConfigurationEntry(
                            plugin_id=package.manifest.name,
                            contribution_id=item.contribution_id,
                            configuration=(
                                configurations[package.manifest.name].to_dict()
                                if item.kind == "capability_provider"
                                else {}
                            ),
                        )
                        for package, _ in pairs
                        for item in package.contribution_index.items
                    ),
                    key=lambda item: (item.plugin_id, item.contribution_id),
                )
            ),
        ),
        allowed_authority_ceiling=("filesystem", "process"),
    )
    return ProductPluginPlanSeed(
        plan=plan,
        packages=tuple(package for package, _ in pairs),
        bindings=tuple(binding for _, binding in pairs),
        owner_bindings=(ProductContributionOwnerBinding(authority=tool_authority),),
    )


def _builtin_plan_seed(
    runtime: PluginRuntimeResolution,
    selected: tuple[PackageProductSelectedPluginManifestV1, ...],
    *,
    base_compilation: CodingBaseProductCompilation,
    configurations: Mapping[str, CodingCapabilityPluginConfig],
    tool_authority: OwnerContributionAuthority,
) -> ProductPluginPlanSeed:
    by_id = {item.manifest.name: item for item in selected}
    pairs = tuple(
        sorted(
            zip(runtime.packages, runtime.bindings, strict=True),
            key=lambda item: item[0].manifest.name,
        )
    )

    base_plan = base_compilation.plan
    plan = PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id=base_plan.context.product_id,
            scope_id=base_plan.context.scope_id,
            policy_revision=base_plan.context.policy_revision,
            instance_revision_refs=tuple(
                by_id[plugin_id].snapshot.instance_revision_ref
                for plugin_id in sorted(by_id)
            ),
        ),
        selected_plugin_ids=tuple(sorted(by_id)),
        selected_contributions=tuple(
            sorted(
                (
                    *base_plan.selected_contributions,
                    *(
                        PluginContributionRef(
                            package.manifest.name, item.contribution_id
                        )
                        for package, _ in pairs
                        if package.manifest.name in configurations
                        for item in package.contribution_index.items
                    ),
                )
            )
        ),
        source_trust_snapshots=tuple(
            _required_trust(by_id[plugin_id]) for plugin_id in sorted(by_id)
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(
                sorted(
                    (
                        *base_plan.effective_configuration_set.entries,
                        *(
                            PluginEffectiveConfigurationEntry(
                                plugin_id=package.manifest.name,
                                contribution_id=item.contribution_id,
                                configuration=(
                                    configurations[package.manifest.name].to_dict()
                                    if item.kind == "capability_provider"
                                    else {}
                                ),
                            )
                            for package, _ in pairs
                            if package.manifest.name in configurations
                            for item in package.contribution_index.items
                        ),
                    ),
                    key=lambda item: (item.plugin_id, item.contribution_id),
                )
            ),
        ),
        allowed_authority_ceiling=("filesystem", "process"),
    )
    return ProductPluginPlanSeed(
        plan=plan,
        packages=tuple(package for package, _ in pairs),
        bindings=tuple(binding for _, binding in pairs),
        owner_bindings=(
            *base_compilation.owner_bindings,
            ProductContributionOwnerBinding(authority=tool_authority),
        ),
    )


def _selected_store_owner_candidates(
    selection: PluginSelection,
    *,
    base: PackageProductSelectedPluginManifestV1,
) -> tuple[OwnerContributionCandidateEnvelope, ...]:
    """Carry B's lock digest without changing Plugin declaration facts."""

    snapshot = base.snapshot
    candidates = tuple(
        prepare_owner_contribution_candidate(selection, item)
        for item in selection.candidates
        if item.declaration.kind in PLUGIN_OWNER_CONTRIBUTION_KINDS
    )
    projected: list[OwnerContributionCandidateEnvelope] = []
    for candidate in candidates:
        if candidate.plugin_id != "coding.base":
            projected.append(candidate)
            continue
        if (
            candidate.product_id != snapshot.installation_key.product_id
            or candidate.instance_revision_ref != snapshot.instance_revision_ref
            or candidate.package_content_digest
            != snapshot.package_revision.package_content_digest
            or candidate.package_source_identity
            != snapshot.package_revision.package_source_identity
        ):
            raise ValueError("Coding Product base owner changed Store selection")
        projected.append(
            replace(
                candidate,
                dependency_lock_digest=(
                    snapshot.package_revision.dependency_lock_digest
                ),
            )
        )
    return tuple(projected)


def _required_trust(
    selected: PackageProductSelectedPluginManifestV1,
) -> PluginSourceTrustSnapshotV1:
    trust = selected.source_trust_snapshot
    if not isinstance(trust, PluginSourceTrustSnapshotV1):
        raise ValueError("Coding Product Capability trust is missing")
    return trust


__all__ = [
    "CodingBuiltinProductCompositionPreparation",
    "CodingBuiltinProductSessionAssembly",
    "prepare_coding_builtin_product_composition",
    "prepare_coding_product_capability_plugin_composition",
]
