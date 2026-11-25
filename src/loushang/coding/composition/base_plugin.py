"""Private Product assembly for the data-only ``coding.base`` Plugin."""

from __future__ import annotations

from collections.abc import Callable, Set
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.coding.composition.base_owners import (
    CodingBaseCommandOwner,
    CodingBaseToolOwner,
)
from loushang.coding.composition.plan import CODING_PRODUCT_ID
from loushang.coding.composition.sets import CodingCompositionSetPlan
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycle,
    CodingPluginManagementChange,
    CodingPluginSessionLease,
)
from loushang.coding.resources.runtime import CodingPackageMaterializer
from loushang.coding.resources.tool_pack import coding_workspace_tool_profile
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionCompilation,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority,
    OwnerContributionKind,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.environment import HostEnvironment, LocalHostEnvironmentProbe
from loushang.harness.plugin_management.assembly import (
    _ManagedPluginErrors,
    _prepare_managed_plugin_runtime,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginInstanceRevisionRef,
    PluginSelectionPlanV2,
    PluginSourceTrustSnapshotV1,
    build_product_plugin_selection_plan,
)
from loushang.harness.resources.plugins.types import (
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
)
from loushang.harness.session.plugin_lifecycle._composition_cleanup import (
    _PreparedCompositionCleanup,
)
from loushang.harness.session.product_composition_assembly import (
    ProductContributionOwnerBinding,
    ProductPluginCompositionAssembly,
    ProductPluginCompositionAssemblyRequest,
    ProductPluginCompositionPreparation,
    ProductPluginPlanSeed,
    ProductPluginSelectionSeed,
    bind_compiled_registration_authority,
    prepare_product_plugin_composition,
)
from loushang.harness.tools.workspace.factory import ToolsOptions

if TYPE_CHECKING:
    from loushang.harness.package_product.product_local_wheel_runtime import (
        PackageProductSelectedPluginManifestV1,
    )

_PLUGIN_ID = "coding.base"
_SOURCE_TRUST_CLASS = "host-equivalent-local"
_SOURCE_TRUST_POLICY_REVISION = "coding-base-source-trust-v1"
_ADMISSION_TTL_SECONDS = 300
_OWNER_SPECS: tuple[tuple[str, OwnerContributionKind, str], ...] = (
    ("commands.session", "command_pack", "harness.session.standard"),
    ("resources.prompt", "resource_item", "loushang.resource.prompt"),
    ("resources.skill", "resource_item", "loushang.resource.skill"),
    ("resources.theme", "resource_item", "loushang.resource.theme"),
    ("tools.workspace", "tool_pack", "harness.workspace.core"),
)


class CodingBasePluginAssemblyError(RuntimeError):
    """The selected Coding composition cannot form the exact base package."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class CodingBasePluginAssembly(_PreparedCompositionCleanup):
    """Inert base package plan retained until whole-Product finalization."""

    runtime: PluginRuntimeResolution = field(repr=False)
    package: PublishedPluginPackage
    binding: PluginSourceBinding
    plan_seed: ProductPluginPlanSeed
    scope_id: str
    composition_set_fingerprint: str
    host_environment: HostEnvironment
    tool_contribution_id: str | None
    tool_names: tuple[str, ...]
    management_lease: CodingPluginSessionLease | None = field(
        default=None,
        repr=False,
    )
    state_cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
    )
    _runtime_closed: bool = field(default=False, init=False, repr=False)
    _management_released: bool = field(default=False, init=False, repr=False)
    _state_cleaned: bool = field(default=False, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    _cleanup_label = "Coding base"
    _transferred = False
    _private_state_cleaned = True  # Base has no separate private-state root.

    def evaluate_management_change(self) -> CodingPluginManagementChange | None:
        if self.management_lease is None:
            return None
        return self.management_lease.evaluate_management_change()

    def _release_management_leases(self) -> None:
        # A base has one lease. Keep its release fail-fast and retry it before
        # removing the root that still holds its journals and lock files.
        if self.management_lease is not None:
            self.management_lease.close()
        self._management_released = True


@dataclass(frozen=True, slots=True)
class CodingBasePluginSessionPreparation:
    """One base Product compilation awaiting the host workspace Provider."""

    base: CodingBasePluginAssembly = field(repr=False, compare=False)
    product: ProductPluginCompositionPreparation

    @property
    def product_composition(self):
        return self.product.product_composition

    def bind_workspace(
        self,
        workspace_binding: CapabilityBundleProviderBinding,
    ) -> CodingBasePluginSessionAssembly:
        if not isinstance(workspace_binding, CapabilityBundleProviderBinding):
            raise TypeError("Coding base Session requires a workspace binding")
        plugin_assembly = self.product.bind_host_providers(
            (workspace_binding.provider,)
        )
        return CodingBasePluginSessionAssembly(
            plugin_assembly=plugin_assembly,
            session_inputs=plugin_assembly.bind_session_inputs({}),
        )


@dataclass(frozen=True, slots=True)
class CodingBasePluginSessionAssembly:
    """Base-only Product closure bound to one Session's host Providers."""

    plugin_assembly: ProductPluginCompositionAssembly
    session_inputs: SessionCapabilityCompositionInputs


