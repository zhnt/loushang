"""Approved first-party Capability declarations from a live Product Store."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from loushang.coding.composition.base_plugin import _owner_bindings
from loushang.coding.composition.base_product import (
    CodingBaseProductCompilation,
    CodingBaseProductSessionAssembly,
)
from loushang.coding.composition.base_product import (
    _resource_bodies as _resource_bodies,
)
from loushang.coding.composition.capability_plugins import (
    _PRODUCT_POLICY_REVISION,
    CodingCapabilityPluginCompositionAssembly,
    CodingCapabilityPluginCompositionPreparation,
    CodingResumePluginParents,
)
from loushang.coding.composition.capability_plugins import (
    _assembly_request as _assembly_request,
)
from loushang.coding.composition.capability_plugins import (
    _bind_default_approval_request_to_plan as _bind_default_approval_request_to_plan,
)
from loushang.coding.composition.capability_plugins import (
    _finalize_selection as _finalize_selection,
)
from loushang.coding.composition.capability_plugins import (
    _provider_owner_authorities as _provider_owner_authorities,
)
from loushang.coding.composition.capability_plugins import (
    _read_clock as _read_clock,
)
from loushang.coding.composition.capability_plugins import (
    _tool_owner_authority as _tool_owner_authority,
)
from loushang.coding.composition.capability_plugins import (
    create_coding_capability_plugin_composition_request as create_coding_capability_plugin_composition_request,
)
from loushang.coding.composition.capability_specs import (
    CodingCapabilityPluginConfig,
)
from loushang.coding.composition.capability_specs import (
    ordered_coding_capability_plugin_specs as ordered_coding_capability_plugin_specs,
)
from loushang.coding.harness.session import (
    selected_plugin_preparation as _preparation_programs,
)
from loushang.coding.package.legacy_data_trust import (
    EXTERNAL_DATA_TRUST_CLASSES,
    permits_external_data_owner,
)
from loushang.coding.package.product_revisions import (
    open_coding_product_builtin_resolution as open_coding_product_builtin_resolution,
)
from loushang.coding.package.product_revisions import (
    open_coding_product_capability_resolution as open_coding_product_capability_resolution,
)
from loushang.coding.resources.catalog import (
    complete_coding_package_plugin_selection_seed as complete_coding_package_plugin_selection_seed,
)
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
from loushang.harness.package_product._selected_plugin_revisions import (
    SelectedProductPreparationScope as SelectedProductPreparationScope,
)
from loushang.harness.package_product._selected_plugin_revisions import (
    selected_runtime_recheck as selected_runtime_recheck,
)
from loushang.harness.package_product._selected_plugin_revisions import (
    validate_preparation_lineage,
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
from loushang.harness.resources.packages._private_tree_windows import (
    prepare_private_windows_directory_chain,
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
)
from loushang.harness.session.product_composition_assembly import (
    prepare_product_plugin_composition as prepare_product_plugin_composition,
)

_MAX_FILES = 64
_MAX_BYTES = 1024 * 1024


_PLUGIN_PREPARATION_PROGRAM_VALUES = {
    "value_001": "Coding Product base compilation is invalid",
    "value_002": "Coding Product Session id is invalid",
    "value_003": "Coding Product Capability configuration is invalid",
    "value_004": "Coding Product Capability configuration type is invalid",
    "value_005": "coding.base",
    "value_006": "Coding Product Capability",
    "value_007": "Coding Product base selection changed",
    "value_008": "Coding Product trust policy changed",
    "value_009": "Coding Product Capability Session id is invalid",
    "value_010": "Coding Product Capability policy revision is invalid",
    "value_011": "Coding Product Capability trust policy changed",
}


def prepare_coding_product_approval_state_root(state_root: Path) -> Path:
    """Prepare the canonical native approval root on this host platform."""

    if os.name == "nt":
        return _prepare_windows_product_approval_state_root(state_root)
    if os.name != "posix":
        raise RuntimeError("Coding Product approval state needs a native owner")
    root = prepare_private_directory_chain(state_root)
    metadata = root.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise ValueError("Coding Product approval state is not private")
    return root


def _prepare_product_approval_state_root(state_root: Path) -> Path:
    """Compatibility alias for existing internal callers and tests."""

    return prepare_coding_product_approval_state_root(state_root)


def _prepare_windows_product_approval_state_root(state_root: Path) -> Path:
    if not isinstance(state_root, Path) or not state_root.is_absolute():
        raise ValueError("Coding Product approval state root is invalid")
    return prepare_private_windows_directory_chain(
        state_root / "product-private",
        max_missing=8,
        label="Coding Product approval state",
    )


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
    external_data_plugin_ids: tuple[str, ...] = (),
    state_root: Path,
    clock: Callable[[], int],
    resume_parents: CodingResumePluginParents | None = None,
) -> CodingBuiltinProductCompositionPreparation:
    """Compile all first-party Product selections before binding host Providers."""

    return _preparation_programs.prepare_builtin_plugins(
        product_runtime,
        base_compilation=base_compilation,
        session_id=session_id,
        configurations=configurations,
        external_data_plugin_ids=external_data_plugin_ids,
        state_root=state_root,
        clock=clock,
        resume_parents=resume_parents,
    )


def prepare_coding_product_capability_plugin_composition(
    product_runtime: PackageProductRuntimeBindingV1,
    *,
    session_id: str,
    configurations: Mapping[str, CodingCapabilityPluginConfig],
    state_root: Path,
    clock: Callable[[], int],
    product_policy_revision: str = _PRODUCT_POLICY_REVISION,
    resume_parents: CodingResumePluginParents | None = None,
) -> CodingCapabilityPluginCompositionPreparation:
    """Approve exact B-selected Definitions and compile inert Provider inputs.

    The Product runtime owns Store selection and its lease. This preparation
    owns only verified revision handles and Approval journals; activation still
    requires the normal host-Provider binding and Session graph publication.
    """

    return _preparation_programs.prepare_selected_plugins(
        product_runtime,
        session_id=session_id,
        configurations=configurations,
        state_root=state_root,
        clock=clock,
        product_policy_revision=product_policy_revision,
        resume_parents=resume_parents,
    )


def _validate_product_lineage(
    runtime: PluginRuntimeResolution,
    selected: tuple[PackageProductSelectedPluginManifestV1, ...],
) -> None:
    validate_preparation_lineage(runtime, selected, label="Coding Product Capability")


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
    selected_data_ids = {
        item.manifest.name
        for item in selected
        if item.source_trust_snapshot is not None
        and item.source_trust_snapshot.source_trust_class in EXTERNAL_DATA_TRUST_CLASSES
        and all(
            permits_external_data_owner(
                item.source_trust_snapshot.source_trust_class,
                reservation.owner,
            )
            for reservation, _ in item.verified_data_only_declarations()
        )
    }
    external_data_owners = {
        reservation.owner
        for item in selected
        if item.manifest.name in selected_data_ids
        for reservation, _ in item.verified_data_only_declarations()
    }
    missing_data_owners = external_data_owners - {
        item.owner_key[0] for item in base_compilation.owner_bindings
    }
    initial_owner_bindings = (
        *base_compilation.owner_bindings,
        *(
            _owner_bindings(
                include_tools=False,
                include_prompt="resources.prompt" in missing_data_owners,
                include_skill="resources.skill" in missing_data_owners,
                include_theme="resources.theme" in missing_data_owners,
                include_command=False,
            )
            if missing_data_owners
            else ()
        ),
    )
    base_owner_bindings = tuple(
        ProductContributionOwnerBinding(
            authority=OwnerContributionAuthority(
                replace(
                    binding.authority.policy,
                    allowed_source_trust_classes=tuple(
                        sorted(
                            (
                                {"host-equivalent-local"}
                                if any(
                                    item.plugin_id == "coding.base"
                                    and item.owner_id == binding.owner_key[0]
                                    for item in base_compilation.product_composition.resource_admissions
                                )
                                else set()
                            )
                            | {
                                item.source_trust_snapshot.source_trust_class
                                for item in selected
                                if item.manifest.name in selected_data_ids
                                and item.source_trust_snapshot is not None
                                and any(
                                    reservation.owner == binding.owner_key[0]
                                    for reservation, _ in item.verified_data_only_declarations()
                                )
                            }
                        )
                    ),
                )
            ),
            admission_ttl_seconds=binding.admission_ttl_seconds,
        )
        if binding.owner_key[0] in external_data_owners
        else binding
        for binding in initial_owner_bindings
    )
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
                        or package.manifest.name in selected_data_ids
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
                            or package.manifest.name in selected_data_ids
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
            *base_owner_bindings,
            ProductContributionOwnerBinding(authority=tool_authority),
        ),
    )


def _selected_store_owner_candidates(
    selection: PluginSelection,
    *,
    base: PackageProductSelectedPluginManifestV1,
    selected: tuple[PackageProductSelectedPluginManifestV1, ...] = (),
) -> tuple[OwnerContributionCandidateEnvelope, ...]:
    """Carry B's lock digest without changing Plugin declaration facts."""

    snapshots = {item.manifest.name: item.snapshot for item in (base, *selected)}
    candidates = tuple(
        prepare_owner_contribution_candidate(selection, item)
        for item in selection.candidates
        if item.declaration.kind in PLUGIN_OWNER_CONTRIBUTION_KINDS
    )
    projected: list[OwnerContributionCandidateEnvelope] = []
    for candidate in candidates:
        snapshot = snapshots.get(candidate.plugin_id)
        if snapshot is None:
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
