"""Narrow authoring views derived from exact Plugin preflight facts."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
)
from loushang.harness.resources.plugins.selection import (
    PluginDeclarationReservation,
    PluginExecutionApprovalSubject,
)
from loushang.harness.resources.plugins.types import PublishedPluginPackage


@dataclass(frozen=True, slots=True)
class _PluginAuthoringReservationView:
    """Package-bound facts safe to retain inside the declaration Builder."""

    plugin_id: str
    package_digest: str
    dependency_lock_digest: str
    contribution: PluginContributionReservation
    approval_subject_digest: str
    decision_id: str


def _authoring_reservation_view(
    value: PluginDeclarationReservation,
) -> _PluginAuthoringReservationView:
    if not isinstance(value, PluginDeclarationReservation):
        raise TypeError(
            "Plugin authoring requires an exact preflight declaration reservation"
        )
    package = value.package
    contribution = value.contribution
    subject = value.approval_subject
    if not isinstance(package, PublishedPluginPackage):
        raise TypeError("Plugin authoring reservation requires a published package")
    if not isinstance(contribution, PluginContributionReservation):
        raise TypeError("Plugin authoring reservation has an invalid contribution")
    if not isinstance(subject, PluginExecutionApprovalSubject):
        raise TypeError("Plugin authoring reservation has an invalid approval subject")
    if contribution not in package.contribution_index.items:
        raise ValueError(
            "Plugin authoring reservation contribution does not belong to its package"
        )
    plugin_id = package.manifest.name
    package_digest = package.content_digest
    dependency_lock_digest = package.dependency_lock.digest
    if (
        subject.plugin_id != plugin_id
        or subject.package_content_digest != package_digest
        or subject.dependency_lock_digest != dependency_lock_digest
        or subject.contribution_id != contribution.contribution_id
        or subject.reservation_fingerprint != contribution.fingerprint
        or subject.execution_model != contribution.execution_model
        or subject.entrypoint != contribution.entrypoint
        or subject.configuration_fingerprint
        != contribution.configuration_fingerprint
        or subject.requested_authorities != contribution.requested_authorities
    ):
        raise ValueError(
            "Plugin authoring reservation does not match its package and approval facts"
        )
    if (
        not isinstance(value.decision_id, str)
        or not value.decision_id
        or value.decision_id != value.decision_id.strip()
    ):
        raise ValueError("Plugin authoring reservation decision id must be non-empty")
    return _PluginAuthoringReservationView(
        plugin_id=plugin_id,
        package_digest=package_digest,
        dependency_lock_digest=dependency_lock_digest,
        contribution=contribution,
        approval_subject_digest=subject.digest,
        decision_id=value.decision_id,
    )


__all__: list[str] = []
