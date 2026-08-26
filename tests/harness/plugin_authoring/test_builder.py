"""Reservation-bound Plugin declaration builder contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Protocol

import pytest

from loushang.harness.capabilities import (
    CapabilityBundleProvider,
    CapabilityContractRange,
    CapabilityRequirement,
)
from loushang.harness.plugin_authoring.builder import PluginDeclarationBuilder
from loushang.harness.plugin_authoring.capability_provider import (
    CapabilityProviderDeclarationPayload,
    PluginSymbolReference,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
)
from loushang.harness.resources.plugins.selection import (
    PendingOnlyPluginExecutionDecisionLookup,
    PluginContributionRef,
    PluginDeclarationExecutionPreflightGate,
    PluginDeclarationReservation,
    PluginDeclarationSourceGroup,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginExecutionApprovalSubject,
    PluginExecutionDecisionCurrent,
    PluginExecutionDecisionLookupResult,
    PluginExecutionDecisionRecord,
    PluginInstanceRevisionRef,
    PluginPreflightAcceptedOutcome,
    PluginPreflightContextV1,
    PluginPreflightPendingApprovalOutcome,
    PluginSelectionPlanV2,
    PluginSelectionResolver,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import (
    PluginSourceBinding,
    PublishedPluginPackage,
)


class _PublishedSyntheticPlugin(Protocol):
    package: PublishedPluginPackage
    binding: PluginSourceBinding
    contribution: PluginContributionReservation
    import_marker: Path


class _CurrentDecisionLookup:
    def __init__(self, decision: PluginExecutionDecisionRecord) -> None:
        self._decision = decision

    def lookup_execution_decision(
        self,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginExecutionDecisionLookupResult:
        return PluginExecutionDecisionCurrent(decision=self._decision)


def test_builder_exact_matches_hand_authored_ir_and_freezes(
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    source_group = _preflight_source_group(published_synthetic_plugin)
    reservation = source_group.reservations[0]
    payload = _payload(reservation)
    builder = PluginDeclarationBuilder(
        source_group=source_group,
    )

    declaration = builder.add_capability_provider(
        contribution_id=reservation.contribution.contribution_id,
        payload=payload,
    )
    hand_authored = PluginDeclaration(
        plugin_id=reservation.package.manifest.name,
        contribution_id=reservation.contribution.contribution_id,
        kind="capability_provider",
        owner=reservation.contribution.owner,
        reservation_fingerprint=reservation.contribution.fingerprint,
        source_descriptor_fingerprint=(
            reservation.contribution.source_descriptor_fingerprint
        ),
        source_kind=reservation.contribution.declaration_source.kind,
        payload=payload.to_dict(),
    )

    assert declaration == hand_authored
    assert (
        CapabilityProviderDeclarationPayload.from_reserved_declaration(
            hand_authored,
            source_group=source_group,
        )
        == payload
    )
    built = builder.build()
    assert built == (hand_authored,)
    assert builder._validate_definition_result(built) is built
    with pytest.raises(ValueError, match="foreign declaration IR"):
        builder._validate_definition_result(tuple([*built]))
    with pytest.raises(RuntimeError, match="frozen"):
        builder.build()
    with pytest.raises(RuntimeError, match="frozen"):
        builder.add_capability_provider(
            contribution_id="review-provider",
            payload=payload,
        )


def test_builder_requires_every_reservation_exactly_once(
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    source_group = _preflight_source_group(published_synthetic_plugin)
    reservation = source_group.reservations[0]
    builder = PluginDeclarationBuilder(
        source_group=source_group,
    )

    with pytest.raises(ValueError, match="unconsumed"):
        builder.build()
    builder.add_capability_provider(
        contribution_id=reservation.contribution.contribution_id,
        payload=_payload(reservation),
    )
    with pytest.raises(ValueError, match="already declared"):
        builder.add_capability_provider(
            contribution_id=reservation.contribution.contribution_id,
            payload=_payload(reservation),
        )
    with pytest.raises(ValueError, match="unknown reservation"):
        builder.add_capability_provider(
            contribution_id="missing",
            payload=_payload(reservation),
        )


def test_builder_uses_product_effective_configuration_from_source_group(
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    source_group = _preflight_source_group(
        published_synthetic_plugin,
        effective_configuration={
            "mode": "product",
            "options": {"trace": True},
        },
    )
    reservation = source_group.reservations[0]
    builder = PluginDeclarationBuilder(source_group=source_group)
    configuration = builder.effective_configuration(
        contribution_id=reservation.contribution.contribution_id
    )

    assert configuration == {
        "mode": "product",
        "options": {"trace": True},
    }
    with pytest.raises(TypeError):
        configuration["mode"] = "plugin"  # type: ignore[index]
    options = configuration["options"]
    assert isinstance(options, Mapping)
    with pytest.raises(TypeError):
        options["trace"] = False  # type: ignore[index]
    with pytest.raises(ValueError, match="unknown reservation"):
        builder.effective_configuration(contribution_id="missing")

    declaration = builder.add_capability_provider(
        contribution_id=reservation.contribution.contribution_id,
        payload=_payload(reservation, binding_inputs=configuration),
    )

    assert declaration.to_dict()["payload"]["bindingInputs"] == {
        "mode": "product",
        "options": {"trace": True},
    }
    builder.build()
    with pytest.raises(RuntimeError, match="frozen"):
        builder.effective_configuration(
            contribution_id=reservation.contribution.contribution_id
        )
    with pytest.raises(ValueError, match="binding inputs"):
        PluginDeclarationBuilder(source_group=source_group).add_capability_provider(
            contribution_id=reservation.contribution.contribution_id,
            payload=_payload(reservation),
        )


@pytest.mark.parametrize(
    ("payload_change", "message"),
    [
        (
            lambda payload: replace(
                payload,
                provider=replace(payload.provider, capability_id="coding.arch"),
            ),
            "owner",
        ),
        (
            lambda payload: replace(
                payload,
                provider=replace(
                    payload.provider,
                    required_authorities=frozenset({"filesystem"}),
                ),
            ),
            "authorities",
        ),
        (
            lambda payload: replace(
                payload,
                provider=replace(payload.provider, source_id="forged"),
            ),
            "source id",
        ),
        (
            lambda payload: replace(
                payload,
                provider=replace(payload.provider, selection_rule="forged"),
            ),
            "selection rule",
        ),
        (
            lambda payload: replace(
                payload,
                binding_inputs={"mode": "changed"},
            ),
            "binding inputs",
        ),
    ],
)
def test_builder_rejects_reservation_or_provenance_mismatch(
    payload_change: object,
    message: str,
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    source_group = _preflight_source_group(published_synthetic_plugin)
    reservation = source_group.reservations[0]
    assert callable(payload_change)
    payload = payload_change(_payload(reservation))
    builder = PluginDeclarationBuilder(
        source_group=source_group,
    )

    with pytest.raises(ValueError, match=message):
        builder.add_capability_provider(
            contribution_id=reservation.contribution.contribution_id,
            payload=payload,
        )


def test_builder_rejects_duplicate_reservation_identity(
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    source_group = _preflight_source_group(published_synthetic_plugin)
    contribution = source_group.reservation_closure[0]

    with pytest.raises(ValueError, match="unique"):
        replace(
            source_group,
            reservation_closure=(contribution, contribution),
        )


def test_source_group_rejects_preflight_context_drift(
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    source_group = _preflight_source_group(published_synthetic_plugin)
    another_context = replace(
        source_group.context,
        scope_id="workspace:another",
    )

    with pytest.raises(ValueError, match="fingerprint"):
        replace(source_group, context=another_context)


def test_subject_rejects_inconsistent_ambient_host_authority(
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    source_group = _preflight_source_group(published_synthetic_plugin)
    gate = source_group.gate
    assert isinstance(gate, PluginDeclarationExecutionPreflightGate)

    with pytest.raises(ValueError, match="ambient host authority"):
        replace(
            gate.subject,
            ambient_host_authority=False,
        )


def test_builder_rejects_mixed_package_and_approval_facts(
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    source_group = _preflight_source_group(published_synthetic_plugin)
    gate = source_group.gate
    assert isinstance(gate, PluginDeclarationExecutionPreflightGate)
    forged_subject = replace(
        gate.subject,
        package_content_digest="0" * 64,
    )
    forged_gate = PluginDeclarationExecutionPreflightGate(
        subject=forged_subject,
        decision=replace(gate.decision, subject_digest=forged_subject.digest),
    )

    with pytest.raises(ValueError, match="proposed facts"):
        replace(source_group, gate=forged_gate)


def test_reserved_decode_rejects_declaration_from_another_plugin(
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    source_group = _preflight_source_group(published_synthetic_plugin)
    reservation = source_group.reservations[0]
    payload = _payload(reservation)
    forged_payload = replace(
        payload,
        provider=replace(payload.provider, source_id="plugin:forged-plugin"),
    )
    declaration = PluginDeclaration(
        plugin_id="forged-plugin",
        contribution_id=reservation.contribution.contribution_id,
        kind="capability_provider",
        owner=reservation.contribution.owner,
        reservation_fingerprint=reservation.contribution.fingerprint,
        source_descriptor_fingerprint=(
            reservation.contribution.source_descriptor_fingerprint
        ),
        source_kind=reservation.contribution.declaration_source.kind,
        payload=forged_payload.to_dict(),
    )

    with pytest.raises(ValueError, match="package identity"):
        CapabilityProviderDeclarationPayload.from_reserved_declaration(
            declaration,
            source_group=source_group,
        )


def _payload(
    reservation: PluginDeclarationReservation,
    *,
    binding_inputs: dict[str, object] | None = None,
) -> CapabilityProviderDeclarationPayload:
    contribution = reservation.contribution
    plugin_id = reservation.package.manifest.name
    provider = CapabilityBundleProvider(
        capability_id=contribution.owner,
        provider_id="org.loushang.coding-lsp/default",
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(1),
        facets=("diagnostics", "semantic", "tools"),
        requirements=(
            CapabilityRequirement(
                capability="harness.workspace",
                facets=("process.launch", "read"),
                compatible_contract=CapabilityContractRange.exact(1),
            ),
        ),
        required_authorities=frozenset(contribution.requested_authorities),
        source_id=f"plugin:{plugin_id}",
        selection_rule="Plugin declaration candidate",
    )
    return CapabilityProviderDeclarationPayload(
        provider=provider,
        factory=PluginSymbolReference(
            path="provider.py",
            symbol="create_provider",
            execution_model="in_process",
        ),
        disposer=PluginSymbolReference(
            path="provider.py",
            symbol="dispose_provider",
            execution_model="in_process",
        ),
        binding_inputs=(
            dict(contribution.configuration)
            if binding_inputs is None
            else binding_inputs
        ),
    )


def _preflight_source_group(
    fixture: _PublishedSyntheticPlugin,
    *,
    effective_configuration: dict[str, object] | None = None,
) -> PluginDeclarationSourceGroup:
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
        selected_contributions=(PluginContributionRef(plugin_id, contribution_id),),
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
                    configuration=(
                        dict(fixture.contribution.configuration)
                        if effective_configuration is None
                        else effective_configuration
                    ),
                ),
            )
        ),
        allowed_authority_ceiling=fixture.contribution.requested_authorities,
    )
    resolver = PluginSelectionResolver()
    pending = resolver.preflight(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    assert isinstance(pending, PluginPreflightPendingApprovalOutcome)
    [subject] = pending.subjects
    outcome = resolver.preflight(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decision_lookup=_CurrentDecisionLookup(
            PluginExecutionDecisionRecord(
                decision_id="decision-1",
                subject_digest=subject.digest,
                policy_revision=plan.context.policy_revision,
                disposition="approved",
            )
        ),
    )
    assert isinstance(outcome, PluginPreflightAcceptedOutcome)
    return outcome.accepted.source_groups[0]
