"""Private Product assembly for the data-only ``coding.base`` Plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loushang.coding.composition_sets import CodingCompositionSetPlan
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.coding.resource_runtime import CodingPackageMaterializer
from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority,
    OwnerContributionKind,
    OwnerContributionPolicy,
)
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.selection import (
    PendingOnlyPluginExecutionDecisionLookup,
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginInstanceRevisionRef,
    PluginPreflightContextV1,
    PluginSelection,
    PluginSelectionPlanV2,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import (
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
)
from loushang.harness.session.product_composition_assembly import (
    ProductCompositionAssemblyRequest,
    ProductContributionOwnerBinding,
)

_PLUGIN_ID = "coding.base"
_SOURCE_TRUST_CLASS = "host-equivalent-local"
_SOURCE_TRUST_POLICY_REVISION = "coding-base-source-trust-v1"
_ADMISSION_TTL_SECONDS = 300
_OWNER_SPECS: tuple[tuple[str, OwnerContributionKind, str], ...] = (
    ("commands.session", "command_pack", "harness.session.standard"),
    ("resources.prompt", "resource_item", "loushang.resource.prompt"),
    ("resources.skill", "resource_item", "loushang.resource.skill"),
    ("tools.workspace", "tool_pack", "harness.workspace.core"),
)


class CodingBasePluginAssemblyError(RuntimeError):
    """The selected Coding composition cannot form the exact base package."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class CodingBasePluginAssembly:
    """Finalized inert package selection retained for repeated owner admission."""

    runtime: PluginRuntimeResolution = field(repr=False)
    package: PublishedPluginPackage
    binding: PluginSourceBinding
    selection: PluginSelection
    composition_request: ProductCompositionAssemblyRequest
    scope_id: str
    composition_set_fingerprint: str
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self.runtime.close()
        self._closed = True


def coding_base_plugin_root() -> Path:
    """Return the exact checked-in source of the reserved ``coding.base`` id."""

    return (Path(__file__).resolve().parent / "_plugins" / "coding_base").resolve(
        strict=True
    )


def prepare_coding_base_plugin_assembly(
    composition_set: CodingCompositionSetPlan,
    *,
    session_id: str,
    package_materializer: CodingPackageMaterializer,
) -> CodingBasePluginAssembly:
    """Publish and finalize the checked-in data-only package without live owners."""

    if not isinstance(composition_set, CodingCompositionSetPlan):
        raise TypeError("Coding base assembly requires a composition-set plan")
    if not isinstance(package_materializer, CodingPackageMaterializer):
        raise TypeError("Coding base assembly requires CodingPackageMaterializer")
    normalized_session_id = _normalized(session_id, name="Coding Session id")
    requests = {item.plugin_id: item for item in composition_set.plugin_requests}
    base_request = requests.get(_PLUGIN_ID)
    if base_request is None:
        raise CodingBasePluginAssemblyError(
            "The selected Coding composition set does not request coding.base",
            code="coding_base_not_requested",
        )
    if (
        base_request.plugin_kind != "resource"
        or not base_request.required
        or base_request.capability_id is not None
        or base_request.mount_mode is not None
    ):
        raise CodingBasePluginAssemblyError(
            "The Coding base request does not match the reserved Product policy",
            code="coding_base_request_mismatch",
        )

    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=coding_base_plugin_root()))
    runtime = authority.publish_runtime(
        (inspection,),
        binding_store=package_materializer,
    )
    try:
        [package] = runtime.packages
        [binding] = runtime.bindings
        scope_id = f"session:{normalized_session_id}"
        selection = _finalize_selection(
            package,
            binding=binding,
            scope_id=scope_id,
            composition_set=composition_set,
        )
        composition_request = ProductCompositionAssemblyRequest(
            selection=selection,
            owner_bindings=_owner_bindings(),
            mandatory_roots=(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
            definitions=(
                MODEL_INPUT_CAPABILITY_DEFINITION,
                WORKSPACE_CAPABILITY_DEFINITION,
            ),
        )
        return CodingBasePluginAssembly(
            runtime=runtime,
            package=package,
            binding=binding,
            selection=selection,
            composition_request=composition_request,
            scope_id=scope_id,
            composition_set_fingerprint=composition_set.fingerprint,
        )
    except BaseException:
        runtime.close()
        raise


def _finalize_selection(
    package: PublishedPluginPackage,
    *,
    binding: PluginSourceBinding,
    scope_id: str,
    composition_set: CodingCompositionSetPlan,
) -> PluginSelection:
    contributions = package.contribution_index.items
    policy_revision = (
        f"coding-base-plc6-v1:{composition_set.set_id}:{composition_set.fingerprint}"
    )
    plan = PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id=CODING_PRODUCT_ID,
            scope_id=scope_id,
            policy_revision=policy_revision,
            instance_revision_refs=(
                PluginInstanceRevisionRef(
                    instance_id=f"{_PLUGIN_ID}@{scope_id}",
                    plugin_id=_PLUGIN_ID,
                    revision=1,
                ),
            ),
        ),
        selected_plugin_ids=(_PLUGIN_ID,),
        selected_contributions=tuple(
            PluginContributionRef(_PLUGIN_ID, item.contribution_id)
            for item in contributions
        ),
        source_trust_snapshots=(
            PluginSourceTrustSnapshotV1(
                plugin_id=_PLUGIN_ID,
                package_source_identity=binding.source_identity,
                source_trust_class=_SOURCE_TRUST_CLASS,
                source_trust_policy_revision=_SOURCE_TRUST_POLICY_REVISION,
                trusted=True,
            ),
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(
                PluginEffectiveConfigurationEntry(
                    plugin_id=_PLUGIN_ID,
                    contribution_id=item.contribution_id,
                    configuration=item.configuration,
                )
                for item in contributions
            )
        ),
        allowed_authority_ceiling=(),
    )
    selection = PluginDeclarationHost().resolve(
        (package,),
        bindings=(binding,),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    if not isinstance(selection, PluginSelection):
        raise CodingBasePluginAssemblyError(
            "The checked-in coding.base declarations did not finalize",
            code="coding_base_selection_incomplete",
        )
    return selection


def _owner_bindings() -> tuple[ProductContributionOwnerBinding, ...]:
    return tuple(
        ProductContributionOwnerBinding(
            authority=OwnerContributionAuthority(
                OwnerContributionPolicy(
                    owner_id=owner_id,
                    contribution_kind=contribution_kind,
                    product_id=CODING_PRODUCT_ID,
                    policy_revision=f"coding-base-{owner_id}-owner-v1",
                    revocation_epoch=0,
                    allowed_source_trust_classes=(_SOURCE_TRUST_CLASS,),
                    allowed_collection_ids=(collection_id,),
                    allowed_requirement_bindings=("direct",),
                    consumer_scope="session",
                    consumer_refresh_boundary="sealed",
                )
            ),
            admission_ttl_seconds=_ADMISSION_TTL_SECONDS,
        )
        for owner_id, contribution_kind, collection_id in _OWNER_SPECS
    )


def _normalized(value: str, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    normalized = value.strip()
    if normalized != value:
        raise ValueError(f"{name} must be normalized")
    return normalized


__all__ = [
    "CodingBasePluginAssembly",
    "CodingBasePluginAssemblyError",
    "coding_base_plugin_root",
    "prepare_coding_base_plugin_assembly",
]
