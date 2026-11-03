"""Sanitized, read-only explanation of observed Plugin management facts.

This projection is one input to the eventual cross-owner explanation. It does
not turn Desired State into a claim about Product selection or model use.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from loushang.harness.plugin_management.application import (
    PluginManagementConvergence,
    PluginManagementOwnerRevisionsV1,
    PluginManagementProjectionV1,
    PluginManagementQueryPort,
    PluginManagementQueryV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1

PLUGIN_MANAGEMENT_EXPLANATION_VERSION = 1
_OTHER_OWNER_EVIDENCE = (
    "capability_graph",
    "product_selection",
    "resource_catalog",
    "session_capture",
)


@dataclass(frozen=True, slots=True)
class PluginManagementInstallationExplanationV1:
    """Management owner's observed facts with explicit absent owner evidence."""

    correlation_id: str
    installation_key: PluginInstallationKeyV1
    observed_at_unix_ns: int
    owner_revisions: PluginManagementOwnerRevisionsV1
    management_status: Literal["observed", "unknown"]
    desired_state: str | None
    convergence: PluginManagementConvergence | None
    selected_plugin_version: str | None
    selected_package_content_digest: str | None
    operation_ids: tuple[str, ...]
    skew_codes: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    snapshot_status: Literal["partial_evidence"] = "partial_evidence"
    explanation_version: int = PLUGIN_MANAGEMENT_EXPLANATION_VERSION

    def __post_init__(self) -> None:
        if not self.correlation_id:
            raise ValueError("Plugin explanation correlation id is required")
        if type(self.observed_at_unix_ns) is not int or self.observed_at_unix_ns < 0:
            raise ValueError("Plugin explanation observation time is invalid")
        for values, name in (
            (self.operation_ids, "operation ids"),
            (self.skew_codes, "skew codes"),
            (self.evidence_gaps, "evidence gaps"),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"Plugin explanation {name} must be sorted and unique")
        if self.management_status == "unknown" and any(
            value is not None
            for value in (
                self.desired_state,
                self.convergence,
                self.selected_plugin_version,
                self.selected_package_content_digest,
            )
        ):
            raise ValueError("Unknown management status cannot assert owner facts")
        if self.snapshot_status != "partial_evidence":
            raise ValueError("Management-only explanation is partial evidence")
        if self.explanation_version != PLUGIN_MANAGEMENT_EXPLANATION_VERSION:
            raise ValueError("Unsupported Plugin management explanation")

    def to_dict(self) -> dict[str, object]:
        """Exclude Source paths, private configuration and Resource bodies."""

        return {
            "correlationId": self.correlation_id,
            "installationKey": self.installation_key.to_dict(),
            "observedAtUnixNs": self.observed_at_unix_ns,
            "ownerRevisions": self.owner_revisions.to_dict(),
            "managementStatus": self.management_status,
            "desiredState": self.desired_state,
            "managementConvergence": self.convergence,
            "selectedPluginVersion": self.selected_plugin_version,
            "selectedPackageContentDigest": self.selected_package_content_digest,
            "operationIds": list(self.operation_ids),
            "skewCodes": list(self.skew_codes),
            "evidenceGaps": list(self.evidence_gaps),
            "snapshotStatus": self.snapshot_status,
            "explanationVersion": self.explanation_version,
        }


class PluginManagementExplanationProjector:
    """Query the management read port once without asking any owner to write."""

    def __init__(
        self,
        queries: PluginManagementQueryPort,
        *,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        if not callable(getattr(queries, "snapshot", None)):
            raise TypeError("Plugin management query port is required")
        if not callable(clock_ns):
            raise TypeError("Plugin explanation clock is required")
        self._queries = queries
        self._clock_ns = clock_ns

    def explain_installation(
        self,
        installation_key: PluginInstallationKeyV1,
        *,
        correlation_id: str,
    ) -> PluginManagementInstallationExplanationV1:
        if not isinstance(installation_key, PluginInstallationKeyV1):
            raise TypeError("Plugin installation key is required")
        query = PluginManagementQueryV1(
            correlation_id=correlation_id,
            product_id=installation_key.product_id,
            installation_scope=installation_key.installation_scope,
            scope_id=installation_key.scope_id,
            plugin_ids=(installation_key.plugin_id,),
        )
        projection = self._queries.snapshot(query)
        if not isinstance(projection, PluginManagementProjectionV1):
            raise TypeError("Plugin management projection is required")
        if projection.correlation_id != correlation_id:
            raise ValueError("Plugin management projection changed correlation id")
        views = tuple(
            item for item in projection.installations
            if item.installation_key == installation_key
        )
        if len(views) > 1:
            raise ValueError("Plugin management projection repeats Installation")
        view = views[0] if views else None
        revision = None if view is None else view.selected_package_revision
        gaps = set(_OTHER_OWNER_EVIDENCE)
        gaps.update(projection.owner_revisions.unsupported_dimensions)
        if view is None:
            gaps.add("management_installation")
        else:
            gaps.update(view.unknown_dimensions)
        return PluginManagementInstallationExplanationV1(
            correlation_id=correlation_id,
            installation_key=installation_key,
            observed_at_unix_ns=self._clock_ns(),
            owner_revisions=projection.owner_revisions,
            management_status="unknown" if view is None else "observed",
            desired_state=None if view is None else view.desired_state,
            convergence=None if view is None else view.convergence,
            selected_plugin_version=None if revision is None else revision.plugin_version,
            selected_package_content_digest=(
                None if revision is None else revision.package_content_digest
            ),
            operation_ids=(
                () if view is None else tuple(item.operation_id for item in view.operations)
            ),
            skew_codes=tuple(
                sorted(
                    {item.code for item in projection.skew if item.installation_key == installation_key}
                )
            ),
            evidence_gaps=tuple(sorted(gaps)),
        )


__all__ = [
    "PLUGIN_MANAGEMENT_EXPLANATION_VERSION",
    "PluginManagementExplanationProjector",
    "PluginManagementInstallationExplanationV1",
]
