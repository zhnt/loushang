"""Approved first-party Capability declarations from a live Product Store."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Mapping
from pathlib import Path

from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority,
)
from loushang.harness.machine_resources.control_plane import (
    prepare_private_directory_chain,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.resources.plugins.authority import PluginRuntimeResolution
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginPreflightContextV1,
    PluginSelectionPlanV2,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.session.product_composition_assembly import (
    ProductContributionOwnerBinding,
    ProductPluginPlanSeed,
    prepare_product_plugin_composition,
)

from ._capability_plugin_composition import (
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
from .package_product_capabilities import (
    open_coding_product_capability_resolution,
)

_MAX_FILES = 64
_MAX_BYTES = 1024 * 1024


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


def _required_trust(
    selected: PackageProductSelectedPluginManifestV1,
) -> PluginSourceTrustSnapshotV1:
    trust = selected.source_trust_snapshot
    if not isinstance(trust, PluginSourceTrustSnapshotV1):
        raise ValueError("Coding Product Capability trust is missing")
    return trust


__all__ = ["prepare_coding_product_capability_plugin_composition"]
