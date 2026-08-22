"""Internal reservation-bound authoring builder for frozen Plugin IR."""

from __future__ import annotations

from loushang.harness.plugin_authoring.capability_provider import (
    CapabilityProviderDeclarationPayload,
    _validate_capability_provider_reservation,
)
from loushang.harness.plugin_authoring.reservations import (
    _authoring_reservation_view,
    _PluginAuthoringReservationView,
)
from loushang.harness.resources.plugins.declarations import PluginDeclaration
from loushang.harness.resources.plugins.selection import (
    PluginDeclarationReservation,
)


class PluginDeclarationBuilder:
    """Consume selected reservations exactly once without live host authority."""

    def __init__(
        self,
        *,
        reservations: tuple[PluginDeclarationReservation, ...],
    ) -> None:
        reservation_views = tuple(
            _authoring_reservation_view(item) for item in reservations
        )
        if not reservation_views:
            raise ValueError("Plugin declaration builder requires reservations")
        revision_identities = {
            (
                item.plugin_id,
                item.package_digest,
                item.dependency_lock_digest,
            )
            for item in reservation_views
        }
        if len(revision_identities) != 1:
            raise ValueError(
                "Plugin declaration reservations must share one package revision"
            )
        reservation_ids = tuple(
            item.contribution.contribution_id for item in reservation_views
        )
        if len(reservation_ids) != len(set(reservation_ids)):
            raise ValueError("Plugin declaration reservations contain a duplicate identity")
        self._plugin_id = reservation_views[0].plugin_id
        self._reservations: dict[str, _PluginAuthoringReservationView] = {
            item.contribution.contribution_id: item
            for item in sorted(
                reservation_views,
                key=lambda item: item.contribution.contribution_id,
            )
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
        reservation_view = self._reservations.get(contribution_id)
        if reservation_view is None:
            raise ValueError(
                f"Plugin contribution references an unknown reservation: {contribution_id}"
            )
        if not isinstance(payload, CapabilityProviderDeclarationPayload):
            raise TypeError("Capability Provider declaration requires a typed payload")
        _validate_capability_provider_reservation(
            payload,
            reservation=reservation_view,
        )
        contribution = reservation_view.contribution
        declaration = PluginDeclaration(
            plugin_id=self._plugin_id,
            contribution_id=contribution_id,
            kind="capability_provider",
            owner=contribution.owner,
            reservation_fingerprint=contribution.fingerprint,
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
