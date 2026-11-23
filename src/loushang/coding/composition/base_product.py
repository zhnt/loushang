"""Path-free Product composition for the selected data-only Coding base."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from dataclasses import replace as replace
from hashlib import sha256
from itertools import chain
from typing import TYPE_CHECKING, Literal

from loushang.coding.composition.base_plugin import (
    _PLUGIN_ID as CODING_BASE_PLUGIN_ID,
)
from loushang.coding.composition.base_plugin import (
    CodingBasePluginAssemblyError,
    CodingBasePluginOwners,
    _build_coding_base_owners_from_admissions,
)
from loushang.coding.composition.base_plugin import (
    _owner_bindings as _owner_bindings,
)
from loushang.coding.composition.base_plugin import (
    prepare_coding_base_product_plan as prepare_coding_base_product_plan,
)
from loushang.coding.composition.sets import CodingCompositionSetPlan
from loushang.coding.package.legacy_data_trust import EXTERNAL_DATA_RESOURCE_OWNERS
from loushang.coding.package.legacy_data_trust import (
    EXTERNAL_DATA_TRUST_CLASSES as EXTERNAL_DATA_TRUST_CLASSES,
)
from loushang.coding.package.legacy_data_trust import (
    EXTERNAL_DATA_TRUST_CLASSES_ORDERED as EXTERNAL_DATA_TRUST_CLASSES_ORDERED,
)
from loushang.coding.package.legacy_data_trust import (
    permits_external_data_owner as permits_external_data_owner,
)
from loushang.harness.capabilities import (
    WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionCompilation,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority as OwnerContributionAuthority,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionCandidateEnvelope,
)
from loushang.harness.capabilities.contribution_admission import (
    ResourceContributionSpec as ResourceContributionSpec,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.environment import HostEnvironment
from loushang.harness.package_product._selected_plugin_revisions import (
    capture_external_data_declaration,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resource_catalog.product_snapshot_source import (
    ProductSelectedResourceInput,
    capture_selected_resource_bodies,
    project_selected_resource_inputs,
    validate_product_resource_compilation,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef as PluginContributionRef,
)
from loushang.harness.resources.plugins.selection import (
    PluginEffectiveConfigurationEntry as PluginEffectiveConfigurationEntry,
)
from loushang.harness.resources.plugins.selection import (
    PluginEffectiveConfigurationSetV1 as PluginEffectiveConfigurationSetV1,
)
from loushang.harness.resources.plugins.selection import (
    PluginPreflightContextV1 as PluginPreflightContextV1,
)
from loushang.harness.resources.plugins.selection import (
    PluginSelectionPlanV2,
)
from loushang.harness.resources.plugins.selection import (
    PluginSourceTrustSnapshotV1 as PluginSourceTrustSnapshotV1,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
)
from loushang.harness.session.product_composition_assembly import (
    ProductContributionOwnerBinding as ProductContributionOwnerBinding,
)
from loushang.harness.session.product_composition_assembly import (
    SelectedProductDataDeclaration,
    _rebind_resource_owner_trust,
    assemble_agent_data_composition,
    bind_agent_host_session_inputs,
    build_product_data_selection_plan,
    prepare_product_selected_contribution_candidate,
    project_selected_product_data_candidates,
)
from loushang.harness.tools.workspace.factory import ToolsOptions

if TYPE_CHECKING:
    from loushang.harness.package_product.product_local_wheel_runtime import (
        PackageProductSelectedPluginManifestV1,
    )


@dataclass(frozen=True, slots=True)
class CodingBaseProductResourceBody:
    admission_fingerprint: str
    contribution_id: str
    logical_path: str
    content_digest: str
    body: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.body, bytes):
            raise TypeError("Product Resource body must be immutable bytes")
        if sha256(self.body).hexdigest() != self.content_digest:
            raise ValueError("Product Resource body changed captured bytes")


@dataclass(frozen=True, slots=True)
class CodingBaseProductCompilation:
    plan: PluginSelectionPlanV2
    product_composition: ProductCompositionCompilation
    owner_bindings: tuple[ProductContributionOwnerBinding, ...] = field(
        repr=False, compare=False
    )
    host_environment: HostEnvironment
    selected_manifest: PackageProductSelectedPluginManifestV1 = field(
        repr=False, compare=False
    )
    tool_contribution_id: str | None
    tool_names: tuple[str, ...]
    resource_bodies: tuple[CodingBaseProductResourceBody, ...] = field(repr=False)
    selected_capability_manifests: tuple[
        PackageProductSelectedPluginManifestV1, ...
    ] = field(default=(), repr=False, compare=False)
    selected_external_data_manifests: tuple[
        PackageProductSelectedPluginManifestV1, ...
    ] = field(default=(), repr=False, compare=False)

    def __post_init__(self) -> None:
        validate_product_resource_compilation(
            self.plan,
            self.product_composition,
            (binding.authority for binding in self.owner_bindings),
            base_plugin_id=CODING_BASE_PLUGIN_ID,
            selected_base=self.selected_manifest,
            selected_capabilities=self.selected_capability_manifests,
            selected_resources=self.selected_external_data_manifests,
            bodies=self.resource_bodies,
            changed_authority="Product Coding base changed owner authority facts",
        )

    def read_resource_body(
        self, admission_fingerprint: str, *, max_bytes: int
    ) -> bytes:
        """Read only one admitted body from the immutable Product root capture."""

        if type(max_bytes) is not int or not 0 <= max_bytes <= 16 * 1024 * 1024:
            raise ValueError("Product Resource read budget is invalid")
        for item in self.resource_bodies:
            if item.admission_fingerprint == admission_fingerprint:
                if len(item.body) > max_bytes:
                    break
                return item.body
        raise CodingBasePluginAssemblyError(
            "Product Resource body is unavailable under this owner admission",
            code="coding_base_product_resource_unavailable",
        )

    def product_resource_inputs(self) -> tuple[ProductSelectedResourceInput, ...]:
        """Pair captured bytes with their exact Product owner admissions."""

        return project_selected_resource_inputs(
            self.product_composition.resource_admissions,
            (self.selected_manifest, *self.selected_external_data_manifests),
            self.resource_bodies,
        )

    def build_owners(
        self,
        *,
        clock: Callable[[], int],
        tool_options: ToolsOptions,
    ) -> CodingBasePluginOwners:
        """Bind Tool and Command owners to the same Product admission facts."""

        return _build_coding_base_owners_from_admissions(
            plan=self.plan,
            product_composition=self.product_composition,
            owner_bindings=self.owner_bindings,
            scope_id=self.plan.context.scope_id,
            tool_contribution_id=self.tool_contribution_id,
            clock=clock,
            tool_options=tool_options,
        )

    def bind_workspace(
        self, workspace_binding: CapabilityBundleProviderBinding
    ) -> CodingBaseProductSessionAssembly:
        """Close the data-only Product base over the Session's host Provider."""

        if not isinstance(workspace_binding, CapabilityBundleProviderBinding):
            raise TypeError("Coding base Product requires a workspace binding")
        workspace = workspace_binding.provider
        if workspace.capability_id != WORKSPACE_CAPABILITY_DEFINITION.capability_id:
            raise ValueError("Coding base Product host Provider is not workspace")
        return CodingBaseProductSessionAssembly(
            compilation=self,
            workspace_binding=workspace_binding,
            session_inputs=bind_agent_host_session_inputs(
                self.product_composition, workspace
            ),
        )


