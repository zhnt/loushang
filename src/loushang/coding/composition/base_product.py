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
    MODEL_INPUT_CAPABILITY_DEFINITION,
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
from loushang.harness.capabilities.provider_selection import (
    ProductCapabilityProviderResolver,
    ProductCapabilityProviderSelectionPlanV1,
)
from loushang.harness.environment import HostEnvironment
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resource_catalog.product_snapshot_source import (
    ProductSelectedResourceInput,
    capture_selected_resource_bodies,
    project_selected_resource_inputs,
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
    validate_session_capability_composition_closure,
)
from loushang.harness.session.product_composition_assembly import (
    ProductContributionOwnerBinding as ProductContributionOwnerBinding,
)
from loushang.harness.session.product_composition_assembly import (
    SelectedProductDataDeclaration,
    build_product_data_selection_plan,
    prepare_product_selected_contribution_candidate,
)
from loushang.harness.session.product_composition_assembly import (
    _assemble_product_contribution_candidates as _assemble_product_contribution_candidates,
)
from loushang.harness.tools.workspace.factory import ToolsOptions

if TYPE_CHECKING:
    from loushang.harness.package_product.product_local_wheel_runtime import (
        PackageProductSelectedPluginManifestV1,
    )


_EXTERNAL_RESOURCE_OWNERS = frozenset(
    {"resources.skill", "resources.prompt", "resources.theme"}
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
        context = self.product_composition.authority_context
        if (
            self.plan.context.product_id != context.product_id
            or self.plan.context.scope_id != context.scope_id
            or self.plan.context.policy_revision != context.product_policy_revision
            or tuple(item.authority.snapshot() for item in self.owner_bindings)
            != context.owner_snapshots
        ):
            raise ValueError("Product Coding base changed owner authority facts")
        expected = {
            item.fingerprint: item.contribution_id
            for item in self.product_composition.resource_admissions
        }
        actual = {
            item.admission_fingerprint: item.contribution_id
            for item in self.resource_bodies
        }
        if actual != expected or len(actual) != len(self.resource_bodies):
            raise ValueError("Product Resource bodies changed owner admissions")
        capability_ids = tuple(
            item.verified_manifest().name
            for item in (
                *self.selected_capability_manifests,
                *self.selected_external_data_manifests,
            )
        )
        if tuple(sorted(capability_ids)) != tuple(
            plugin_id
            for plugin_id in self.plan.selected_plugin_ids
            if plugin_id != "coding.base"
        ):
            raise ValueError("Product manifests changed the selected plan")
        instance_refs = {
            item.plugin_id: item for item in self.plan.context.instance_revision_refs
        }
        trust = {item.plugin_id: item for item in self.plan.source_trust_snapshots}
        if any(
            selected.snapshot.instance_revision_ref
            != instance_refs.get(selected.manifest.name)
            or selected.source_trust_snapshot != trust.get(selected.manifest.name)
            for selected in (
                *self.selected_capability_manifests,
                *self.selected_external_data_manifests,
            )
        ):
            raise ValueError("Product manifests changed B selection facts")
        selected_by_id = {
            item.manifest.name: item
            for item in (
                self.selected_manifest,
                *self.selected_external_data_manifests,
            )
        }
        for admission in self.product_composition.resource_admissions:
            captured = next(
                item
                for item in self.resource_bodies
                if item.admission_fingerprint == admission.fingerprint
            )
            input_record = ProductSelectedResourceInput(
                admission=admission,
                selected_manifest=selected_by_id[admission.plugin_id],
                relative_path=captured.logical_path,
            )
            if input_record.body != captured.body:
                raise ValueError("Product Resource body changed selected Store bytes")

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
            {item.admission_fingerprint: item.logical_path for item in self.resource_bodies},
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
        context = self.product_composition.authority_context
        resolved = ProductCapabilityProviderResolver().resolve(
            ProductCapabilityProviderSelectionPlanV1(
                product_id=context.product_id,
                roots=(),
                choices=(),
                policy_revision=context.product_policy_revision,
            ),
            definitions=(
                MODEL_INPUT_CAPABILITY_DEFINITION,
                WORKSPACE_CAPABILITY_DEFINITION,
            ),
            admissions=(),
            owner_snapshots=(),
            evaluated_at=context.evaluated_at,
            prebound_providers=(workspace,),
        )
        validate_session_capability_composition_closure(
            self.product_composition,
            resolved,
            host_capability_ids=(
                MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
                WORKSPACE_CAPABILITY_DEFINITION.capability_id,
            ),
            host_providers=(workspace,),
        )
        return CodingBaseProductSessionAssembly(
            compilation=self,
            workspace_binding=workspace_binding,
            session_inputs=SessionCapabilityCompositionInputs(
                product_composition=self.product_composition,
                resolved_providers=resolved,
                component_requests=(),
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
    pairs = selected.verified_data_only_declarations()
    candidates = tuple(
        _candidate(selected, plan, reservation, declaration)
        for reservation, declaration in pairs
        if PluginContributionRef(
            CODING_BASE_PLUGIN_ID,
            reservation.contribution_id,
        )
        in selected_refs
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
    product_composition = _compile_coding_resource_candidates(
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
    candidates = tuple(
        _candidate(selected, plan, reservation, declaration)
        for selected, reservation, declaration in chain(base_declarations, declarations)
        if PluginContributionRef(selected.manifest.name, reservation.contribution_id)
        in plan.selected_contributions
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
    composition = _compile_coding_resource_candidates(
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
    captured: list[SelectedProductDataDeclaration] = []
    for item in selected:
        trust = item.source_trust_snapshot
        declarations = item.verified_data_only_declarations()
        if standalone:
            if (
                not isinstance(trust, PluginSourceTrustSnapshotV1)
                or _external_selection_rejected(trust, declarations)
                or item.snapshot.installation_key.plugin_id != item.manifest.name
                or item.snapshot.instance_revision_ref.plugin_id != item.manifest.name
            ):
                raise ValueError("Product external data Resource selection changed")
        elif trust is None or _external_selection_rejected(trust, declarations):
            raise ValueError("External Product data Resource selection changed")
        ((reservation, declaration),) = declarations
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
        ProductContributionOwnerBinding(
            authority=OwnerContributionAuthority(
                replace(
                    binding.authority.policy,
                    allowed_source_trust_classes=trust_by_owner[binding.owner_key[0]],
                )
            ),
            admission_ttl_seconds=binding.admission_ttl_seconds,
        )
        if binding.owner_key[0] in trust_by_owner
        else binding
        for binding in bindings
    )


def _compile_coding_resource_candidates(
    plan: PluginSelectionPlanV2,
    candidates: tuple[OwnerContributionCandidateEnvelope, ...],
    owner_bindings: tuple[ProductContributionOwnerBinding, ...],
    *,
    evaluated_at: int,
) -> ProductCompositionCompilation:
    return _assemble_product_contribution_candidates(
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


def _external_selection_rejected(
    trust: PluginSourceTrustSnapshotV1,
    declarations: tuple[
        tuple[PluginContributionReservation, PluginDeclaration], ...
    ],
) -> bool:
    """Apply the same admission constraints after each path classifies trust."""
    return (
        not trust.trusted
        or trust.source_trust_class not in EXTERNAL_DATA_TRUST_CLASSES
        or len(declarations) != 1
        or not permits_external_data_owner(
            trust.source_trust_class, declarations[0][0].owner
        )
        or declarations[0][0].kind != "resource_item"
        or declarations[0][0].owner not in _EXTERNAL_RESOURCE_OWNERS
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
