"""Reservation-bound Plugin declaration builder contracts."""

from __future__ import annotations

from dataclasses import replace

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


def test_builder_exact_matches_hand_authored_ir_and_freezes() -> None:
    reservation = _reservation()
    payload = _payload(reservation)
    builder = PluginDeclarationBuilder(
        plugin_id="review-pack",
        package_digest="a" * 64,
        reservations=(reservation,),
    )

    declaration = builder.add_capability_provider(
        contribution_id="review-provider",
        payload=payload,
    )
    hand_authored = PluginDeclaration(
        plugin_id="review-pack",
        contribution_id="review-provider",
        kind="capability_provider",
        owner="coding.lsp",
        reservation_fingerprint=reservation.fingerprint,
        payload=payload.to_dict(),
    )

    assert declaration == hand_authored
    assert (
        CapabilityProviderDeclarationPayload.from_reserved_declaration(
            hand_authored,
            package_digest="a" * 64,
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


def test_builder_requires_every_reservation_exactly_once() -> None:
    first = _reservation()
    second = replace(first, contribution_id="alternate-provider", required=False)
    builder = PluginDeclarationBuilder(
        plugin_id="review-pack",
        package_digest="a" * 64,
        reservations=(first, second),
    )
    builder.add_capability_provider(
        contribution_id=first.contribution_id,
        payload=_payload(first),
    )

    with pytest.raises(ValueError, match="unconsumed"):
        builder.build()
    with pytest.raises(ValueError, match="already declared"):
        builder.add_capability_provider(
            contribution_id=first.contribution_id,
            payload=_payload(first),
        )
    with pytest.raises(ValueError, match="unknown reservation"):
        builder.add_capability_provider(
            contribution_id="missing",
            payload=_payload(first),
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
) -> None:
    reservation = _reservation()
    assert callable(payload_change)
    payload = payload_change(_payload(reservation))
    builder = PluginDeclarationBuilder(
        plugin_id="review-pack",
        package_digest="a" * 64,
        reservations=(reservation,),
    )

    with pytest.raises(ValueError, match=message):
        builder.add_capability_provider(
            contribution_id=reservation.contribution_id,
            payload=payload,
        )


def test_builder_rejects_duplicate_reservation_identity() -> None:
    reservation = _reservation()

    with pytest.raises(ValueError, match="duplicate"):
        PluginDeclarationBuilder(
            plugin_id="review-pack",
            package_digest="a" * 64,
            reservations=(reservation, reservation),
        )


def _reservation() -> PluginContributionReservation:
    return PluginContributionReservation(
        contribution_id="review-provider",
        kind="capability_provider",
        owner="coding.lsp",
        entrypoint="definition.py:declare",
        execution_model="in_process",
        requested_authorities=("process",),
        configuration={"mode": "review"},
    )


def _payload(
    reservation: PluginContributionReservation,
) -> CapabilityProviderDeclarationPayload:
    provider = CapabilityBundleProvider(
        capability_id="coding.lsp",
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
        required_authorities=frozenset({"process"}),
        source_id="plugin:review-pack",
        selection_rule="Plugin declaration candidate",
    )
    return CapabilityProviderDeclarationPayload(
        provider=provider,
        factory=PluginSymbolReference(
            path="provider.py",
            symbol="create_provider",
            package_digest="a" * 64,
            execution_model="in_process",
        ),
        disposer=PluginSymbolReference(
            path="provider.py",
            symbol="dispose_provider",
            package_digest="a" * 64,
            execution_model="in_process",
        ),
        binding_inputs={"mode": "review"},
        configuration_fingerprint=reservation.configuration_fingerprint,
    )