@dataclass(frozen=True, slots=True)
class CodingBaseProductSessionAssembly:
    compilation: CodingBaseProductCompilation = field(repr=False)
    workspace_binding: CapabilityBundleProviderBinding = field(repr=False)
    session_inputs: SessionCapabilityCompositionInputs


def compile_coding_base_product_selection(
    selected: PackageProductSelectedPluginManifestV1,
    composition_set: CodingCompositionSetPlan,
    *,
    installation_key: PluginInstallationKeyV1,
    session_id: str,
    host_environment: HostEnvironment,
    evaluated_at: int,
    include_tool_contribution: bool = True,
    include_tool_claim_prompt: bool = True,
    include_skill_contribution: bool = True,
    include_command_contribution: bool = True,
) -> CodingBaseProductCompilation:
    """Admit Product-selected declarations without a peer publication handle."""

    plan, tool_id, tool_names = prepare_coding_base_product_plan(
        selected,
        composition_set,
        installation_key=installation_key,
        session_id=session_id,
        host_environment=host_environment,
        include_tool_contribution=include_tool_contribution,
        include_tool_claim_prompt=include_tool_claim_prompt,
        include_skill_contribution=include_skill_contribution,
        include_command_contribution=include_command_contribution,
    )
    selected_refs = set(plan.selected_contributions)
    candidates = project_selected_product_data_candidates(
        plan,
        (
            (selected, reservation, declaration)
            for reservation, declaration in selected.verified_data_only_declarations()
        ),
        prepare=_candidate,
    )
    if {
        PluginContributionRef(item.plugin_id, item.contribution_id)
        for item in candidates
    } != selected_refs:
        raise CodingBasePluginAssemblyError(
            'Selected Coding base Product declarations are incomplete',
            code='coding_base_product_selection_mismatch',
        )
    owners = {item.owner_id for item in candidates}
    owner_bindings = _owner_bindings(
        include_tools="tools.workspace" in owners,
        include_prompt="resources.prompt" in owners,
        include_skill="resources.skill" in owners,
        include_theme="resources.theme" in owners,
        include_command="commands.session" in owners,
    )
    product_composition = assemble_agent_data_composition(
        plan, candidates, owner_bindings, evaluated_at=evaluated_at
    )
    return CodingBaseProductCompilation(
        plan=plan,
        product_composition=product_composition,
        owner_bindings=owner_bindings,
        host_environment=host_environment,
        selected_manifest=selected,
        tool_contribution_id=tool_id,
        tool_names=tool_names,
        resource_bodies=_resource_bodies(selected, product_composition),
    )


