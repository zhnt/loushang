"""Private Product assembly for the data-only ``coding.base`` Plugin."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from loushang.coding._base_plugin_owners import (
    CodingBaseCommandOwner,
    CodingBaseToolOwner,
)
from loushang.coding.composition_sets import CodingCompositionSetPlan
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.coding.resource_runtime import CodingPackageMaterializer
from loushang.coding.tool_pack import coding_workspace_tool_profile
from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority,
    OwnerContributionKind,
    OwnerContributionPolicy,
    OwnerContributionSnapshot,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.environment import HostEnvironment, LocalHostEnvironmentProbe
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginInstanceRevisionRef,
    PluginPreflightContextV1,
    PluginSelectionPlanV2,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import (
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
    SessionCapabilityOwnerAuthorityGate,
)
from loushang.harness.session.product_composition_assembly import (
    ProductCompositionAssemblyRequest,
    ProductContributionOwnerBinding,
    ProductPluginCompositionAssembly,
    ProductPluginCompositionAssemblyRequest,
    ProductPluginCompositionPreparation,
    ProductPluginPlanSeed,
    ProductPluginSelectionSeed,
    prepare_product_plugin_composition,
)
from loushang.harness.tools.workspace.factory import ToolsOptions

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
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self.runtime.close()
        self._closed = True


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
    command: CodingBaseCommandOwner = field(repr=False)


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
    host_environment: HostEnvironment | None = None,
    include_tool_contribution: bool = True,
    include_tool_claim_prompt: bool = True,
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
    normalized_session_id = _normalized(session_id, name="Coding Session id")
    resolved_environment = host_environment or LocalHostEnvironmentProbe().detect()
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
        plan, tool_contribution_id, tool_names = _build_selection_plan(
            package,
            binding=binding,
            scope_id=scope_id,
            composition_set=composition_set,
            host_environment=resolved_environment,
            include_tool_contribution=include_tool_contribution,
            include_tool_claim_prompt=include_tool_claim_prompt,
        )
        plan_seed = ProductPluginPlanSeed(
            plan=plan,
            packages=(package,),
            bindings=(binding,),
            owner_bindings=_owner_bindings(
                include_tools=include_tool_contribution,
                include_prompt=include_tool_claim_prompt,
            ),
        )
        return CodingBasePluginAssembly(
            runtime=runtime,
            package=package,
            binding=binding,
            plan_seed=plan_seed,
            scope_id=scope_id,
            composition_set_fingerprint=composition_set.fingerprint,
            host_environment=resolved_environment,
            tool_contribution_id=tool_contribution_id,
            tool_names=tool_names,
        )
    except BaseException:
        runtime.close()
        raise


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
    contribution_request = ProductCompositionAssemblyRequest(
        selection=seed.selection,
        owner_bindings=seed.owner_bindings,
        mandatory_roots=(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
        definitions=(
            MODEL_INPUT_CAPABILITY_DEFINITION,
            WORKSPACE_CAPABILITY_DEFINITION,
        ),
    )
    request = ProductPluginCompositionAssemblyRequest(
        contribution_request=contribution_request,
        provider_owner_bindings=(),
        provider_roots=(),
        host_capability_ids=(
            MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
            WORKSPACE_CAPABILITY_DEFINITION.capability_id,
        ),
        select_capability_providers=lambda _admissions: (),
    )
    return CodingBasePluginSessionPreparation(
        base=assembly,
        product=prepare_product_plugin_composition(
            request,
            evaluated_at=evaluated_at,
        ),
    )


def prepare_coding_base_resource_plan_seed(
    assembly: CodingBasePluginAssembly,
) -> ProductPluginPlanSeed:
    """Project the pinned base package into a Resource-owner refresh plan."""

    if not isinstance(assembly, CodingBasePluginAssembly):
        raise TypeError("Coding base Resource plan requires base assembly")
    seed = assembly.plan_seed
    resource_ids = {
        item.contribution_id
        for item in assembly.package.contribution_index.items
        if item.kind == "resource_item"
    }
    selected_resources = tuple(
        item
        for item in seed.plan.selected_contributions
        if item.plugin_id == _PLUGIN_ID and item.contribution_id in resource_ids
    )
    if not selected_resources:
        raise CodingBasePluginAssemblyError(
            "The Coding base selection has no Resource contribution",
            code="coding_base_resource_selection_empty",
        )
    return ProductPluginPlanSeed(
        plan=replace(
            seed.plan,
            selected_contributions=selected_resources,
        ),
        packages=seed.packages,
        bindings=seed.bindings,
        owner_bindings=tuple(
            item
            for item in seed.owner_bindings
            if item.owner_key[1] == "resource_item"
        ),
    )


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
    if not callable(clock):
        raise TypeError("Coding base owner clock is invalid")
    if not isinstance(tool_options, ToolsOptions):
        raise TypeError("Coding base Tool options are invalid")
    admissions = {
        (item.owner_id, item.contribution_kind, item.contribution_id): item
        for item in plugin_assembly.product_composition.catalog_admissions
        if item.plugin_id == _PLUGIN_ID
    }
    tool_admission = (
        admissions.get(
            ("tools.workspace", "tool_pack", assembly.tool_contribution_id)
        )
        if assembly.tool_contribution_id is not None
        else None
    )
    command_admission = admissions.get(
        ("commands.session", "command_pack", "coding.standard")
    )
    expected_admissions = 2 if assembly.tool_contribution_id is not None else 1
    if (
        command_admission is None
        or len(admissions) != expected_admissions
        or (
            assembly.tool_contribution_id is not None
            and tool_admission is None
        )
    ):
        raise ValueError("Coding base requires exact Tool and Command admissions")
    authorities = {
        item.owner_key: item.authority
        for item in plugin_assembly.contribution_request.owner_bindings
    }
    context = plugin_assembly.product_composition.authority_context

    def read_owner(
        owner_id: str,
        contribution_kind: str,
        product_id: str,
    ) -> OwnerContributionSnapshot:
        authority = authorities.get((owner_id, contribution_kind, product_id))
        if authority is None:
            raise ValueError("Coding base owner reader received another owner")
        return authority.snapshot()

    def read_trust(
        plugin_id: str,
        source_identity: str,
    ) -> PluginSourceTrustSnapshotV1:
        matches = tuple(
            item
            for item in context.trust_snapshots
            if item.plugin_id == plugin_id
            and item.package_source_identity == source_identity
        )
        if len(matches) != 1:
            raise ValueError("Coding base owner requires one trust snapshot")
        return matches[0]

    def read_product_policy(product_id: str, scope_id: str) -> str:
        if product_id != context.product_id or scope_id != context.scope_id:
            raise ValueError("Coding base owner received another Product scope")
        return context.product_policy_revision

    gate = SessionCapabilityOwnerAuthorityGate(
        authority_context=context,
        owner_snapshot_reader=read_owner,
        trust_snapshot_reader=read_trust,
        product_policy_revision_reader=read_product_policy,
        clock=clock,
    )
    return CodingBasePluginOwners(
        tool=(
            CodingBaseToolOwner(
                admission=tool_admission,
                authority_gate=gate,
                options=tool_options,
                scope_id=assembly.scope_id,
            )
            if tool_admission is not None
            else None
        ),
        command=CodingBaseCommandOwner(
            admission=command_admission,
            authority_gate=gate,
            scope_id=assembly.scope_id,
        ),
    )


def _build_selection_plan(
    package: PublishedPluginPackage,
    *,
    binding: PluginSourceBinding,
    scope_id: str,
    composition_set: CodingCompositionSetPlan,
    host_environment: HostEnvironment,
    include_tool_contribution: bool,
    include_tool_claim_prompt: bool,
) -> tuple[PluginSelectionPlanV2, str | None, tuple[str, ...]]:
    contributions = package.contribution_index.items
    tool_contribution_id = (
        "coding.builtin.windows"
        if host_environment.os_family == "windows"
        else "coding.builtin"
    )
    selected_ids = {
        "coding.standard",
        "skill-standard",
    }
    if include_tool_contribution:
        selected_ids.add(tool_contribution_id)
    if include_tool_claim_prompt:
        selected_ids.add("prompt-standard")
    selected_contributions = tuple(
        PluginContributionRef(_PLUGIN_ID, item.contribution_id)
        for item in contributions
        if item.contribution_id in selected_ids
    )
    selected_tool_names = (
        tuple(
            sorted(
                coding_workspace_tool_profile(host_environment).builtin_tool_names
            )
        )
        if include_tool_contribution
        else ()
    )
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
        selected_contributions=selected_contributions,
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
    return (
        plan,
        tool_contribution_id if include_tool_contribution else None,
        selected_tool_names,
    )


def _owner_bindings(
    *,
    include_tools: bool,
    include_prompt: bool,
) -> tuple[ProductContributionOwnerBinding, ...]:
    selected_specs = tuple(
        spec
        for spec in _OWNER_SPECS
        if (include_tools or spec[0] != "tools.workspace")
        and (include_prompt or spec[0] != "resources.prompt")
    )
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
        for owner_id, contribution_kind, collection_id in selected_specs
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
    "prepare_coding_base_resource_plan_seed",
    "prepare_coding_base_plugin_session",
]
