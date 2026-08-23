from __future__ import annotations

from typing import Protocol

import pytest

from loushang.harness.capabilities import CapabilityDefinition
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderAdmissionError,
    CapabilityProviderAdmissionRecord,
    CapabilityProviderCandidateEnvelope,
    CapabilityProviderEligibilityGrant,
    CapabilityProviderOwnerAuthority,
    CapabilityProviderOwnerPolicy,
)
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
from loushang.harness.plugin_authoring.provider_admission import (
    prepare_capability_provider_candidate,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
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
    PluginSourceBinding,
    PublishedPluginPackage,
)


class _PublishedPlugin(Protocol):
    package: PublishedPluginPackage
    binding: PluginSourceBinding
    contribution: PluginContributionReservation


def test_plugin_candidate_preparation_binds_exact_finalized_selection(
    published_document_plugin: _PublishedPlugin,
) -> None:
    selection = _selection(published_document_plugin)
    definition = _definition()

    candidate = prepare_capability_provider_candidate(
        selection,
        selection.candidates[0],
        definition=definition,
    )

    assert candidate.definition == definition
    assert candidate.provider.provider_id == "org.loushang.document/default"
    assert candidate.plugin_candidate_fingerprint == (
        selection.candidates[0].fingerprint
    )
    assert candidate.binding_spec.factory.path == "provider.py"
    assert candidate.binding_spec.binding_inputs == {}
    assert candidate.product_id == "coding"
    assert candidate.scope_id == "workspace:test"
    assert candidate.fingerprint.to_dict()["digest"] == candidate.fingerprint.digest
    assert candidate.to_dict()["fingerprint"] == candidate.fingerprint.to_dict()
    assert not _contains_callable(candidate.to_dict())


def test_owner_is_the_only_grant_and_admission_constructor(
    published_document_plugin: _PublishedPlugin,
) -> None:
    candidate = _candidate(published_document_plugin)
    authority = _authority()

    with pytest.raises(TypeError, match="owner-constructed"):
        CapabilityProviderEligibilityGrant()
    with pytest.raises(TypeError, match="owner-constructed"):
        CapabilityProviderAdmissionRecord()

    grant = authority.grant_eligibility(
        candidate,
        issued_at=100,
        expires_at=220,
    )
    admission = authority.admit(
        candidate,
        eligibility=grant,
        issued_at=120,
        expires_at=200,
    )

    assert grant.candidate_fingerprint == candidate.fingerprint.digest
    assert admission.candidate is candidate
    assert admission.eligibility_fingerprint == grant.fingerprint
    assert admission.effective_facets == candidate.provider.facets
    assert admission.effective_authorities == tuple(
        sorted(candidate.provider.required_authorities)
    )
    assert admission.owner_policy_revision == "document-owner-1"
    assert authority.snapshot().revocation_epoch == 3
    assert not _contains_callable(admission.to_dict())


def test_owner_rejects_policy_contract_expiry_and_fingerprint_skew(
    published_document_plugin: _PublishedPlugin,
) -> None:
    candidate = _candidate(published_document_plugin)

    with pytest.raises(CapabilityProviderAdmissionError) as disallowed:
        _authority(provider_ids=("org.loushang.other/default",)).grant_eligibility(
            candidate,
            issued_at=100,
            expires_at=200,
        )
    assert disallowed.value.code == "provider_not_allowed_by_owner"

    incompatible = CapabilityDefinition(
        capability_id="document.capability",
        owner_id="document",
        contract_version=2,
        facets=("default",),
        scope="session",
        refresh_boundary="sealed",
        phase="final",
    )
    selection = _selection(published_document_plugin)
    incompatible_candidate = prepare_capability_provider_candidate(
        selection,
        selection.candidates[0],
        definition=incompatible,
    )
    with pytest.raises(CapabilityProviderAdmissionError) as contract:
        _authority().grant_eligibility(
            incompatible_candidate,
            issued_at=100,
            expires_at=200,
        )
    assert contract.value.code == "provider_contract_incompatible"

    grant = _authority().grant_eligibility(
        candidate,
        issued_at=100,
        expires_at=200,
    )
    with pytest.raises(CapabilityProviderAdmissionError) as expired:
        _authority().admit(
            candidate,
            eligibility=grant,
            issued_at=200,
            expires_at=220,
        )
    assert expired.value.code == "provider_eligibility_expired"

    with pytest.raises(CapabilityProviderAdmissionError) as revision:
        _authority(policy_revision="document-owner-2").admit(
            candidate,
            eligibility=grant,
            issued_at=150,
            expires_at=190,
        )
    assert revision.value.code == "provider_owner_policy_stale"


def _candidate(fixture: _PublishedPlugin) -> CapabilityProviderCandidateEnvelope:
    selection = _selection(fixture)
    return prepare_capability_provider_candidate(
        selection,
        selection.candidates[0],
        definition=_definition(),
    )


def _definition() -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id="document.capability",
        owner_id="document",
        contract_version=1,
        facets=("default",),
        scope="session",
        refresh_boundary="sealed",
        phase="final",
    )


def _authority(
    *,
    policy_revision: str = "document-owner-1",
    provider_ids: tuple[str, ...] = ("org.loushang.document/default",),
) -> CapabilityProviderOwnerAuthority:
    return CapabilityProviderOwnerAuthority(
        CapabilityProviderOwnerPolicy(
            capability_id="document.capability",
            owner_id="document",
            policy_revision=policy_revision,
            revocation_epoch=3,
            allowed_provider_ids=provider_ids,
            allowed_source_trust_classes=("host-equivalent-local",),
            authority_ceiling=(),
        )
    )


def _selection(fixture: _PublishedPlugin) -> PluginSelection:
    plugin_id = fixture.package.manifest.name
    contribution_id = fixture.contribution.contribution_id
    plan = PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="coding",
            scope_id="workspace:test",
            policy_revision="policy-1",
            instance_revision_refs=(
                PluginInstanceRevisionRef(
                    instance_id=f"{plugin_id}@product",
                    plugin_id=plugin_id,
                    revision=1,
                ),
            ),
        ),
        selected_plugin_ids=(plugin_id,),
        selected_contributions=(
            PluginContributionRef(plugin_id, contribution_id),
        ),
        source_trust_snapshots=(
            PluginSourceTrustSnapshotV1(
                plugin_id=plugin_id,
                package_source_identity=fixture.binding.source_identity,
                source_trust_class="host-equivalent-local",
                source_trust_policy_revision="trust-1",
                trusted=True,
            ),
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=(
                PluginEffectiveConfigurationEntry(
                    plugin_id=plugin_id,
                    contribution_id=contribution_id,
                    configuration=dict(fixture.contribution.configuration),
                ),
            )
        ),
        allowed_authority_ceiling=fixture.contribution.requested_authorities,
    )
    result = PluginDeclarationHost().resolve(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    assert isinstance(result, PluginSelection)
    return result


def _contains_callable(value: object) -> bool:
    if callable(value):
        return True
    if isinstance(value, dict):
        return any(_contains_callable(item) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_contains_callable(item) for item in value)
    return False
