"""Bridge finalized Plugin IR into exact Resource/Tool/Command owner facts."""

from __future__ import annotations

from loushang.harness.capabilities.contribution_admission import (
    CatalogConsumerContributionSpec,
    OwnerContributionAdmissionError,
    OwnerContributionCandidateEnvelope,
    OwnerContributionSpec,
    ResourceContributionSpec,
)
from loushang.harness.plugin_authoring.consumer_pack import (
    CommandPackDeclarationPayload,
    ToolPackDeclarationPayload,
)
from loushang.harness.plugin_authoring.resource_item import (
    ResourceItemDeclarationPayload,
)
from loushang.harness.resources.plugins.declarations import (
    PluginDeclarationCodecError,
)
from loushang.harness.resources.plugins.engine import (
    MANAGED_SKILL_ACTION_CONFIGURATION_KEY,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionCandidate,
    PluginSelection,
)


def prepare_owner_contribution_candidate(
    selection: PluginSelection,
    candidate: PluginContributionCandidate,
) -> OwnerContributionCandidateEnvelope:
    """Project one exact finalized inert contribution into owner-layer data."""

    if not isinstance(selection, PluginSelection):
        raise TypeError("Owner contribution preparation requires PluginSelection")
    if not isinstance(candidate, PluginContributionCandidate):
        raise TypeError("Owner contribution preparation requires a Candidate")
    if candidate not in selection.candidates:
        raise OwnerContributionAdmissionError(
            "Owner contribution candidate is outside the finalized selection.",
            code="plugin_candidate_not_selected",
        )
    declaration = candidate.declaration
    contribution: OwnerContributionSpec
    try:
        if declaration.kind == "resource_item":
            resource_payload = ResourceItemDeclarationPayload.from_candidate(candidate)
            reservation = next(
                item
                for item in candidate.package.contribution_index.items
                if item.contribution_id == declaration.contribution_id
            )
            contribution = ResourceContributionSpec(
                resource_kind=resource_payload.resource_kind,
                locator=resource_payload.locator,
                locator_kind=resource_payload.locator_kind,
                media_type=resource_payload.media_type,
                schema_id=resource_payload.schema_id,
                schema_version=resource_payload.schema_version,
                managed_skill_actions=(
                    reservation.configuration.get(
                        MANAGED_SKILL_ACTION_CONFIGURATION_KEY
                    )
                    is True
                ),
            )
        elif declaration.kind == "tool_pack":
            tool_payload = ToolPackDeclarationPayload.from_candidate(candidate)
            contribution = CatalogConsumerContributionSpec(
                contribution_kind="tool_pack",
                catalog_id=tool_payload.catalog_id,
                catalog_revision=tool_payload.catalog_revision,
                item_ids=tool_payload.item_ids,
                requirements=tool_payload.requirements,
            )
        elif declaration.kind == "command_pack":
            command_payload = CommandPackDeclarationPayload.from_candidate(candidate)
            contribution = CatalogConsumerContributionSpec(
                contribution_kind="command_pack",
                catalog_id=command_payload.catalog_id,
                catalog_revision=command_payload.catalog_revision,
                item_ids=command_payload.item_ids,
                requirements=command_payload.requirements,
            )
        else:
            raise OwnerContributionAdmissionError(
                "Plugin candidate is not an owner-admitted external contribution.",
                code="unsupported_owner_contribution_kind",
            )
    except PluginDeclarationCodecError as exc:
        raise OwnerContributionAdmissionError(
            "Owner contribution declaration payload is invalid.",
            code="invalid_owner_contribution_declaration",
        ) from exc

    package = candidate.package
    plugin_id = package.manifest.name
    trust_by_plugin = {
        item.plugin_id: item for item in selection.plan.source_trust_snapshots
    }
    instance_by_plugin = {
        item.plugin_id: item
        for item in selection.plan.context.instance_revision_refs
    }
    trust = trust_by_plugin.get(plugin_id)
    instance = instance_by_plugin.get(plugin_id)
    if trust is None or instance is None:
        raise OwnerContributionAdmissionError(
            "Owner contribution Product provenance is incomplete.",
            code="contribution_selection_provenance_missing",
        )
    return OwnerContributionCandidateEnvelope(
        owner_id=declaration.owner,
        plugin_id=plugin_id,
        contribution_id=declaration.contribution_id,
        contribution=contribution,
        plugin_candidate_fingerprint=candidate.fingerprint,
        declaration_fingerprint=declaration.fingerprint,
        declaration_evidence_fingerprint=candidate.evidence.fingerprint,
        package_content_digest=package.content_digest,
        dependency_lock_digest=package.dependency_lock.digest,
        product_id=selection.plan.context.product_id,
        scope_id=selection.plan.context.scope_id,
        product_policy_revision=selection.plan.context.policy_revision,
        instance_revision_ref=instance,
        package_source_identity=trust.package_source_identity,
        source_trust_class=trust.source_trust_class,
        source_trust_policy_revision=trust.source_trust_policy_revision,
        source_trusted=trust.trusted,
    )


__all__: list[str] = []
