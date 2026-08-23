"""Host-owned entry for inert Plugin declaration composition."""

from __future__ import annotations

from loushang.harness.plugin_authoring.coordinator import (
    PluginDeclarationCoordinator,
)
from loushang.harness.resources.plugins.selection import (
    PluginExecutionDecisionLookupPort,
    PluginPreflightAcceptedOutcome,
    PluginPreflightDeniedOutcome,
    PluginPreflightPendingApprovalOutcome,
    PluginPreflightRejectedOutcome,
    PluginSelection,
    PluginSelectionPlanV2,
    PluginSelectionResolver,
)
from loushang.harness.resources.plugins.types import (
    PluginSourceBinding,
    PublishedPluginPackage,
)

PluginDeclarationHostResult = (
    PluginSelection
    | PluginPreflightPendingApprovalOutcome
    | PluginPreflightDeniedOutcome
    | PluginPreflightRejectedOutcome
)


class PluginDeclarationHost:
    """Own one Resolver/Coordinator pair for the current Host boot.

    The Host returns proposed approval subjects without recording decisions. An
    accepted preflight is handed directly to the sole declaration Coordinator,
    so its active token never becomes a Product-facing continuation handle.
    """

    __slots__ = ("_coordinator", "_resolver")

    def __init__(self) -> None:
        self._resolver = PluginSelectionResolver()
        self._coordinator = PluginDeclarationCoordinator(self._resolver)

    def resolve(
        self,
        packages: tuple[PublishedPluginPackage, ...],
        *,
        bindings: tuple[PluginSourceBinding, ...],
        plan: PluginSelectionPlanV2,
        decision_lookup: PluginExecutionDecisionLookupPort,
    ) -> PluginDeclarationHostResult:
        """Revalidate one authoritative Plan and compose accepted declarations."""

        outcome = self._resolver.preflight(
            packages,
            bindings=bindings,
            plan=plan,
            decision_lookup=decision_lookup,
        )
        if isinstance(outcome, PluginPreflightAcceptedOutcome):
            return self._coordinator.finalize(outcome.accepted)
        return outcome


__all__ = ["PluginDeclarationHost", "PluginDeclarationHostResult"]