def extend_coding_base_product_data_resources(
    base: CodingBaseProductCompilation,
    external: tuple[PackageProductSelectedPluginManifestV1, ...],
    *,
    evaluated_at: int,
) -> CodingBaseProductCompilation:
    """Compile gated external data Resources under one exact owner set."""

    if not external:
        return base
    if base.plan.selected_plugin_ids != (CODING_BASE_PLUGIN_ID,):
        raise ValueError("External data extension requires the base-only plan")
    if tuple(sorted(item.manifest.name for item in external)) != tuple(
        item.manifest.name for item in external
    ):
        raise ValueError("External data selections must be sorted and unique")
    declarations = _capture_external_resource_declarations(external, standalone=False)
    plan = build_product_data_selection_plan(
        external,
        declarations=declarations,
        product_id=base.plan.context.product_id,
        scope_id=base.plan.context.scope_id,
        policy_revision=base.plan.context.policy_revision,
        base=base.plan,
    )
    base_declarations = (
        (base.selected_manifest, reservation, declaration)
        for reservation, declaration in base.selected_manifest.verified_data_only_declarations()
    )
    candidates = project_selected_product_data_candidates(
        plan, chain(base_declarations, declarations), prepare=_candidate
    )
    builtin_owners = {
        item.owner_id for item in candidates if item.plugin_id == CODING_BASE_PLUGIN_ID
    }
    trust_by_owner = {
        reservation.owner: (
            ("host-equivalent-local", *EXTERNAL_DATA_TRUST_CLASSES_ORDERED)
            if reservation.owner in builtin_owners
            else EXTERNAL_DATA_TRUST_CLASSES_ORDERED
        )
        for _, reservation, _ in declarations
    }
    owners = tuple(
        sorted(
            _bind_coding_external_resource_owners(base.owner_bindings, trust_by_owner),
            key=lambda binding: binding.owner_key,
        )
    )
    composition = assemble_agent_data_composition(
        plan, candidates, owners, evaluated_at=evaluated_at
    )
    return replace(
        base,
        plan=plan,
        product_composition=composition,
        owner_bindings=owners,
        resource_bodies=_resource_bodies(
            base.selected_manifest, composition, external_selected=external
        ),
        selected_external_data_manifests=external,
    )


