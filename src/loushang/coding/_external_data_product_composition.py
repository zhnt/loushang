"""Product-selected data Resources whose composition does not require coding.base."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256

from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionCompilation,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.resource_catalog.product_snapshot_source import (
    ProductSelectedResourceInput,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
)
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
    _assemble_product_contribution_candidates,
)

from ._base_plugin import _owner_bindings
from ._base_product_composition import (
    CodingBaseProductResourceBody,
    _candidate,
    _resource_bodies,
)
from .composition_sets import CodingCompositionSetPlan
from .package_legacy_data_trust import (
    EXTERNAL_DATA_TRUST_CLASSES,
    EXTERNAL_DATA_TRUST_CLASSES_ORDERED,
    permits_external_data_owner,
)


@dataclass(frozen=True, slots=True)
class CodingExternalDataProductCompilation:
    product_composition: ProductCompositionCompilation
    selected_manifests: tuple[PackageProductSelectedPluginManifestV1, ...]
    resource_bodies: tuple[CodingBaseProductResourceBody, ...]

    def product_resource_inputs(self) -> tuple[ProductSelectedResourceInput, ...]:
        by_id = {item.manifest.name: item for item in self.selected_manifests}
        bodies = {item.admission_fingerprint: item for item in self.resource_bodies}
        if len(bodies) != len(self.resource_bodies):
            raise ValueError("Product data Resource body identity is duplicated")
        return tuple(
            ProductSelectedResourceInput(
                admission=admission,
                selected_manifest=by_id[admission.plugin_id],
                relative_path=bodies[admission.fingerprint].logical_path,
            )
            for admission in self.product_composition.resource_admissions
        )

    def assert_current(self, runtime: PackageProductRuntimeBindingV1) -> None:
        for selected in self.selected_manifests:
            runtime.assert_selected_plugin_manifest_current(selected)


def compile_coding_external_data_product_selection(
    selected: tuple[PackageProductSelectedPluginManifestV1, ...],
    *,
    composition_set: CodingCompositionSetPlan,
    session_id: str,
    evaluated_at: int,
) -> CodingExternalDataProductCompilation:
    """Admit exact Product Store data roots without a base Plugin dependency."""

    if not selected or tuple(sorted(item.manifest.name for item in selected)) != tuple(
        item.manifest.name for item in selected
    ):
        raise ValueError("Product external data selections must be sorted and nonempty")
    if len({item.manifest.name for item in selected}) != len(selected):
        raise ValueError("Product external data Plugin identity is duplicated")
    if not isinstance(composition_set, CodingCompositionSetPlan):
        raise TypeError("Coding composition set is required")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Coding Product Session id is invalid")
    if type(evaluated_at) is not int or evaluated_at < 0:
        raise ValueError("Coding Product evaluation time is invalid")
    owners: set[str] = set()
    trusts: list[PluginSourceTrustSnapshotV1] = []
    pairs: list[
        tuple[
            PackageProductSelectedPluginManifestV1,
            PluginContributionReservation,
            PluginDeclaration,
        ]
    ] = []
    for item in selected:
        trust = item.source_trust_snapshot
        declarations = item.verified_data_only_declarations()
        if (
            not isinstance(trust, PluginSourceTrustSnapshotV1)
            or not trust.trusted
            or trust.source_trust_class not in EXTERNAL_DATA_TRUST_CLASSES
            or len(declarations) != 1
            or not permits_external_data_owner(
                trust.source_trust_class, declarations[0][0].owner
            )
            or declarations[0][0].kind != "resource_item"
            or declarations[0][0].owner
            not in {"resources.skill", "resources.prompt", "resources.theme"}
            or item.snapshot.installation_key.plugin_id != item.manifest.name
            or item.snapshot.instance_revision_ref.plugin_id != item.manifest.name
        ):
            raise ValueError("Product external data Resource selection changed")
        owners.add(declarations[0][0].owner)
        trusts.append(trust)
        pairs.extend(
            (item, reservation, declaration)
            for reservation, declaration in declarations
        )
    policy_digest = sha256(
        canonical_json_bytes(
            [
                {
                    "pluginId": item.manifest.name,
                    "committedSetId": item.snapshot.committed_record.committed_set.set_id,
                    "instanceRevision": item.snapshot.instance_revision_ref.to_dict(),
                }
                for item in selected
            ]
        )
    ).hexdigest()
    plan = PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="coding",
            scope_id=f"session:{session_id.strip()}",
            policy_revision=(
                f"coding-external-data-v1:{composition_set.set_id}:"
                f"{composition_set.fingerprint}:{policy_digest}"
            ),
            instance_revision_refs=tuple(
                item.snapshot.instance_revision_ref for item in selected
            ),
        ),
        selected_plugin_ids=tuple(item.manifest.name for item in selected),
        selected_contributions=tuple(
            sorted(
                PluginContributionRef(item.manifest.name, reservation.contribution_id)
                for item, reservation, _ in pairs
            )
        ),
        source_trust_snapshots=tuple(trusts),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(
                sorted(
                    (
                        PluginEffectiveConfigurationEntry(
                            plugin_id=item.manifest.name,
                            contribution_id=reservation.contribution_id,
                            configuration=reservation.configuration,
                        )
                        for item, reservation, _ in pairs
                    ),
                    key=lambda entry: (entry.plugin_id, entry.contribution_id),
                )
            )
        ),
        allowed_authority_ceiling=(),
    )
    candidates = tuple(
        _candidate(item, plan, reservation, declaration)
        for item, reservation, declaration in pairs
    )
    owner_bindings = tuple(
        ProductContributionOwnerBinding(
            authority=OwnerContributionAuthority(
                replace(
                    binding.authority.policy,
                    allowed_source_trust_classes=(
                        *EXTERNAL_DATA_TRUST_CLASSES_ORDERED,
                    ),
                )
            ),
            admission_ttl_seconds=binding.admission_ttl_seconds,
        )
        for binding in _owner_bindings(
            include_tools=False,
            include_prompt="resources.prompt" in owners,
            include_skill="resources.skill" in owners,
            include_theme="resources.theme" in owners,
            include_command=False,
        )
    )
    composition = _assemble_product_contribution_candidates(
        plan=plan,
        candidates=candidates,
        owner_bindings=owner_bindings,
        mandatory_roots=(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
        definitions=(
            MODEL_INPUT_CAPABILITY_DEFINITION,
            WORKSPACE_CAPABILITY_DEFINITION,
        ),
        select_optional_requirements=lambda _preview: (),
        evaluated_at=evaluated_at,
    )
    return CodingExternalDataProductCompilation(
        product_composition=composition,
        selected_manifests=selected,
        resource_bodies=_resource_bodies(None, composition, external_selected=selected),
    )


__all__ = [
    "CodingExternalDataProductCompilation",
    "compile_coding_external_data_product_selection",
]
