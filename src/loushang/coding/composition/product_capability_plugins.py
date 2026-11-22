"""Approved first-party Capability declarations from a live Product Store."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

from loushang.coding.composition.base_product import (
    CodingBaseProductCompilation,
    CodingBaseProductSessionAssembly,
    _bind_coding_external_resource_owners,
)
from loushang.coding.composition.base_product import (
    _resource_bodies as _resource_bodies,
)
from loushang.coding.composition.capability_plugins import (
    _PRODUCT_POLICY_REVISION,
    CodingCapabilityPluginCompositionAssembly,
    CodingCapabilityPluginCompositionPreparation,
    CodingResumePluginParents,
    _capability_configuration_entries,
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
    CodingCapabilityPluginSpec,
)
from loushang.coding.composition.capability_specs import (
    ordered_coding_capability_plugin_specs as ordered_coding_capability_plugin_specs,
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
from loushang.harness.resources.packages._private_tree_windows import (
    prepare_private_windows_directory_chain,
)
from loushang.harness.resources.plugins.authority import PluginRuntimeResolution
from loushang.harness.resources.plugins.selection import (
    PluginPreflightContextV1,
    PluginSelectionPlanV2,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import PublishedPluginPackage
from loushang.harness.session.product_composition_assembly import (
    ProductContributionOwnerBinding,
    ProductPluginPlanSeed,
    project_product_owner_candidates,
)
from loushang.harness.session.product_composition_assembly import (
    prepare_product_plugin_composition as prepare_product_plugin_composition,
)

_MAX_FILES = 64
_MAX_BYTES = 1024 * 1024


def coding_session_plugin_state_relative_path(session_id: str) -> Path:
    """Return the historical Product Plugin location without creating it."""
    state_id = hashlib.sha256(
        b"loushang.coding-capability-plugin-state/v1\0" + session_id.encode("utf-8")
    ).hexdigest()
    return Path("plugin-state", "coding-capability-plugins", state_id)


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

    if not isinstance(base_compilation, CodingBaseProductCompilation):
        raise TypeError("Coding Product base compilation is invalid")
    return cast(
        CodingBuiltinProductCompositionPreparation,
        _prepare_fenced_capabilities(
            product_runtime,
            session_id=session_id,
            configurations=configurations,
            state_root=state_root,
            clock=clock,
            resume_parents=resume_parents,
            base_compilation=base_compilation,
            external_data_plugin_ids=external_data_plugin_ids,
        ),
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

    return cast(
        CodingCapabilityPluginCompositionPreparation,
        _prepare_fenced_capabilities(
            product_runtime,
            session_id=session_id,
            configurations=configurations,
            state_root=state_root,
            clock=clock,
            resume_parents=resume_parents,
            product_policy_revision=product_policy_revision,
        ),
    )


def _prepare_fenced_capabilities(
    product_runtime: PackageProductRuntimeBindingV1,
    *,
    session_id: str,
    configurations: Mapping[str, CodingCapabilityPluginConfig],
    state_root: Path,
    clock: Callable[[], int],
    resume_parents: CodingResumePluginParents | None,
    product_policy_revision: str = _PRODUCT_POLICY_REVISION,
    base_compilation: CodingBaseProductCompilation | None = None,
    external_data_plugin_ids: tuple[str, ...] = (),
) -> (
    CodingCapabilityPluginCompositionPreparation
    | CodingBuiltinProductCompositionPreparation
):
    if not isinstance(session_id, str) or not session_id.strip():
        if base_compilation is None:
            raise ValueError("Coding Product Capability Session id is invalid")
        raise ValueError("Coding Product Session id is invalid")
    if not isinstance(configurations, Mapping) or not configurations:
        raise ValueError("Coding Product Capability configuration is invalid")
    specs = ordered_coding_capability_plugin_specs(configurations)
    if any(
        not isinstance(configurations[spec.plugin_id], spec.configuration_type)
        for spec in specs
    ):
        raise TypeError("Coding Product Capability configuration type is invalid")
    if base_compilation is None and (
        not isinstance(product_policy_revision, str) or not product_policy_revision
    ):
        raise ValueError("Coding Product Capability policy revision is invalid")
    _read_clock(clock)
    root = _prepare_product_approval_state_root(state_root)

    def open_runtime() -> PluginRuntimeResolution:
        plugin_ids = tuple(spec.plugin_id for spec in specs)
        if base_compilation is None:
            return open_coding_product_capability_resolution(
                product_runtime, plugin_ids=plugin_ids
            )
        return open_coding_product_builtin_resolution(
            product_runtime,
            capability_plugin_ids=plugin_ids,
            external_data_plugin_ids=external_data_plugin_ids,
        )

    capture: SelectedProductPreparationScope[
        CodingCapabilityPluginSpec | PublishedPluginPackage
    ] = SelectedProductPreparationScope(
        product_runtime=product_runtime,
        open_runtime=open_runtime,
        selection_id=lambda item: (
            item.plugin_id
            if isinstance(item, CodingCapabilityPluginSpec)
            else item.manifest.name
        ),
        selection_items=lambda runtime: (
            specs if base_compilation is None else runtime.packages
        ),
        maximum_files=lambda: _MAX_FILES,
        maximum_bytes=lambda: _MAX_BYTES,
        label="Coding Product Capability",
    )
    with capture as (runtime, selected):
        base = None
        if base_compilation is None:
            trust_revisions = {
                item.source_trust_snapshot.source_trust_policy_revision
                for item in selected
                if item.source_trust_snapshot is not None
            }
            if len(trust_revisions) != 1:
                raise ValueError("Coding Product Capability trust policy changed")
        else:
            by_id = {item.manifest.name: item for item in selected}
            base = by_id["coding.base"]
            if (
                base != base_compilation.selected_manifest
                or base_compilation.plan.selected_plugin_ids != ("coding.base",)
                or base_compilation.plan.context.scope_id
                != f"session:{session_id.strip()}"
            ):
                raise ValueError("Coding Product base selection changed")
            trust_revisions = {
                _required_trust(item).source_trust_policy_revision for item in selected
            }
            if len(trust_revisions) != 1:
                raise ValueError("Coding Product trust policy changed")
        plugin_ids = frozenset(configurations)
        if base_compilation is None:
            scope_id = f"session:{session_id.strip()}"
        else:
            scope_id = base_compilation.plan.context.scope_id
            product_policy_revision = base_compilation.plan.context.policy_revision
        tool_authority = _tool_owner_authority(plugin_ids)
        seed = _product_plan_seed(
            runtime,
            selected,
            configurations=configurations,
            scope_id=scope_id,
            product_policy_revision=product_policy_revision,
            tool_authority=tool_authority,
            base_compilation=base_compilation,
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
            resume_parents=resume_parents,
        )
        provider_authorities = _provider_owner_authorities(plugin_ids)
        selected_seed = complete_coding_package_plugin_selection_seed(
            seed, selection=selection
        )
        external_selected = (
            tuple(by_id[item] for item in external_data_plugin_ids)
            if base is not None
            else ()
        )
        owner_candidates = (
            project_product_owner_candidates(
                selection,
                selected_manifests=(base, *external_selected),
                selection_changed="Coding Product base owner changed Store selection",
            )
            if base is not None
            else None
        )
        product = prepare_product_plugin_composition(
            _assembly_request(
                selected_seed,
                provider_authorities=provider_authorities,
                owner_candidates=owner_candidates,
            ),
            evaluated_at=_read_clock(clock),
        )
        capability_preparation = CodingCapabilityPluginCompositionPreparation(
            request=request,
            runtime=runtime,
            selection=selection,
            product=product,
            provider_owner_authorities=provider_authorities,
            tool_owner_authority=tool_authority,
            scope_id=scope_id,
            state_root=root,
            selection_recheck=selected_runtime_recheck(runtime),
            resume_parents=resume_parents,
        )
        if base_compilation is None:
            return capability_preparation
        assert base is not None
        combined_base = replace(
            base_compilation,
            plan=selection.plan,
            product_composition=product.product_composition,
            owner_bindings=selected_seed.owner_bindings,
            resource_bodies=_resource_bodies(
                base,
                product.product_composition,
                external_selected=external_selected,
            ),
            selected_capability_manifests=tuple(
                by_id[plugin_id] for plugin_id in sorted(plugin_ids)
            ),
            selected_external_data_manifests=external_selected,
        )
        return CodingBuiltinProductCompositionPreparation(
            base_compilation=combined_base,
            capability_preparation=capability_preparation,
        )


def _validate_product_lineage(
    runtime: PluginRuntimeResolution,
    selected: tuple[PackageProductSelectedPluginManifestV1, ...],
) -> None:
    validate_preparation_lineage(runtime, selected, label="Coding Product Capability")


def _fenced_selection_plan(
    selected: tuple[PackageProductSelectedPluginManifestV1, ...],
    packages: Iterable[PublishedPluginPackage],
    *,
    configurations: Mapping[str, CodingCapabilityPluginConfig],
    product_id: str,
    scope_id: str,
    policy_revision: str,
    base: PluginSelectionPlanV2 | None = None,
) -> PluginSelectionPlanV2:
    by_id = {item.manifest.name: item for item in selected}
    selected_ids = tuple(sorted(by_id))
    return PluginSelectionPlanV2.from_selected_entries(
        PluginPreflightContextV1(
            product_id=product_id,
            scope_id=scope_id,
            policy_revision=policy_revision,
            instance_revision_refs=tuple(
                by_id[plugin_id].snapshot.instance_revision_ref
                for plugin_id in selected_ids
            ),
        ),
        selected_plugin_ids=selected_ids,
        source_trust_snapshots=tuple(
            _required_trust(by_id[plugin_id]) for plugin_id in selected_ids
        ),
        additions=_capability_configuration_entries(packages, configurations),
        allowed_authority_ceiling=("filesystem", "process"),
        base=base,
    )


def _product_plan_seed(
    runtime: PluginRuntimeResolution,
    selected: tuple[PackageProductSelectedPluginManifestV1, ...],
    *,
    configurations: Mapping[str, CodingCapabilityPluginConfig],
    scope_id: str,
    product_policy_revision: str,
    tool_authority: OwnerContributionAuthority,
    base_compilation: CodingBaseProductCompilation | None = None,
) -> ProductPluginPlanSeed:
    pairs = tuple(
        sorted(
            zip(runtime.packages, runtime.bindings, strict=True),
            key=lambda item: item[0].manifest.name,
        )
    )
    base_plan = None
    base_owner_bindings: tuple[ProductContributionOwnerBinding, ...] = ()
    selected_data_ids: set[str] = set()
    if base_compilation is not None:
        base_plan = base_compilation.plan
        selected_data_ids, base_owner_bindings = _builtin_data_owner_bindings(
            base_compilation, selected
        )
    plan = _fenced_selection_plan(
        selected,
        (
            package
            for package, _ in pairs
            if base_plan is None
            or package.manifest.name in configurations
            or package.manifest.name in selected_data_ids
        ),
        configurations=configurations,
        product_id="coding" if base_plan is None else base_plan.context.product_id,
        scope_id=scope_id,
        policy_revision=product_policy_revision,
        base=base_plan,
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


def _builtin_data_owner_bindings(
    base_compilation: CodingBaseProductCompilation,
    selected: tuple[PackageProductSelectedPluginManifestV1, ...],
) -> tuple[set[str], tuple[ProductContributionOwnerBinding, ...]]:
    selected_data_ids: set[str] = set()
    external_trust_by_owner: dict[str, set[str]] = {}
    for item in selected:
        trust = item.source_trust_snapshot
        if trust is None or trust.source_trust_class not in EXTERNAL_DATA_TRUST_CLASSES:
            continue
        owners = tuple(
            reservation.owner
            for reservation, _ in item.verified_data_only_declarations()
        )
        if not all(
            permits_external_data_owner(trust.source_trust_class, owner)
            for owner in owners
        ):
            continue
        selected_data_ids.add(item.manifest.name)
        for owner in owners:
            external_trust_by_owner.setdefault(owner, set()).add(
                trust.source_trust_class
            )

    for admission in base_compilation.product_composition.resource_admissions:
        if (
            admission.plugin_id == "coding.base"
            and admission.owner_id in external_trust_by_owner
        ):
            external_trust_by_owner[admission.owner_id].add("host-equivalent-local")
    base_owner_bindings = _bind_coding_external_resource_owners(
        base_compilation.owner_bindings,
        {
            owner: tuple(sorted(classes))
            for owner, classes in external_trust_by_owner.items()
        },
    )
    return selected_data_ids, base_owner_bindings


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
