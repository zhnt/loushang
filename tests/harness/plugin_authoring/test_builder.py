"""Reservation-bound Plugin declaration builder contracts."""

from __future__ import annotations

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
    PluginContributionRef,
    PluginDeclarationReservation,
    PluginExecutionDecisionRecord,
    PluginSelectionPlan,
    PluginSelectionResolver,
    PluginSourceTrust,
    build_execution_approval_subject,
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


def test_builder_exact_matches_hand_authored_ir_and_freezes(
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    reservation = _preflight_reservation(published_synthetic_plugin)
    payload = _payload(reservation)
    builder = PluginDeclarationBuilder(
        reservations=(reservation,),
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
        payload=payload.to_dict(),
    )

    assert declaration == hand_authored
    assert (
        CapabilityProviderDeclarationPayload.from_reserved_declaration(
            hand_authored,
            reservation=reservation,
        )
        == payload
    )
    assert builder.build() == (hand_authored,)
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
    reservation = _preflight_reservation(published_synthetic_plugin)
    builder = PluginDeclarationBuilder(
        reservations=(reservation,),
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
                configuration_fingerprint="c" * 64,
            ),
            "configuration fingerprint",
        ),
        (
            lambda payload: replace(
                payload,
                factory=replace(payload.factory, package_digest="c" * 64),
                disposer=replace(payload.disposer, package_digest="c" * 64),
            ),
            "package digest",
        ),
    ],
)
def test_builder_rejects_reservation_or_provenance_mismatch(
    payload_change: object,
    message: str,
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    reservation = _preflight_reservation(published_synthetic_plugin)
    assert callable(payload_change)
    payload = payload_change(_payload(reservation))
    builder = PluginDeclarationBuilder(
        reservations=(reservation,),
    )

    with pytest.raises(ValueError, match=message):
        builder.add_capability_provider(
            contribution_id=reservation.contribution.contribution_id,
            payload=payload,
        )


def test_builder_rejects_duplicate_reservation_identity(
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    reservation = _preflight_reservation(published_synthetic_plugin)

    with pytest.raises(ValueError, match="duplicate"):
        PluginDeclarationBuilder(
            reservations=(reservation, reservation),
        )


def test_builder_rejects_reservations_from_mixed_preflight_contexts(
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    reservation = _preflight_reservation(published_synthetic_plugin)
    another_scope = replace(
        reservation,
        approval_subject=replace(
            reservation.approval_subject,
            scope_id="workspace:another",
        ),
        decision_id="decision-another-scope",
    )

    with pytest.raises(ValueError, match="preflight context"):
        PluginDeclarationBuilder(
            reservations=(reservation, another_scope),
        )


def test_builder_rejects_inconsistent_ambient_host_authority(
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    reservation = _preflight_reservation(published_synthetic_plugin)
    forged = replace(
        reservation,
        approval_subject=replace(
            reservation.approval_subject,
            ambient_host_authority=False,
        ),
    )

    with pytest.raises(ValueError, match="package and approval facts"):
        PluginDeclarationBuilder(reservations=(forged,))


def test_builder_rejects_mixed_package_and_approval_facts(
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    reservation = _preflight_reservation(published_synthetic_plugin)
    forged = replace(
        reservation,
        approval_subject=replace(
            reservation.approval_subject,
            package_content_digest="0" * 64,
        ),
    )

    with pytest.raises(ValueError, match="package and approval facts"):
        PluginDeclarationBuilder(reservations=(forged,))


def test_reserved_decode_rejects_declaration_from_another_plugin(
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    reservation = _preflight_reservation(published_synthetic_plugin)
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
        payload=forged_payload.to_dict(),
    )

    with pytest.raises(ValueError, match="package identity"):
        CapabilityProviderDeclarationPayload.from_reserved_declaration(
            declaration,
            reservation=reservation,
        )


def _payload(
    reservation: PluginDeclarationReservation,
) -> CapabilityProviderDeclarationPayload:
    contribution = reservation.contribution
    plugin_id = reservation.package.manifest.name
    package_digest = reservation.package.content_digest
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
            package_digest=package_digest,
            execution_model="in_process",
        ),
        disposer=PluginSymbolReference(
            path="provider.py",
            symbol="dispose_provider",
            package_digest=package_digest,
            execution_model="in_process",
        ),
        binding_inputs=dict(contribution.configuration),
        configuration_fingerprint=contribution.configuration_fingerprint,
    )


def _preflight_reservation(
    fixture: _PublishedSyntheticPlugin,
) -> PluginDeclarationReservation:
    plugin_id = fixture.package.manifest.name
    contribution_id = fixture.contribution.contribution_id
    plan = PluginSelectionPlan(
        product_id="coding",
        scope_id="workspace:test",
        policy_revision="policy-1",
        selected_plugin_ids=(plugin_id,),
        selected_contributions=(PluginContributionRef(plugin_id, contribution_id),),
        source_trust=(
            PluginSourceTrust(
                plugin_id=plugin_id,
                source_identity=fixture.binding.source_identity,
                trust_class="host-equivalent-local",
                trusted=True,
            ),
        ),
        allowed_authorities=fixture.contribution.requested_authorities,
    )
    subject = build_execution_approval_subject(
        fixture.package,
        fixture.contribution,
        plan=plan,
        source_trust=plan.source_trust[0],
        binding=fixture.binding,
    )
    preflight = PluginSelectionResolver().preflight(
        (fixture.package,),
        bindings=(fixture.binding,),
        plan=plan,
        decisions=(
            PluginExecutionDecisionRecord(
                decision_id="decision-1",
                subject_digest=subject.digest,
                policy_revision=plan.policy_revision,
                disposition="approved",
            ),
        ),
    )
    return preflight.reservations[0]