@dataclass(frozen=True, slots=True)
class CodingBasePluginOwners:
    tool: CodingBaseToolOwner | None = field(repr=False)
    command: CodingBaseCommandOwner | None = field(repr=False)


def coding_base_plugin_root() -> Path:
    """Return the exact checked-in source of the reserved ``coding.base`` id."""

    return (Path(__file__).resolve().parent.parent / "_plugins" / "coding_base").resolve(
        strict=True
    )


def prepare_coding_base_plugin_assembly(
    composition_set: CodingCompositionSetPlan,
    *,
    session_id: str,
    package_materializer: CodingPackageMaterializer,
    host_environment: HostEnvironment | None = None,
    include_tool_contribution: bool = True,
    include_tool_claim_prompt: bool = True,
    include_skill_contribution: bool = True,
    include_command_contribution: bool = True,
) -> CodingBasePluginAssembly:
    """Publish and plan the checked-in data-only package without live owners."""

    if not isinstance(composition_set, CodingCompositionSetPlan):
        raise TypeError("Coding base assembly requires a composition-set plan")
    if not isinstance(package_materializer, CodingPackageMaterializer):
        raise TypeError("Coding base assembly requires CodingPackageMaterializer")
    if host_environment is not None and not isinstance(
        host_environment, HostEnvironment
    ):
        raise TypeError("Coding base host environment is invalid")
    if not isinstance(include_tool_contribution, bool):
        raise TypeError("Coding base Tool selection flag must be a boolean")
    if not isinstance(include_tool_claim_prompt, bool):
        raise TypeError("Coding base Tool-claim Prompt flag must be a boolean")
    if not isinstance(include_skill_contribution, bool):
        raise TypeError("Coding base Skill selection flag must be a boolean")
    if not isinstance(include_command_contribution, bool):
        raise TypeError("Coding base Command selection flag must be a boolean")
    normalized_session_id = _normalized(session_id, name="Coding Session id")
    resolved_environment = host_environment or LocalHostEnvironmentProbe().detect()
    _validate_base_request(composition_set)

    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=coding_base_plugin_root()))
    runtime = authority.publish_runtime(
        (inspection,),
        binding_store=package_materializer,
    )
    try:
        return _assemble_base_runtime(
            runtime=runtime,
            composition_set=composition_set,
            session_id=normalized_session_id,
            host_environment=resolved_environment,
            include_tool_contribution=include_tool_contribution,
            include_tool_claim_prompt=include_tool_claim_prompt,
            include_skill_contribution=include_skill_contribution,
            include_command_contribution=include_command_contribution,
            instance_revision_ref=None,
            management_lease=None,
            state_cleanup=None,
        )
    except BaseException:
        runtime.close()
        raise