def _capture_external_resource_declarations(
    selected: tuple[PackageProductSelectedPluginManifestV1, ...],
    *,
    standalone: bool,
) -> tuple[SelectedProductDataDeclaration, ...]:
    invalid = (
        "Product external data Resource selection changed"
        if standalone
        else "External Product data Resource selection changed"
    )
    captured: list[SelectedProductDataDeclaration] = []
    for item in selected:
        reservation, declaration = capture_external_data_declaration(
            item,
            trust_classes=EXTERNAL_DATA_TRUST_CLASSES,
            resource_owners=EXTERNAL_DATA_RESOURCE_OWNERS,
            permits_owner=permits_external_data_owner,
            invalid=invalid,
            standalone=standalone,
        )
        captured.append((item, reservation, declaration))
    return tuple(captured)


def _bind_coding_external_resource_owners(
    bindings: tuple[ProductContributionOwnerBinding, ...],
    trust_by_owner: Mapping[str, tuple[str, ...]],
) -> tuple[ProductContributionOwnerBinding, ...]:
    missing = trust_by_owner.keys() - {item.owner_key[0] for item in bindings}
    if missing:
        bindings = (
            *bindings,
            *_owner_bindings(
                include_tools=False,
                include_prompt="resources.prompt" in missing,
                include_skill="resources.skill" in missing,
                include_theme="resources.theme" in missing,
                include_command=False,
            ),
        )
    return tuple(
        _rebind_resource_owner_trust(binding, trust_by_owner[binding.owner_key[0]])
        if binding.owner_key[0] in trust_by_owner
        else binding
        for binding in bindings
    )


def _resource_bodies(
    selected: PackageProductSelectedPluginManifestV1 | None,
    compilation: ProductCompositionCompilation,
    *,
    external_selected: tuple[PackageProductSelectedPluginManifestV1, ...] = (),
) -> tuple[CodingBaseProductResourceBody, ...]:
    return tuple(
        CodingBaseProductResourceBody(
            admission_fingerprint=admission.fingerprint,
            contribution_id=admission.candidate.contribution_id,
            logical_path=locator,
            content_digest=sha256(body).hexdigest(),
            body=body,
        )
        for admission, locator, body in capture_selected_resource_bodies(
            compilation.resource_admissions,
            ((selected,) if selected is not None else ()) + external_selected,
            reject=_resource_capture_error,
        )
    )


def _resource_capture_error(
    reason: Literal["store_provenance", "unsupported_directory", "missing_body"],
) -> CodingBasePluginAssemblyError:
    if reason == "store_provenance":
        return CodingBasePluginAssemblyError(
            "Product Resource admission changed selected Store provenance",
            code="coding_base_product_resource_mismatch",
        )
    return CodingBasePluginAssemblyError(
        "Product Resource directory has no supported body"
        if reason == "unsupported_directory"
        else "Product Resource body is missing from the selected Store capture",
        code="coding_base_product_resource_unavailable",
    )


def _candidate(
    selected: PackageProductSelectedPluginManifestV1,
    plan: PluginSelectionPlanV2,
    reservation: PluginContributionReservation,
    declaration: PluginDeclaration,
) -> OwnerContributionCandidateEnvelope:
    return prepare_product_selected_contribution_candidate(
        selected,
        plan,
        reservation,
        declaration,
        product_label="Coding base",
        selection_error_code="coding_base_product_selection_mismatch",
        missing_resource_error_code="coding_base_product_resource_missing",
        make_error=lambda message, code: CodingBasePluginAssemblyError(
            message, code=code
        ),
    )


__all__ = [
    "CodingBaseProductCompilation",
    "CodingBaseProductResourceBody",
    "compile_coding_base_product_selection",
    "extend_coding_base_product_data_resources",
]
