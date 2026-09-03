"""PLC9A2 adapters from Package handoff records to Plugin management owners."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loushang.harness.plugin_management.operations import (
    PluginManagementCommandV1,
    PluginManagementOperationEventV1,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginInstallationScope,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageDesiredStateCommitRequestV1,
    PackageDesiredStateCommitResultV1,
)

PACKAGE_PRODUCT_DESIRED_ADAPTER_VERSION = 1


class PluginManagementCommandSubmitPort(Protocol):
    """Narrow command surface retained by the Package desired adapter."""

    def submit(
        self,
        command: PluginManagementCommandV1,
    ) -> PluginManagementOperationEventV1: ...


class PackageProductDesiredRevisionProjectionPort(Protocol):
    """Resolve owner evidence omitted from the capability-poor handoff record."""

    def project(
        self,
        request: PackageDesiredStateCommitRequestV1,
    ) -> PluginPackageRevisionRefV1: ...

    def inventory_revision(self) -> int: ...


@dataclass(frozen=True, slots=True)
class PluginManagementPackageDesiredStateAdapter:
    """Commit an admitted PLC9B root through the sole management service."""

    management: PluginManagementCommandSubmitPort
    revisions: PackageProductDesiredRevisionProjectionPort
    installation_scope: PluginInstallationScope
    actor_id: str
    policy_revision: str
    approval_reference: str | None = None
    owner_identity: str = "plugin-management-service"
    adapter_version: int = PACKAGE_PRODUCT_DESIRED_ADAPTER_VERSION

    def __post_init__(self) -> None:
        if not callable(getattr(self.management, "submit", None)):
            raise TypeError("Plugin management command owner is required")
        if not all(
            callable(getattr(self.revisions, method, None))
            for method in ("project", "inventory_revision")
        ):
            raise TypeError("Package desired revision projector is required")
        if self.installation_scope not in {"process", "tenant", "workspace"}:
            raise ValueError("Unsupported Package Product installation scope")
        for value, name in (
            (self.actor_id, "Package Product actor id"),
            (self.policy_revision, "Package Product policy revision"),
            (self.owner_identity, "Package Product desired owner identity"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        if self.adapter_version != PACKAGE_PRODUCT_DESIRED_ADAPTER_VERSION:
            raise ValueError("Unsupported Package Product desired adapter")

    def commit(
        self,
        request: PackageDesiredStateCommitRequestV1,
    ) -> PackageDesiredStateCommitResultV1:
        if not isinstance(request, PackageDesiredStateCommitRequestV1):
            raise TypeError("Package desired-state commit request is required")
        package_revision = self.revisions.project(request)
        if not isinstance(package_revision, PluginPackageRevisionRefV1):
            raise TypeError(
                "Package desired revision projector returned invalid evidence"
            )
        if (
            package_revision.plugin_id != request.plugin_id
            or package_revision.plugin_version != request.root_ref.version
            or package_revision.package_content_digest
            != request.root_ref.artifact_digest
        ):
            raise ValueError("Package desired revision evidence changed")
        command = PluginManagementCommandV1(
            action="install",
            mutation=PluginDesiredStateMutationV1(
                operation_id=request.command_id,
                idempotency_key=request.desired_request_id,
                expected_inventory_revision=request.expected_inventory_revision,
                installation_key=PluginInstallationKeyV1(
                    product_id=request.product_id,
                    installation_scope=self.installation_scope,
                    scope_id=request.scope_id,
                    plugin_id=request.plugin_id,
                ),
                desired_state="installed_disabled",
                package_revision=package_revision,
                actor_id=self.actor_id,
                policy_revision=self.policy_revision,
                approval_reference=self.approval_reference,
            ),
        )
        event = self.management.submit(command)
        if not isinstance(event, PluginManagementOperationEventV1):
            raise TypeError("Plugin management owner returned an invalid operation")
        if event.status != "terminal" or event.result is None:
            raise RuntimeError("Plugin management desired operation is not terminal")
        if event.result.disposition == "succeeded":
            transition = event.result.transition
            if (
                transition is None
                or transition.inventory_revision
                != request.expected_inventory_revision + 1
            ):
                raise RuntimeError("Plugin management desired receipt changed")
            return PackageDesiredStateCommitResultV1.committed(
                request,
                owner_identity=self.owner_identity,
                owner_revision=event.journal_revision,
            )
        if event.result.error_code == "plugin_inventory_revision_conflict":
            return PackageDesiredStateCommitResultV1.rejected(
                request,
                observed_inventory_revision=_observed_inventory_revision(
                    self.revisions,
                    request,
                ),
                owner_identity=self.owner_identity,
                owner_revision=event.journal_revision,
            )
        raise RuntimeError(
            "Plugin management desired operation failed: "
            f"{event.result.error_code or 'unknown'}"
        )


def _observed_inventory_revision(
    revisions: PackageProductDesiredRevisionProjectionPort,
    request: PackageDesiredStateCommitRequestV1,
) -> int:
    value = revisions.inventory_revision()
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TypeError("Package desired inventory projection is invalid")
    if value == request.expected_inventory_revision:
        raise RuntimeError("Plugin management conflict lacks changed owner revision")
    return value


__all__ = [
    "PACKAGE_PRODUCT_DESIRED_ADAPTER_VERSION",
    "PackageProductDesiredRevisionProjectionPort",
    "PluginManagementCommandSubmitPort",
    "PluginManagementPackageDesiredStateAdapter",
]