_MANAGED_ASSEMBLY_ERRORS = _ManagedPluginErrors(
    facts={
        "management_selection_incomplete": (
            "Enabled Coding base selection lacks exact lifecycle evidence",
            "coding_base_management_selection_incomplete",
        ),
        "binding_lock_replay_invalid": (
            "Selected Coding base binding lock failed exact replay",
            "coding_base_binding_replay_invalid",
        ),
        "binding_replay_unavailable": (
            "Selected Coding base binding is unavailable for replay",
            "coding_base_binding_replay_unavailable",
        ),
        "revision_replay_unavailable": (
            "Selected Coding base revision failed exact replay",
            "coding_base_revision_replay_unavailable",
        ),
        "revision_replay_integrity_failed": (
            "Selected Coding base revision failed exact replay",
            "coding_base_revision_replay_integrity_failed",
        ),
        "binding_replay_invalid": (
            "Selected Coding base binding failed exact replay",
            "coding_base_binding_replay_invalid",
        ),
        "selected_revision_mismatch": (
            "Replayed Coding base package is not the selected revision",
            "coding_base_selected_revision_mismatch",
        ),
        "session_lease_mismatch": (
            "Coding base Session lease is outside the management snapshot",
            "coding_base_session_lease_mismatch",
        ),
    },
    make_error=lambda message, code: CodingBasePluginAssemblyError(message, code=code),
    cleanup_notes={
        "lease": "Coding base Session lease cleanup failed: {error}",
        "revision": "Coding base revision cleanup failed: {error}",
        "state": "Coding base state cleanup failed: {error}",
    },
)


def prepare_managed_coding_base_plugin_assembly(
    composition_set: CodingCompositionSetPlan,
    *,
    session_id: str,
    package_materializer: CodingPackageMaterializer,
    lifecycle: CodingPluginLifecycle,
    host_environment: HostEnvironment | None = None,
    include_tool_contribution: bool = True,
    include_tool_claim_prompt: bool = True,
    include_skill_contribution: bool = True,
    include_command_contribution: bool = True,
    state_cleanup: Callable[[], None] | None = None,
    session_owner_id: str | None = None,
    legacy_disabled: bool = False,
) -> CodingBasePluginAssembly | None:
    """Intersect the Product request with one durable management snapshot."""

    if not isinstance(composition_set, CodingCompositionSetPlan):
        raise TypeError("Managed Coding base assembly requires a composition set")
    if not isinstance(package_materializer, CodingPackageMaterializer):
        raise TypeError("Managed Coding base assembly requires a materializer")
    if not isinstance(lifecycle, CodingPluginLifecycle):
        raise TypeError("Managed Coding base assembly requires a lifecycle")
    if state_cleanup is not None and not callable(state_cleanup):
        raise TypeError("Managed Coding base state cleanup must be callable")
    if not isinstance(legacy_disabled, bool):
        raise TypeError("Managed Coding base legacy selection must be boolean")
    for name, value in (
        ("Skill", include_skill_contribution),
        ("Command", include_command_contribution),
    ):
        if not isinstance(value, bool):
            raise TypeError(f"Coding base {name} selection flag must be a boolean")
    _validate_base_request(composition_set)
    normalized_session_id = _normalized(session_id, name="Coding Session id")
    environment = host_environment or LocalHostEnvironmentProbe().detect()

    return _prepare_managed_plugin_runtime(
        lifecycle=lifecycle,
        package_materializer=package_materializer,
        plugin_id=_PLUGIN_ID,
        session_id=normalized_session_id,
        session_owner_id=session_owner_id,
        legacy_disabled=legacy_disabled,
        source_root=lambda: coding_base_plugin_root(),
        owner_contributions=lambda: _selected_owner_contributions(
            os_family=environment.os_family if include_tool_contribution else "",
            include_tools=include_tool_contribution,
            include_prompt=include_tool_claim_prompt,
            include_skill=include_skill_contribution,
            include_command=include_command_contribution,
        ),
        finish=lambda runtime, selected_instance, lease: _assemble_base_runtime(
            runtime=runtime,
            composition_set=composition_set,
            session_id=normalized_session_id,
            host_environment=environment,
            include_tool_contribution=include_tool_contribution,
            include_tool_claim_prompt=include_tool_claim_prompt,
            include_skill_contribution=include_skill_contribution,
            include_command_contribution=include_command_contribution,
            instance_revision_ref=selected_instance,
            management_lease=lease,
            state_cleanup=state_cleanup,
        ),
        errors=_MANAGED_ASSEMBLY_ERRORS,
        state_cleanup=state_cleanup,
    )


