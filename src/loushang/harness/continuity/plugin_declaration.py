"""Strict installed-Plugin declaration bridge owned by Continuity."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.capabilities.component_admission import (
    CAPABILITY_COMPONENT_CANDIDATE_VERSION_V2,
    CapabilityComponentAdmissionError,
    CapabilityComponentCandidate,
)
from loushang.harness.capabilities.component_contracts import (
    CapabilityComponentBindingSpec,
    CapabilityComponentDefinition,
)
from loushang.harness.capabilities.contracts import CapabilityContractRange
from loushang.harness.continuity.import_provider import (
    MAX_CONTINUITY_IMPORT_PROVIDERS,
    ContinuityImportProviderPack,
)
from loushang.harness.resources.plugins.continuity_provider import (
    CONTINUITY_PROVIDER_DECLARATION_OWNER,
    CONTINUITY_PROVIDER_PAYLOAD_VERSION,
    ContinuityProviderDeclarationWirePayloadV2,
    decode_continuity_provider_declaration_payload,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclarationCodecError,
    _thaw_json,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionCandidate,
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginSelection,
)

CONTINUITY_PROVIDER_CONTRIBUTION_KIND = "continuity_provider"
CONTINUITY_PROVIDER_COMPONENT_KIND = "continuity.provider"
CONTINUITY_PROVIDER_PAYLOAD_SCHEMA_ID = "loushang.continuity-import-provider-pack"
CONTINUITY_PLUGIN_DELETE_AUTHORITY = "continuity.delete"

CONTINUITY_PROVIDER_COMPONENT_DEFINITION = CapabilityComponentDefinition(
    capability_id="harness.continuity",
    owner_id="harness",
    component_kind=CONTINUITY_PROVIDER_COMPONENT_KIND,
    payload_schema_id=CONTINUITY_PROVIDER_PAYLOAD_SCHEMA_ID,
    payload_schema_version=1,
    compatible_bundle_contract=CapabilityContractRange.exact(1),
    multiplicity="aggregate",
    selection_policy="ordered_unique",
    minimum_count=0,
    maximum_count=MAX_CONTINUITY_IMPORT_PROVIDERS,
    disposer_contract="required",
)


@dataclass(frozen=True, slots=True)
class ContinuityProviderDeclarationPayload(ContinuityProviderDeclarationWirePayloadV2):
    """Continuity-owned wire payload plus finalized-selection semantics."""

    @classmethod
    def from_finalized_candidate(
        cls,
        selection: PluginSelection,
        candidate: PluginContributionCandidate,
    ) -> ContinuityProviderDeclarationPayload:
        """Decode only an exact Candidate from its finalized Product selection."""

        contribution, configuration = _selected_candidate_facts(selection, candidate)
        declaration = candidate.declaration
        if (
            declaration.kind != CONTINUITY_PROVIDER_CONTRIBUTION_KIND
            or declaration.owner != CONTINUITY_PROVIDER_DECLARATION_OWNER
        ):
            raise ValueError("Continuity Provider declaration owner or kind mismatch")
        wire_payload = decode_continuity_provider_declaration_payload(
            declaration.to_dict()["payload"]
        )
        payload = cls(
            factory=wire_payload.factory,
            disposer=wire_payload.disposer,
            supported_actions=getattr(
                wire_payload,
                "supported_actions",
                ("activate",),
            ),
            binding_inputs=wire_payload.binding_inputs,
            continuity_profile_version=wire_payload.continuity_profile_version,
        )
        if payload.to_dict()["bindingInputs"] != _thaw_json(
            configuration.configuration
        ):
            raise ValueError(
                "Continuity Provider binding inputs must match Product configuration"
            )
        for reference in (payload.factory, payload.disposer):
            if reference.execution_model != contribution.contribution_execution_model:
                raise ValueError(
                    "Continuity Provider symbol model must match its reservation"
                )
        return payload


def prepare_continuity_provider_component_candidate(
    selection: PluginSelection,
    candidate: PluginContributionCandidate,
) -> CapabilityComponentCandidate:
    """Compile one finalized Continuity declaration into exact owner input."""

    try:
        contribution, _configuration = _selected_candidate_facts(
            selection,
            candidate,
        )
        payload = ContinuityProviderDeclarationPayload.from_finalized_candidate(
            selection,
            candidate,
        )
        if (
            "delete" in payload.supported_actions
            and CONTINUITY_PLUGIN_DELETE_AUTHORITY
            not in contribution.requested_authorities
        ):
            raise ValueError(
                "Continuity delete action requires its declared Plugin authority"
            )
    except (PluginDeclarationCodecError, TypeError, ValueError) as exc:
        raise CapabilityComponentAdmissionError(
            "Continuity Provider declaration payload is invalid.",
            code="invalid_continuity_provider_declaration",
        ) from exc

    plugin_id = candidate.package.manifest.name
    instance_by_plugin = {
        item.plugin_id: item for item in selection.plan.context.instance_revision_refs
    }
    trust_by_plugin = {
        item.plugin_id: item for item in selection.plan.source_trust_snapshots
    }
    instance = instance_by_plugin.get(plugin_id)
    trust = trust_by_plugin.get(plugin_id)
    if instance is None or trust is None:
        raise CapabilityComponentAdmissionError(
            "Continuity Provider Product provenance is incomplete.",
            code="continuity_provider_selection_provenance_missing",
        )
    declaration = candidate.declaration
    return CapabilityComponentCandidate(
        definition=CONTINUITY_PROVIDER_COMPONENT_DEFINITION,
        component_id=continuity_provider_component_id(
            plugin_id,
            declaration.contribution_id,
        ),
        binding_spec=CapabilityComponentBindingSpec(
            source_kind="plugin",
            source_id=plugin_id,
            contribution_id=declaration.contribution_id,
            source_revision_ref=f"{instance.instance_id}:r{instance.revision}",
            content_digest=candidate.package.content_digest,
            plugin_id=plugin_id,
            dependency_lock_digest=candidate.package.dependency_lock.digest,
            factory_path=payload.factory.path,
            factory_symbol=payload.factory.symbol,
            disposer_path=payload.disposer.path,
            disposer_symbol=payload.disposer.symbol,
            binding_inputs=payload.binding_inputs,
        ),
        product_id=selection.plan.context.product_id,
        scope_id=selection.plan.context.scope_id,
        product_policy_revision=selection.plan.context.policy_revision,
        source_trust_class=trust.source_trust_class,
        source_trust_policy_revision=trust.source_trust_policy_revision,
        source_trusted=trust.trusted,
        package_source_identity=trust.package_source_identity,
        instance_revision_ref=instance,
        plugin_candidate_fingerprint=candidate.fingerprint,
        declaration_fingerprint=declaration.fingerprint,
        declaration_evidence_fingerprint=candidate.evidence.fingerprint,
        allowed_authority_ceiling=selection.plan.allowed_authority_ceiling,
        requested_authorities=contribution.requested_authorities,
        candidate_version=CAPABILITY_COMPONENT_CANDIDATE_VERSION_V2,
    )


def continuity_provider_component_id(plugin_id: str, contribution_id: str) -> str:
    if not isinstance(plugin_id, str) or not plugin_id.strip():
        raise ValueError("Continuity Provider Plugin id must be non-empty")
    if not isinstance(contribution_id, str) or not contribution_id.strip():
        raise ValueError("Continuity Provider contribution id must be non-empty")
    return f"plugin:{plugin_id}:{contribution_id}"


def validate_continuity_provider_component_payload(payload: object) -> None:
    if not isinstance(payload, ContinuityImportProviderPack):
        raise TypeError(
            "Continuity Provider component must return ContinuityImportProviderPack"
        )


def _selected_candidate_facts(
    selection: PluginSelection,
    candidate: PluginContributionCandidate,
) -> tuple[PluginContributionReservation, PluginEffectiveConfigurationEntry]:
    if not isinstance(selection, PluginSelection):
        raise TypeError("Continuity Provider decoder requires PluginSelection")
    if not isinstance(candidate, PluginContributionCandidate):
        raise TypeError("Continuity Provider decoder requires a finalized Candidate")
    if candidate not in selection.candidates:
        raise ValueError("Continuity Provider candidate is outside its selection")
    plugin_id = candidate.package.manifest.name
    declaration = candidate.declaration
    ref = PluginContributionRef(plugin_id, declaration.contribution_id)
    contributions = tuple(
        item
        for item in candidate.package.contribution_index.items
        if item.contribution_id == declaration.contribution_id
    )
    configurations = tuple(
        item
        for item in selection.plan.effective_configuration_set.entries
        if item.ref == ref
    )
    if len(contributions) != 1 or len(configurations) != 1:
        raise ValueError("Continuity Provider reservation facts are incomplete")
    contribution = contributions[0]
    if (
        contribution.kind != CONTINUITY_PROVIDER_CONTRIBUTION_KIND
        or contribution.owner != CONTINUITY_PROVIDER_DECLARATION_OWNER
        or declaration.plugin_id != plugin_id
        or declaration.contribution_id != contribution.contribution_id
        or declaration.kind != contribution.kind
        or declaration.owner != contribution.owner
        or declaration.reservation_fingerprint != contribution.fingerprint
        or declaration.source_descriptor_fingerprint
        != contribution.source_descriptor_fingerprint
        or declaration.source_kind != contribution.declaration_source.kind
        or contribution.contribution_execution_model != "in_process"
    ):
        raise ValueError("Continuity Provider declaration changed its reservation")
    return contribution, configurations[0]


__all__ = [
    "CONTINUITY_PROVIDER_COMPONENT_DEFINITION",
    "CONTINUITY_PROVIDER_COMPONENT_KIND",
    "CONTINUITY_PROVIDER_CONTRIBUTION_KIND",
    "CONTINUITY_PROVIDER_DECLARATION_OWNER",
    "CONTINUITY_PROVIDER_PAYLOAD_VERSION",
    "ContinuityProviderDeclarationPayload",
    "CONTINUITY_PLUGIN_DELETE_AUTHORITY",
    "continuity_provider_component_id",
    "prepare_continuity_provider_component_candidate",
    "validate_continuity_provider_component_payload",
]
