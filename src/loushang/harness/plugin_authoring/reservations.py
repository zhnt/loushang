"""Narrow authoring views derived from exact Plugin preflight facts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
)
from loushang.harness.resources.plugins.selection import (
    PluginDeclarationExecutionPreflightGate,
    PluginDeclarationReservation,
    PluginDeclarationSourceGroup,
    PluginExecutionApprovalSubject,
)
from loushang.harness.resources.plugins.types import PublishedPluginPackage


@dataclass(frozen=True, slots=True)
class _PluginAuthoringPreflightContext:
    """Common approval context shared by one Definition evaluation."""

    source_identity: str
    source_trust_class: str
    product_id: str
    scope_id: str
    policy_revision: str
    ambient_host_authority: bool


@dataclass(frozen=True, slots=True)
class _PluginAuthoringReservationView:
    """Package-bound facts safe to retain inside the declaration Builder."""

    plugin_id: str
    package_digest: str
    dependency_lock_digest: str
    preflight_context: _PluginAuthoringPreflightContext
    contribution: PluginContributionReservation
    effective_configuration: Mapping[str, object]
    approval_subject_digest: str
    decision_id: str


def _authoring_reservation_view(
    source_group: PluginDeclarationSourceGroup,
    value: PluginDeclarationReservation,
) -> _PluginAuthoringReservationView:
    if not isinstance(source_group, PluginDeclarationSourceGroup):
        raise TypeError("Plugin authoring requires an exact declaration SourceGroup")
    if not isinstance(value, PluginDeclarationReservation):
        raise TypeError(
            "Plugin authoring requires an exact preflight declaration reservation"
        )
    if (
        value.source_group_id != source_group.source_group_id
        or value.source_group_fingerprint != source_group.source_group_fingerprint
    ):
        raise ValueError("Plugin authoring reservation does not belong to its SourceGroup")
    package = value.package
    contribution = value.contribution
    gate = source_group.gate
    if not isinstance(gate, PluginDeclarationExecutionPreflightGate):
        raise ValueError("Plugin declaration Builder requires an executable SourceGroup")
    subject = gate.subject
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
        package is not source_group.package
        or contribution not in source_group.reservation_closure
        or subject.plugin_id != plugin_id
        or subject.package_content_digest != package_digest
        or subject.dependency_lock_digest != dependency_lock_digest
        or not subject.ambient_host_authority
        or subject.entrypoint != contribution.declaration_source.entrypoint
        or subject.source_descriptor_fingerprint
        != contribution.source_descriptor_fingerprint
        or subject.configuration_map_fingerprint
        != source_group.configuration_map_fingerprint
        or subject.reservation_closure_fingerprint
        != source_group.reservation_closure_fingerprint
        or subject.requested_authorities != source_group.requested_authorities
        or subject.allowed_authority_ceiling
        != source_group.allowed_authority_ceiling
        or subject.instance_revision_ref != source_group.instance_revision_ref
    ):
        raise ValueError(
            "Plugin authoring reservation does not match its package and approval facts"
        )
    effective_by_id = {
        item.contribution_id: item.configuration
        for item in source_group.effective_configuration_entries
    }
    return _PluginAuthoringReservationView(
        plugin_id=plugin_id,
        package_digest=package_digest,
        dependency_lock_digest=dependency_lock_digest,
        preflight_context=_PluginAuthoringPreflightContext(
            source_identity=subject.package_source_identity,
            source_trust_class=subject.source_trust_class,
            product_id=subject.product_id,
            scope_id=subject.scope_id,
            policy_revision=subject.policy_revision,
            ambient_host_authority=subject.ambient_host_authority,
        ),
        contribution=contribution,
        effective_configuration=effective_by_id[contribution.contribution_id],
        approval_subject_digest=subject.digest,
        decision_id=gate.decision.decision_id,
    )


__all__: list[str] = []