def prepare_coding_base_plugin_session(
    assembly: CodingBasePluginAssembly,
    *,
    evaluated_at: int,
    selection_seed: ProductPluginSelectionSeed,
) -> CodingBasePluginSessionPreparation:
    """Compile the base selection once before Session host construction."""

    if not isinstance(assembly, CodingBasePluginAssembly):
        raise TypeError("Coding base Session preparation requires base assembly")
    if not isinstance(selection_seed, ProductPluginSelectionSeed):
        raise TypeError("Coding base Session selection seed is invalid")
    seed = selection_seed
    if _PLUGIN_ID not in seed.selection.plan.selected_plugin_ids:
        raise ValueError("Coding base Session selection omits coding.base")
    return CodingBasePluginSessionPreparation(
        base=assembly,
        product=prepare_product_plugin_composition(
            ProductPluginCompositionAssemblyRequest.for_agent_session(seed),
            evaluated_at=evaluated_at,
        ),
    )


def prepare_coding_base_resource_plan_seed(
    assembly: CodingBasePluginAssembly,
) -> ProductPluginPlanSeed | None:
    """Project the pinned base package into a Resource-owner refresh plan."""

    if not isinstance(assembly, CodingBasePluginAssembly):
        raise TypeError("Coding base Resource plan requires base assembly")
    return assembly.plan_seed.select_resources(assembly.package, plugin_id=_PLUGIN_ID)


def build_coding_base_plugin_owners(
    assembly: CodingBasePluginAssembly,
    plugin_assembly: ProductPluginCompositionAssembly,
    *,
    clock: Callable[[], int],
    tool_options: ToolsOptions = ToolsOptions(),
) -> CodingBasePluginOwners:
    """Build exact base owners from the sole compiled Product composition."""

    if not isinstance(assembly, CodingBasePluginAssembly):
        raise TypeError("Coding base owners require base assembly")
    if not isinstance(plugin_assembly, ProductPluginCompositionAssembly):
        raise TypeError("Coding base owners require Product Plugin assembly")
    return _build_coding_base_owners_from_admissions(
        plan=assembly.plan_seed.plan,
        product_composition=plugin_assembly.product_composition,
        owner_bindings=plugin_assembly.contribution_request.owner_bindings,
        scope_id=assembly.scope_id,
        tool_contribution_id=assembly.tool_contribution_id,
        clock=clock,
        tool_options=tool_options,
    )


