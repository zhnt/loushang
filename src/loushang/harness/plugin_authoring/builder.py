"""Internal reservation-bound authoring builder for frozen Plugin IR."""

from __future__ import annotations

from collections.abc import Mapping

from loushang.harness.plugin_authoring.capability_provider import (
    CapabilityProviderDeclarationPayload,
    _validate_capability_provider_reservation,
)
from loushang.harness.plugin_authoring.consumer_pack import (
    CommandPackDeclarationPayload,
    ToolPackDeclarationPayload,
    _CatalogConsumerDeclarationPayload,
    _validate_catalog_consumer_reservation,
)
from loushang.harness.plugin_authoring.reservations import (
    _authoring_reservation_view,
    _PluginAuthoringReservationView,
)
from loushang.harness.plugin_authoring.resource_item import (
    ResourceItemDeclarationPayload,
    _validate_resource_item_reservation,
)
from loushang.harness.resources.plugins.declarations import PluginDeclaration
from loushang.harness.resources.plugins.selection import (
    PluginDeclarationSourceGroup,
)


class PluginDeclarationBuilder:
    """Consume selected reservations exactly once without live host authority."""

    def __init__(
        self,
        *,
        source_group: PluginDeclarationSourceGroup,
    ) -> None:
        if not isinstance(source_group, PluginDeclarationSourceGroup):
            raise TypeError("Plugin declaration builder requires one SourceGroup")
        reservations = source_group.reservations
        reservation_views = tuple(
            _authoring_reservation_view(source_group, item) for item in reservations
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
        preflight_contexts = {item.preflight_context for item in reservation_views}
        if len(preflight_contexts) != 1:
            raise ValueError(
                "Plugin declaration reservations must share one preflight context"
            )
        reservation_ids = tuple(
            item.contribution.contribution_id for item in reservation_views
        )
        if len(reservation_ids) != len(set(reservation_ids)):
            raise ValueError(
                "Plugin declaration reservations contain a duplicate identity"
            )
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
        self._built_declarations: tuple[PluginDeclaration, ...] | None = None

    @property
    def plugin_id(self) -> str:
        """Return the inert package identity used by the public SDK compiler."""

        return self._plugin_id

    def effective_configuration(
        self,
        *,
        contribution_id: str,
    ) -> Mapping[str, object]:
        """Return one reservation's frozen Product effective configuration."""

        self._require_open()
        reservation_view = self._reservations.get(contribution_id)
        if reservation_view is None:
            raise ValueError(
                "Plugin configuration references an unknown reservation: "
                f"{contribution_id}"
            )
        return reservation_view.effective_configuration

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
            source_descriptor_fingerprint=contribution.source_descriptor_fingerprint,
            source_kind=contribution.declaration_source.kind,
            payload=payload.to_dict(),
        )
        self._declarations[contribution_id] = declaration
        return declaration

    def add_resource_item(
        self,
        *,
        contribution_id: str,
        payload: ResourceItemDeclarationPayload,
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
        if not isinstance(payload, ResourceItemDeclarationPayload):
            raise TypeError("Resource Item declaration requires a typed payload")
        _validate_resource_item_reservation(
            payload,
            reservation=reservation_view,
        )
        contribution = reservation_view.contribution
        declaration = PluginDeclaration(
            plugin_id=self._plugin_id,
            contribution_id=contribution_id,
            kind="resource_item",
            owner=contribution.owner,
            reservation_fingerprint=contribution.fingerprint,
            source_descriptor_fingerprint=contribution.source_descriptor_fingerprint,
            source_kind=contribution.declaration_source.kind,
            payload=payload.to_dict(),
        )
        self._declarations[contribution_id] = declaration
        return declaration

    def add_tool_pack(
        self,
        *,
        contribution_id: str,
        payload: ToolPackDeclarationPayload,
    ) -> PluginDeclaration:
        if not isinstance(payload, ToolPackDeclarationPayload):
            raise TypeError("Tool Pack declaration requires a typed payload")
        return self._add_catalog_consumer(
            contribution_id=contribution_id,
            payload=payload,
        )

    def add_command_pack(
        self,
        *,
        contribution_id: str,
        payload: CommandPackDeclarationPayload,
    ) -> PluginDeclaration:
        if not isinstance(payload, CommandPackDeclarationPayload):
            raise TypeError("Command Pack declaration requires a typed payload")
        return self._add_catalog_consumer(
            contribution_id=contribution_id,
            payload=payload,
        )

    def _add_catalog_consumer(
        self,
        *,
        contribution_id: str,
        payload: _CatalogConsumerDeclarationPayload,
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
        _validate_catalog_consumer_reservation(
            payload,
            reservation=reservation_view,
        )
        contribution = reservation_view.contribution
        declaration = PluginDeclaration(
            plugin_id=self._plugin_id,
            contribution_id=contribution_id,
            kind=payload._CONTRIBUTION_KIND,
            owner=contribution.owner,
            reservation_fingerprint=contribution.fingerprint,
            source_descriptor_fingerprint=contribution.source_descriptor_fingerprint,
            source_kind=contribution.declaration_source.kind,
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
        self._built_declarations = tuple(
            self._declarations[contribution_id]
            for contribution_id in sorted(self._declarations)
        )
        return self._built_declarations

    def _require_open(self) -> None:
        if self._frozen:
            raise RuntimeError("Plugin declaration builder is frozen")

    def _validate_definition_result(
        self,
        value: object,
    ) -> tuple[PluginDeclaration, ...]:
        """Accept only the exact tuple produced by this builder's ``build``."""

        if not self._frozen:
            raise ValueError("Plugin Definition did not freeze its declaration builder")
        declarations = self._built_declarations
        if declarations is None or value is not declarations:
            raise ValueError("Plugin Definition returned foreign declaration IR")
        return declarations


__all__ = ["PluginDeclarationBuilder"]
