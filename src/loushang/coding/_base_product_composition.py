"""Path-free Product composition for the selected data-only Coding base."""

from __future__ import annotations

import json
from dataclasses import dataclass
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
from loushang.harness.environment import HostEnvironment
from loushang.harness.plugin_authoring.consumer_pack import (
    CommandPackDeclarationPayload,
    ToolPackDeclarationPayload,
)
from loushang.harness.plugin_authoring.resource_item import (
    ResourceItemDeclarationPayload,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
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
from loushang.harness.session.product_composition_assembly import (
    _assemble_product_contribution_candidates,
)

if TYPE_CHECKING:
    from loushang.harness.resources.packages.product_local_wheel_runtime import (
        PackageProductSelectedPluginManifestV1,
    )


@dataclass(frozen=True, slots=True)
class CodingBaseProductCompilation:
    plan: PluginSelectionPlanV2
    product_composition: ProductCompositionCompilation
    tool_contribution_id: str | None
    tool_names: tuple[str, ...]


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
        tool_contribution_id=tool_id,
        tool_names=tool_names,
    )


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


__all__ = ["CodingBaseProductCompilation", "compile_coding_base_product_selection"]