def _build_coding_base_owners_from_admissions(
    *,
    plan: PluginSelectionPlanV2,
    product_composition: ProductCompositionCompilation,
    owner_bindings: tuple[ProductContributionOwnerBinding, ...],
    scope_id: str,
    tool_contribution_id: str | None,
    clock: Callable[[], int],
    tool_options: ToolsOptions,
) -> CodingBasePluginOwners:
    """Bind owner adapters to one exact Product compilation and its authorities."""

    if not isinstance(plan, PluginSelectionPlanV2):
        raise TypeError("Coding base owner plan is invalid")
    if not isinstance(product_composition, ProductCompositionCompilation):
        raise TypeError("Coding base owner Product composition is invalid")
    if plan.context.scope_id != scope_id:
        raise ValueError("Coding base owner scope changed Product selection")
    if not callable(clock):
        raise TypeError("Coding base owner clock is invalid")
    if not isinstance(tool_options, ToolsOptions):
        raise TypeError("Coding base Tool options are invalid")
    admissions = {
        (item.owner_id, item.contribution_kind, item.contribution_id): item
        for item in product_composition.catalog_admissions
        if item.plugin_id == _PLUGIN_ID
    }
    tool_admission = (
        admissions.get(("tools.workspace", "tool_pack", tool_contribution_id))
        if tool_contribution_id is not None
        else None
    )
    command_admission = admissions.get(
        ("commands.session", "command_pack", "coding.standard")
    )
    selected_contribution_ids = {
        item.contribution_id
        for item in plan.selected_contributions
        if item.plugin_id == _PLUGIN_ID
    }
    command_selected = "coding.standard" in selected_contribution_ids
    expected_admissions = int(tool_contribution_id is not None) + int(command_selected)
    if (
        len(admissions) != expected_admissions
        or (command_selected and command_admission is None)
        or (not command_selected and command_admission is not None)
        or (tool_contribution_id is not None and tool_admission is None)
    ):
        raise ValueError("Coding base requires exact Tool and Command admissions")
    gate = bind_compiled_registration_authority(
        product_composition, owner_bindings, clock=clock, label="Coding base owner"
    )
    return CodingBasePluginOwners(
        tool=(
            CodingBaseToolOwner(
                admission=tool_admission,
                authority_gate=gate,
                options=tool_options,
                scope_id=scope_id,
            )
            if tool_admission is not None
            else None
        ),
        command=(
            CodingBaseCommandOwner(
                admission=command_admission,
                authority_gate=gate,
                scope_id=scope_id,
            )
            if command_admission is not None
            else None
        ),
    )


def prepare_coding_base_product_plan(
    selected: PackageProductSelectedPluginManifestV1,
    composition_set: CodingCompositionSetPlan,
    *,
    installation_key: PluginInstallationKeyV1,
    session_id: str,
    host_environment: HostEnvironment,
    include_tool_contribution: bool = True,
    include_tool_claim_prompt: bool = True,
    include_skill_contribution: bool = True,
    include_command_contribution: bool = True,
) -> tuple[PluginSelectionPlanV2, str | None, tuple[str, ...]]:
    """Build an inert Coding plan from one Product-selected data-only root."""

    from loushang.harness.package_product.product_local_wheel_runtime import (
        PackageProductSelectedPluginManifestV1,
    )

    if not isinstance(selected, PackageProductSelectedPluginManifestV1):
        raise TypeError("Coding base requires Product-selected Plugin evidence")
    if not isinstance(composition_set, CodingCompositionSetPlan):
        raise TypeError("Coding base requires a composition-set plan")
    if not isinstance(host_environment, HostEnvironment):
        raise TypeError("Coding base requires a host environment")
    if not isinstance(installation_key, PluginInstallationKeyV1):
        raise TypeError("Coding base requires an exact Product installation key")
    manifest = selected.verified_manifest()
    source_trust_snapshot = selected.source_trust_snapshot
    if not isinstance(source_trust_snapshot, PluginSourceTrustSnapshotV1):
        raise CodingBasePluginAssemblyError(
            "Selected Coding base has no Product source trust decision",
            code="coding_base_product_source_untrusted",
        )
    _validate_base_request(composition_set)
    if (
        manifest.name != _PLUGIN_ID
        or selected.snapshot.installation_key != installation_key
        or selected.snapshot.installation_key.product_id != CODING_PRODUCT_ID
        or selected.snapshot.instance_revision_ref.plugin_id != _PLUGIN_ID
        or source_trust_snapshot.plugin_id != _PLUGIN_ID
        or source_trust_snapshot.package_source_identity
        != selected.snapshot.package_revision.package_source_identity
        or source_trust_snapshot.source_trust_class != _SOURCE_TRUST_CLASS
        or not source_trust_snapshot.trusted
        or any(
            item.contribution_execution_model != "data_only"
            for item in manifest.contribution_index.items
        )
    ):
        raise CodingBasePluginAssemblyError(
            "Selected Coding base Product evidence is not admissible",
            code="coding_base_product_selection_mismatch",
        )
    contributions = tuple(
        reservation for reservation, _ in selected.verified_data_only_declarations()
    )
    scope_id = f"session:{_normalized(session_id, name='Coding Session id')}"
    return _build_selection_plan_from_evidence(
        contributions=contributions,
        source_trust_snapshot=source_trust_snapshot,
        instance_revision_ref=selected.snapshot.instance_revision_ref,
        policy_revision_base=(
            f"coding-base-plc9b-v1:{composition_set.set_id}:"
            f"{composition_set.fingerprint}:"
            f"{selected.snapshot.committed_record.committed_set.set_id}"
        ),
        scope_id=scope_id,
        selected_owners=_selected_owner_contributions(
            os_family=host_environment.os_family,
            include_tools=include_tool_contribution,
            include_prompt=include_tool_claim_prompt,
            include_skill=include_skill_contribution,
            include_command=include_command_contribution,
        ),
        host_environment=host_environment,
        include_tool_contribution=include_tool_contribution,
        include_tool_claim_prompt=include_tool_claim_prompt,
        include_skill_contribution=include_skill_contribution,
        include_command_contribution=include_command_contribution,
        require_complete=True,
    )


