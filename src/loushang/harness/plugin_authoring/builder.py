"""Internal reservation-bound authoring builder for frozen Plugin IR."""

from __future__ import annotations

from loushang.harness.plugin_authoring.capability_provider import (
    CapabilityProviderDeclarationPayload,
    _validate_capability_provider_reservation,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
    _require_identifier,
    _require_sha256,
)


class PluginDeclarationBuilder:
    """Consume selected reservations exactly once without live host authority."""

    def __init__(
        self,
        *,
        plugin_id: str,
        package_digest: str,
        reservations: tuple[PluginContributionReservation, ...],
    ) -> None:
        _require_identifier(plugin_id, name="Plugin id")
        _require_sha256(package_digest, name="Plugin package digest")
        if any(
            not isinstance(item, PluginContributionReservation) for item in reservations
        ):
            raise TypeError("Plugin declaration reservations have an invalid type")
        reservation_ids = tuple(item.contribution_id for item in reservations)
        if len(reservation_ids) != len(set(reservation_ids)):
            raise ValueError("Plugin declaration reservations contain a duplicate identity")
        self._plugin_id = plugin_id
        self._package_digest = package_digest
        self._reservations = {
            item.contribution_id: item
            for item in sorted(reservations, key=lambda item: item.contribution_id)
        }
        self._declarations: dict[str, PluginDeclaration] = {}
        self._frozen = False

    def add_capability_provider(
        self,
        *,
        contribution_id: str,
        payload: CapabilityProviderDeclarationPayload,
    ) -> PluginDeclaration:
        self._require_open()
        if contribution_id in self._declarations:
            raise ValueError(
                f"Plugin contribution is already declared: {contribution_id}"
            )
        reservation = self._reservations.get(contribution_id)
        if reservation is None:
            raise ValueError(
                f"Plugin contribution references an unknown reservation: {contribution_id}"
            )
        if not isinstance(payload, CapabilityProviderDeclarationPayload):
            raise TypeError("Capability Provider declaration requires a typed payload")
        _validate_capability_provider_reservation(
            payload,
            plugin_id=self._plugin_id,
            package_digest=self._package_digest,
            reservation=reservation,
        )
        declaration = PluginDeclaration(
            plugin_id=self._plugin_id,
            contribution_id=contribution_id,
            kind="capability_provider",
            owner=reservation.owner,
            reservation_fingerprint=reservation.fingerprint,
            payload=payload.to_dict(),
        )
        self._declarations[contribution_id] = declaration
        return declaration

    def build(self) -> tuple[PluginDeclaration, ...]:
        self._require_open()
        unconsumed = tuple(
            contribution_id
            for contribution_id in self._reservations
            if contribution_id not in self._declarations
        )
        if unconsumed:
            raise ValueError(
                "Plugin declaration builder has unconsumed reservations: "
                + ", ".join(unconsumed)
            )
        self._frozen = True
        return tuple(
            self._declarations[contribution_id]
            for contribution_id in sorted(self._declarations)
        )

    def _require_open(self) -> None:
        if self._frozen:
            raise RuntimeError("Plugin declaration builder is frozen")


__all__ = ["PluginDeclarationBuilder"]
