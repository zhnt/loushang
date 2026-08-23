"""Upper-layer bridge from finalized Plugin IR to Capability admission data."""

from __future__ import annotations

from loushang.harness.capabilities.contracts import CapabilityDefinition
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderAdmissionError,
    CapabilityProviderBindingSpec,
    CapabilityProviderCandidateEnvelope,
    CapabilityProviderSymbolLocator,
)
from loushang.harness.plugin_authoring.capability_provider import (
    PluginSymbolReference,
    _capability_provider_payload_from_finalized_candidate,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionCandidate,
    PluginSelection,
)


def prepare_capability_provider_candidate(
    selection: PluginSelection,
    candidate: PluginContributionCandidate,
    *,
    definition: CapabilityDefinition,
) -> CapabilityProviderCandidateEnvelope:
    """Bind one exact finalized Candidate to inert Capability owner inputs."""

    if not isinstance(selection, PluginSelection):
        raise TypeError("Capability Provider preparation requires PluginSelection")
    if not isinstance(candidate, PluginContributionCandidate):
        raise TypeError("Capability Provider preparation requires a Candidate")
    if not isinstance(definition, CapabilityDefinition):
        raise TypeError("Capability Provider preparation requires a Definition")
    if candidate not in selection.candidates:
        raise CapabilityProviderAdmissionError(
            "Capability Provider candidate is outside the finalized selection.",
            code="plugin_candidate_not_selected",
        )

    try:
        payload = _capability_provider_payload_from_finalized_candidate(
            selection,
            candidate,
        )
    except (TypeError, ValueError) as exc:
        raise CapabilityProviderAdmissionError(
            "Capability Provider declaration payload is invalid.",
            code="invalid_capability_provider_declaration",
        ) from exc

    package = candidate.package
    declaration = candidate.declaration
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
        raise CapabilityProviderAdmissionError(
            "Capability Provider Product provenance is incomplete.",
            code="provider_selection_provenance_missing",
        )

    binding_spec = CapabilityProviderBindingSpec(
        plugin_id=plugin_id,
        contribution_id=declaration.contribution_id,
        package_content_digest=package.content_digest,
        dependency_lock_digest=package.dependency_lock.digest,
        factory=_binding_locator(payload.factory),
        disposer=(
            None
            if payload.disposer is None
            else _binding_locator(payload.disposer)
        ),
        binding_inputs=payload.binding_inputs,
    )
    return CapabilityProviderCandidateEnvelope(
        definition=definition,
        provider=payload.provider,
        binding_spec=binding_spec,
        plugin_candidate_fingerprint=candidate.fingerprint,
        declaration_fingerprint=declaration.fingerprint,
        declaration_evidence_fingerprint=candidate.evidence.fingerprint,
        product_id=selection.plan.context.product_id,
        scope_id=selection.plan.context.scope_id,
        product_policy_revision=selection.plan.context.policy_revision,
        instance_revision_ref=instance,
        package_source_identity=trust.package_source_identity,
        source_trust_class=trust.source_trust_class,
        source_trust_policy_revision=trust.source_trust_policy_revision,
        source_trusted=trust.trusted,
        allowed_authority_ceiling=selection.plan.allowed_authority_ceiling,
    )


def _binding_locator(
    reference: PluginSymbolReference,
) -> CapabilityProviderSymbolLocator:
    if reference.execution_model != "in_process":
        raise ValueError("Capability Provider binding requires in-process locators")
    return CapabilityProviderSymbolLocator(
        path=reference.path,
        symbol=reference.symbol,
        execution_model=reference.execution_model,
    )


__all__: list[str] = []