def _build_selection_plan_from_evidence(
    *,
    contributions: tuple[PluginContributionReservation, ...],
    source_trust_snapshot: PluginSourceTrustSnapshotV1,
    instance_revision_ref: PluginInstanceRevisionRef,
    policy_revision_base: str,
    scope_id: str,
    selected_owners: tuple[tuple[str, tuple[str, ...]], ...],
    host_environment: HostEnvironment,
    include_tool_contribution: bool,
    include_tool_claim_prompt: bool,
    include_skill_contribution: bool,
    include_command_contribution: bool,
    require_complete: bool = False,
) -> tuple[PluginSelectionPlanV2, str | None, tuple[str, ...]]:
    owners = dict(selected_owners)
    selected_ids = {item for contributions in owners.values() for item in contributions}
    selected_contributions = tuple(
        PluginContributionRef(_PLUGIN_ID, item.contribution_id)
        for item in contributions
        if item.contribution_id in selected_ids
    )
    selected_tool_names = (
        tuple(
            sorted(coding_workspace_tool_profile(host_environment).builtin_tool_names)
        )
        if include_tool_contribution
        else ()
    )
    policy_revision = policy_revision_base
    if not all(
        (
            include_tool_contribution,
            include_tool_claim_prompt,
            include_skill_contribution,
            include_command_contribution,
        )
    ):
        policy_revision += (
            ":contributions="
            f"t{int(include_tool_contribution)}"
            f"p{int(include_tool_claim_prompt)}"
            f"s{int(include_skill_contribution)}"
            f"c{int(include_command_contribution)}"
        )
    plan = build_product_plugin_selection_plan(
        product_id=CODING_PRODUCT_ID,
        scope_id=scope_id,
        policy_revision=policy_revision,
        instance_refs=(instance_revision_ref,),
        plugin_ids=(_PLUGIN_ID,),
        selected_contributions=selected_contributions,
        source_trust=(source_trust_snapshot,),
        additions=(
            PluginEffectiveConfigurationEntry(
                plugin_id=_PLUGIN_ID,
                contribution_id=item.contribution_id,
                configuration=item.configuration,
            )
            for item in contributions
        ),
        allowed_authority_ceiling=(),
    )
    if require_complete and {
        item.contribution_id for item in plan.selected_contributions
    } != selected_ids:
        raise CodingBasePluginAssemblyError(
            "Selected Coding base Product contributions are incomplete",
            code="coding_base_product_selection_mismatch",
        )
    return (
        plan,
        owners["tools.workspace"][0] if include_tool_contribution else None,
        selected_tool_names,
    )


