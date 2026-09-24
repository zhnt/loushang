"""Path-free Product composition for the selected data-only Coding base."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING

from loushang.coding._base_plugin import (
    CodingBasePluginAssemblyError,
    _owner_bindings,
    prepare_coding_base_product_plan,
)
from loushang.coding.composition_sets import CodingCompositionSetPlan
from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionCompilation,
)
from loushang.harness.capabilities.contribution_admission import (
    CatalogConsumerContributionSpec,
    OwnerContributionCandidateEnvelope,
    OwnerContributionSpec,
    ResourceContributionSpec,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.capabilities.provider_selection import (
    ProductCapabilityProviderResolver,
    ProductCapabilityProviderSelectionPlanV1,
)
from loushang.harness.environment import HostEnvironment
from loushang.harness.plugin_authoring.consumer_pack import (
    CommandPackDeclarationPayload,
    ToolPackDeclarationPayload,
)
from loushang.harness.plugin_authoring.resource_item import (
    ResourceItemDeclarationPayload,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resource_catalog.product_snapshot_source import (
    ProductSelectedResourceInput,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
)
from loushang.harness.resources.plugins.engine import (
    MANAGED_SKILL_ACTION_CONFIGURATION_KEY,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef,
    PluginSelectionPlanV2,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
    validate_session_capability_composition_closure,
)
from loushang.harness.session.product_composition_assembly import (
    _assemble_product_contribution_candidates,
)

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
    selected_manifest: PackageProductSelectedPluginManifestV1 = field(
        repr=False, compare=False
    )
    tool_contribution_id: str | None
    tool_names: tuple[str, ...]
    resource_bodies: tuple[CodingBaseProductResourceBody, ...] = field(repr=False)

    def __post_init__(self) -> None:
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
        for admission in self.product_composition.resource_admissions:
            captured = next(
                item
                for item in self.resource_bodies
                if item.admission_fingerprint == admission.fingerprint
            )
            input_record = ProductSelectedResourceInput(
                admission=admission,
                selected_manifest=self.selected_manifest,
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

        by_fingerprint = {
            item.admission_fingerprint: item for item in self.resource_bodies
        }
        return tuple(
            ProductSelectedResourceInput(
                admission=admission,
                selected_manifest=self.selected_manifest,
                relative_path=by_fingerprint[admission.fingerprint].logical_path,
            )
            for admission in self.product_composition.resource_admissions
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
            session_inputs=SessionCapabilityCompositionInputs(
                product_composition=self.product_composition,
                resolved_providers=resolved,
                component_requests=(),
            ),
        )


@dataclass(frozen=True, slots=True)
class CodingBaseProductSessionAssembly:
    compilation: CodingBaseProductCompilation = field(repr=False)
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
        if PluginContributionRef("coding.base", reservation.contribution_id)
        in selected_refs
    )
    if {
        PluginContributionRef(item.plugin_id, item.contribution_id)
        for item in candidates
    } != selected_refs:
        raise CodingBasePluginAssemblyError(
            "Selected Coding base Product declarations are incomplete",
            code="coding_base_product_selection_mismatch",
        )
    owners = {item.owner_id for item in candidates}
    product_composition = _assemble_product_contribution_candidates(
        plan=plan,
        candidates=candidates,
        owner_bindings=_owner_bindings(
            include_tools="tools.workspace" in owners,
            include_prompt="resources.prompt" in owners,
            include_skill="resources.skill" in owners,
            include_command="commands.session" in owners,
        ),
        mandatory_roots=(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
        definitions=(
            MODEL_INPUT_CAPABILITY_DEFINITION,
            WORKSPACE_CAPABILITY_DEFINITION,
        ),
        select_optional_requirements=lambda _preview: (),
        evaluated_at=evaluated_at,
    )
    return CodingBaseProductCompilation(
        plan=plan,
        product_composition=product_composition,
        selected_manifest=selected,
        tool_contribution_id=tool_id,
        tool_names=tool_names,
        resource_bodies=_resource_bodies(selected, product_composition),
    )


def _resource_bodies(
    selected: PackageProductSelectedPluginManifestV1,
    compilation: ProductCompositionCompilation,
) -> tuple[CodingBaseProductResourceBody, ...]:
    snapshot = selected.snapshot
    members = dict(snapshot.files)
    root = selected.manifest.root_relative_path.as_posix()
    bodies: list[CodingBaseProductResourceBody] = []
    for admission in compilation.resource_admissions:
        candidate = admission.candidate
        resource = candidate.contribution
        if (
            not isinstance(resource, ResourceContributionSpec)
            or candidate.package_content_digest
            != snapshot.package_revision.package_content_digest
            or candidate.instance_revision_ref != snapshot.instance_revision_ref
        ):
            raise CodingBasePluginAssemblyError(
                "Product Resource admission changed selected Store provenance",
                code="coding_base_product_resource_mismatch",
            )
        locator = resource.locator
        if resource.locator_kind == "directory":
            if resource.resource_kind != "skill":
                raise CodingBasePluginAssemblyError(
                    "Product Resource directory has no supported body",
                    code="coding_base_product_resource_unavailable",
                )
            locator = f"{locator}/SKILL.md"
        captured_path = locator if root == "." else f"{root}/{locator}"
        body = members.get(captured_path)
        if body is None:
            raise CodingBasePluginAssemblyError(
                "Product Resource body is missing from the selected Store capture",
                code="coding_base_product_resource_unavailable",
            )
        bodies.append(
            CodingBaseProductResourceBody(
                admission_fingerprint=admission.fingerprint,
                contribution_id=candidate.contribution_id,
                logical_path=locator,
                content_digest=sha256(body).hexdigest(),
                body=body,
            )
        )
    return tuple(bodies)


def _candidate(
    selected: PackageProductSelectedPluginManifestV1,
    plan: PluginSelectionPlanV2,
    reservation: PluginContributionReservation,
    declaration: PluginDeclaration,
) -> OwnerContributionCandidateEnvelope:
    snapshot = selected.snapshot
    manifest = selected.manifest
    if declaration.plugin_id != "coding.base":
        raise CodingBasePluginAssemblyError(
            "Selected Coding base declaration changed Plugin identity",
            code="coding_base_product_selection_mismatch",
        )
    contribution: OwnerContributionSpec
    payload = declaration.to_dict()["payload"]
    if declaration.kind == "resource_item":
        resource = ResourceItemDeclarationPayload.from_dict(payload)
        _require_product_locator(selected, resource)
        contribution = ResourceContributionSpec(
            resource_kind=resource.resource_kind,
            locator=resource.locator,
            locator_kind=resource.locator_kind,
            media_type=resource.media_type,
            schema_id=resource.schema_id,
            schema_version=resource.schema_version,
            managed_skill_actions=(
                reservation.configuration.get(MANAGED_SKILL_ACTION_CONFIGURATION_KEY)
                is True
            ),
        )
        owner_namespace = resource.owner_namespace
    elif declaration.kind in {"tool_pack", "command_pack"}:
        consumer = (
            ToolPackDeclarationPayload.from_dict(payload)
            if declaration.kind == "tool_pack"
            else CommandPackDeclarationPayload.from_dict(payload)
        )
        contribution = CatalogConsumerContributionSpec(
            contribution_kind=(
                "tool_pack" if declaration.kind == "tool_pack" else "command_pack"
            ),
            catalog_id=consumer.catalog_id,
            catalog_revision=consumer.catalog_revision,
            item_ids=consumer.item_ids,
            requirements=consumer.requirements,
        )
        owner_namespace = consumer.owner_namespace
    else:
        raise CodingBasePluginAssemblyError(
            "Selected Coding base contribution kind is unsupported",
            code="coding_base_product_selection_mismatch",
        )
    if owner_namespace != reservation.owner or reservation.requested_authorities:
        raise CodingBasePluginAssemblyError(
            "Selected Coding base owner or authority changed",
            code="coding_base_product_selection_mismatch",
        )
    root = manifest.root_relative_path.as_posix()
    source_path = reservation.declaration_source.relative_path.as_posix()
    document_path = source_path if root == "." else f"{root}/{source_path}"
    document = dict(selected.declaration_documents)[document_path]
    evidence_fingerprint = _digest(
        "loushang.product-selected-declaration-evidence/v1",
        {
            "committedSetId": snapshot.committed_record.committed_set.set_id,
            "declarationFingerprint": declaration.fingerprint,
            "documentBytesDigest": document.bytes_digest,
            "documentPath": document_path,
            "reservationFingerprint": reservation.fingerprint,
            "rootRef": snapshot.root_ref.to_dict(),
        },
    )
    trust = plan.source_trust_snapshots[0]
    candidate_fingerprint = _digest(
        "loushang.product-selected-plugin-candidate/v1",
        {
            "declarationEvidenceFingerprint": evidence_fingerprint,
            "declarationFingerprint": declaration.fingerprint,
            "instanceRevisionRef": snapshot.instance_revision_ref.to_dict(),
            "packageSourceIdentity": trust.package_source_identity,
            "policyRevision": plan.context.policy_revision,
            "productId": plan.context.product_id,
            "scopeId": plan.context.scope_id,
            "sourceTrustClass": trust.source_trust_class,
            "sourceTrustPolicyRevision": trust.source_trust_policy_revision,
        },
    )
    return OwnerContributionCandidateEnvelope(
        owner_id=reservation.owner,
        plugin_id=manifest.name,
        contribution_id=reservation.contribution_id,
        contribution=contribution,
        plugin_candidate_fingerprint=candidate_fingerprint,
        declaration_fingerprint=declaration.fingerprint,
        declaration_evidence_fingerprint=evidence_fingerprint,
        package_content_digest=snapshot.package_revision.package_content_digest,
        dependency_lock_digest=snapshot.package_revision.dependency_lock_digest,
        product_id=plan.context.product_id,
        scope_id=plan.context.scope_id,
        product_policy_revision=plan.context.policy_revision,
        instance_revision_ref=snapshot.instance_revision_ref,
        package_source_identity=trust.package_source_identity,
        source_trust_class=trust.source_trust_class,
        source_trust_policy_revision=trust.source_trust_policy_revision,
        source_trusted=trust.trusted,
    )


def _require_product_locator(
    selected: PackageProductSelectedPluginManifestV1,
    payload: ResourceItemDeclarationPayload,
) -> None:
    root = selected.manifest.root_relative_path.as_posix()
    locator = payload.locator if root == "." else f"{root}/{payload.locator}"
    files = {path for path, _ in selected.snapshot.files}
    if payload.locator_kind == "file":
        valid = locator in files
    else:
        valid = locator not in files and any(
            path.startswith(f"{locator}/") for path in files
        )
    if not valid:
        raise CodingBasePluginAssemblyError(
            "Selected Coding base Resource locator is outside the Product root",
            code="coding_base_product_resource_missing",
        )


def _digest(domain: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256(domain.encode("ascii") + b"\0" + encoded).hexdigest()


__all__ = [
    "CodingBaseProductCompilation",
    "CodingBaseProductResourceBody",
    "compile_coding_base_product_selection",
]