def _assemble_base_runtime(
    *,
    runtime: PluginRuntimeResolution,
    composition_set: CodingCompositionSetPlan,
    session_id: str,
    host_environment: HostEnvironment,
    include_tool_contribution: bool,
    include_tool_claim_prompt: bool,
    include_skill_contribution: bool,
    include_command_contribution: bool,
    instance_revision_ref: PluginInstanceRevisionRef | None,
    management_lease: CodingPluginSessionLease | None,
    state_cleanup: Callable[[], None] | None,
) -> CodingBasePluginAssembly:
    [package] = runtime.packages
    [binding] = runtime.bindings
    scope_id = f"session:{session_id}"
    selected_owners = _selected_owner_contributions(
        os_family=host_environment.os_family,
        include_tools=include_tool_contribution,
        include_prompt=include_tool_claim_prompt,
        include_skill=include_skill_contribution,
        include_command=include_command_contribution,
    )
    plan, tool_contribution_id, tool_names = _build_selection_plan_from_evidence(
        contributions=package.contribution_index.items,
        source_trust_snapshot=PluginSourceTrustSnapshotV1(
            plugin_id=_PLUGIN_ID,
            package_source_identity=binding.source_identity,
            source_trust_class=_SOURCE_TRUST_CLASS,
            source_trust_policy_revision=_SOURCE_TRUST_POLICY_REVISION,
            trusted=True,
        ),
        instance_revision_ref=(
            instance_revision_ref
            or PluginInstanceRevisionRef(
                instance_id=f"{_PLUGIN_ID}@{scope_id}",
                plugin_id=_PLUGIN_ID,
                revision=1,
            )
        ),
        policy_revision_base=(
            f"coding-base-plc6-v1:{composition_set.set_id}:"
            f"{composition_set.fingerprint}"
        ),
        scope_id=scope_id,
        selected_owners=selected_owners,
        host_environment=host_environment,
        include_tool_contribution=include_tool_contribution,
        include_tool_claim_prompt=include_tool_claim_prompt,
        include_skill_contribution=include_skill_contribution,
        include_command_contribution=include_command_contribution,
    )
    return CodingBasePluginAssembly(
        runtime=runtime,
        package=package,
        binding=binding,
        plan_seed=ProductPluginPlanSeed(
            plan=plan,
            packages=(package,),
            bindings=(binding,),
            owner_bindings=_owner_bindings({owner_id for owner_id, _ in selected_owners}),
        ),
        scope_id=scope_id,
        composition_set_fingerprint=composition_set.fingerprint,
        host_environment=host_environment,
        tool_contribution_id=tool_contribution_id,
        tool_names=tool_names,
        management_lease=management_lease,
        state_cleanup=state_cleanup,
    )


def _validate_base_request(composition_set: CodingCompositionSetPlan) -> None:
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


def _owner_bindings(
    owner_ids: Set[str],
) -> tuple[ProductContributionOwnerBinding, ...]:
    return tuple(
        ProductContributionOwnerBinding(
            authority=OwnerContributionAuthority.for_direct_session(
                owner_id=owner_id,
                contribution_kind=contribution_kind,
                product_id=CODING_PRODUCT_ID,
                policy_revision=f"coding-base-{owner_id}-owner-v1",
                trust_classes=(_SOURCE_TRUST_CLASS,),
                collection_ids=(collection_id,),
            ),
            admission_ttl_seconds=_ADMISSION_TTL_SECONDS,
        )
        for owner_id, contribution_kind, collection_id in _OWNER_SPECS
        if owner_id in owner_ids
    )


def _selected_owner_contributions(
    *,
    os_family: str,
    include_tools: bool,
    include_prompt: bool,
    include_skill: bool,
    include_command: bool,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    tool = "coding.builtin.windows" if os_family == "windows" else "coding.builtin"
    return tuple(
        (owner_id, (contribution_id,))
        for owner_id, contribution_id, include in (
            ("commands.session", "coding.standard", include_command),
            ("resources.prompt", "prompt-standard", include_prompt),
            ("resources.skill", "skill-standard", include_skill),
            ("tools.workspace", tool, include_tools),
        )
        if include
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
    "CodingBasePluginOwners",
    "CodingBasePluginSessionAssembly",
    "CodingBasePluginSessionPreparation",
    "build_coding_base_plugin_owners",
    "coding_base_plugin_root",
    "prepare_coding_base_plugin_assembly",
    "prepare_coding_base_product_plan",
    "prepare_managed_coding_base_plugin_assembly",
    "prepare_coding_base_resource_plan_seed",
    "prepare_coding_base_plugin_session",
]
