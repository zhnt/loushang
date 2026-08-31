from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loushang.harness.plugin_management import (
    PluginDesiredStateLedger,
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginInstanceActivationV1,
    PluginInstanceRuntimeInventorySnapshotV1,
    PluginInstanceRuntimeSnapshotV1,
    PluginManagementApplicationCommandV1,
    PluginManagementApplicationPorts,
    PluginManagementCommandApplication,
    PluginManagementCommandV1,
    PluginManagementMigrationRecordV1,
    PluginManagementMigrationSnapshotV1,
    PluginManagementQueryV1,
    PluginManagementReadModelProjector,
    PluginManagementService,
    PluginManagementSourceRecordV1,
    PluginManagementSourceSnapshotV1,
    PluginPackageLifecycleSnapshotV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef


def test_application_command_port_preserves_correlation_and_durable_identity(
    tmp_path: Path,
) -> None:
    desired, service = _management(tmp_path)
    commands = PluginManagementCommandApplication(service)
    request = PluginManagementApplicationCommandV1(
        correlation_id="cli:install:coding.base",
        command=_command(action="install", revision=0, package=_package()),
    )

    result = commands.submit(request)

    assert result.correlation_id == request.correlation_id
    assert result.operation.status == "terminal"
    assert result.operation.result is not None
    assert result.operation.result.disposition == "succeeded"
    assert desired.snapshot().inventory_revision == 1
    resumed = commands.operation(
        request.command.operation_id,
        correlation_id="cli:resume:coding.base",
    )
    assert resumed is not None
    assert resumed.correlation_id == "cli:resume:coding.base"
    assert resumed.operation == result.operation
    assert commands.submit(request) == result
    assert result.to_dict()["correlationId"] == request.correlation_id


def test_correlated_projection_joins_owner_snapshots_without_new_state_clock(
    tmp_path: Path,
) -> None:
    desired, service = _management(tmp_path)
    commands = PluginManagementCommandApplication(service)
    commands.submit(
        PluginManagementApplicationCommandV1(
            correlation_id="install",
            command=_command(action="install", revision=0, package=_package()),
        )
    )
    commands.submit(
        PluginManagementApplicationCommandV1(
            correlation_id="enable",
            command=_command(action="enable", revision=1, operation=2),
        )
    )
    source = _SourceOwner(
        PluginManagementSourceSnapshotV1(
            owner_revision="source-config:7",
            records=(
                PluginManagementSourceRecordV1(
                    installation_key=_key(),
                    source_identity="embedded:coding.base",
                    source_kind="builtin",
                    availability="available",
                    source_location="embedded:coding.base",
                    plugin_version="1.0.0",
                    manifest_enabled_default=True,
                ),
            ),
        )
    )
    queries = PluginManagementReadModelProjector(
        desired_state=desired,
        operations=service,
        migrations=_MigrationOwner(
            PluginManagementMigrationSnapshotV1(
                journal_revision=3,
                records=(
                    PluginManagementMigrationRecordV1(
                        installation_key=_key(),
                        phase="compatibility_window",
                        journal_revision=3,
                    ),
                ),
            )
        ),
        source=source,
    )
    ports = PluginManagementApplicationPorts(commands=commands, queries=queries)

    projection = ports.queries.snapshot(_query(correlation_id="cli:list:1"))

    assert projection.correlation_id == "cli:list:1"
    assert projection.owner_revisions.desired_state == 2
    assert projection.owner_revisions.operations == 6
    assert projection.owner_revisions.enablement_migration == 3
    assert projection.owner_revisions.source == "source-config:7"
    assert projection.owner_revisions.instances is None
    assert projection.owner_revisions.unsupported_dimensions == (
        "backup_retention",
        "instances",
        "packages",
        "private_data",
        "retirement",
        "worker_process",
    )
    [installed] = projection.installations
    assert installed.installation_key == _key()
    assert installed.desired_state == "installed_enabled"
    assert installed.enablement_migration_phase == "compatibility_window"
    assert installed.selected_package_revision == _package()
    assert installed.convergence == "inactive"
    assert installed.unknown_dimensions == ("instances", "packages", "retirement")
    assert tuple(item.operation_id for item in installed.operations) == (
        "operation-1",
        "operation-2",
    )
    document = projection.to_dict()
    assert document["projectionVersion"] == 1
    assert document["ownerRevisions"]["desiredState"] == 2
    assert document["installations"][0]["convergence"] == "inactive"
    assert not (tmp_path / "management-projection.json").exists()


def test_projection_reports_orphan_instance_as_invariant_skew(tmp_path: Path) -> None:
    desired, service = _management(tmp_path)
    instance_ref = PluginInstanceRevisionRef(
        instance_id="orphan-instance",
        plugin_id=_key().plugin_id,
        revision=1,
    )
    activation = PluginInstanceActivationV1.create(
        installation_key=_key(),
        instance_revision_ref=instance_ref,
        package_revision=_package(),
        source_inventory_revision=1,
        operation_id="activate-orphan",
        idempotency_key="activate-orphan",
        direct_host_reference="test-host",
    )
    instance = PluginInstanceRuntimeSnapshotV1(
        installation_key=_key(),
        instance_revision_ref=instance_ref,
        package_revision=_package(),
        activation=activation,
        state="ACTIVE",
        retirement_intent=None,
        revocation=None,
        completion=None,
        open_family_ids=(activation.direct_host_family.family_id,),
    )
    queries = PluginManagementReadModelProjector(
        desired_state=desired,
        operations=service,
        instances=_InstanceOwner(
            PluginInstanceRuntimeInventorySnapshotV1(
                journal_revision=1,
                instances=(instance,),
                open_families=(activation.direct_host_family,),
            )
        ),
    )

    projection = queries.snapshot(_query(correlation_id="skew-query"))

    [skew] = projection.skew
    assert skew.code == "instance_without_desired_history"
    assert skew.disposition == "invariant_violation"
    [view] = projection.installations
    assert view.desired_state == "unknown"
    assert view.convergence == "unknown"


def test_projection_reports_selected_facts_missing_from_supported_owners(
    tmp_path: Path,
) -> None:
    desired, service = _management(tmp_path)
    commands = PluginManagementCommandApplication(service)
    commands.submit(
        PluginManagementApplicationCommandV1(
            correlation_id="install",
            command=_command(action="install", revision=0, package=_package()),
        )
    )
    commands.submit(
        PluginManagementApplicationCommandV1(
            correlation_id="enable",
            command=_command(action="enable", revision=1, operation=2),
        )
    )
    queries = PluginManagementReadModelProjector(
        desired_state=desired,
        operations=service,
        instances=_InstanceOwner(
            PluginInstanceRuntimeInventorySnapshotV1(
                journal_revision=0,
                instances=(),
                open_families=(),
            )
        ),
        packages=_PackageOwner(
            PluginPackageLifecycleSnapshotV1(
                journal_revision=0,
                startup_id="test-startup",
                recovery_barrier=None,
                open_pins=(),
                cleanup_tasks=(),
                packages=(),
            )
        ),
    )

    projection = queries.snapshot(_query(correlation_id="missing-owner-facts"))

    assert tuple(item.code for item in projection.skew) == (
        "desired_selected_instance_not_observed",
        "desired_selected_package_not_observed",
    )
    [view] = projection.installations
    assert "instances" in view.unknown_dimensions
    assert "packages" in view.unknown_dimensions


def test_query_filter_does_not_cross_product_or_scope(tmp_path: Path) -> None:
    desired, service = _management(tmp_path)
    source = _SourceOwner(
        PluginManagementSourceSnapshotV1(
            owner_revision="source-config:1",
            records=(
                PluginManagementSourceRecordV1(
                    installation_key=_key(),
                    source_identity="embedded:coding.base",
                    source_kind="builtin",
                    availability="available",
                ),
                PluginManagementSourceRecordV1(
                    installation_key=PluginInstallationKeyV1(
                        product_id="other",
                        installation_scope="workspace",
                        scope_id="workspace-1",
                        plugin_id="other.plugin",
                    ),
                    source_identity="embedded:other.plugin",
                    source_kind="builtin",
                    availability="available",
                ),
            ),
        )
    )
    queries = PluginManagementReadModelProjector(
        desired_state=desired,
        operations=service,
        source=source,
    )

    projection = queries.snapshot(
        PluginManagementQueryV1(
            correlation_id="filtered",
            product_id="coding",
            installation_scope="workspace",
            scope_id="workspace-1",
            plugin_ids=("missing",),
        )
    )

    assert projection.installations == ()


@dataclass(frozen=True)
class _SourceOwner:
    value: PluginManagementSourceSnapshotV1

    def snapshot(self) -> PluginManagementSourceSnapshotV1:
        return self.value


@dataclass(frozen=True)
class _InstanceOwner:
    value: PluginInstanceRuntimeInventorySnapshotV1

    def snapshot(self) -> PluginInstanceRuntimeInventorySnapshotV1:
        return self.value


@dataclass(frozen=True)
class _MigrationOwner:
    value: PluginManagementMigrationSnapshotV1

    def management_snapshot(self) -> PluginManagementMigrationSnapshotV1:
        return self.value


@dataclass(frozen=True)
class _PackageOwner:
    value: PluginPackageLifecycleSnapshotV1

    def snapshot(self) -> PluginPackageLifecycleSnapshotV1:
        return self.value


def _management(
    tmp_path: Path,
) -> tuple[PluginDesiredStateLedger, PluginManagementService]:
    desired = PluginDesiredStateLedger(
        tmp_path / "desired.jsonl",
        instance_id_factory=lambda: "instance-1",
    )
    return desired, PluginManagementService(
        desired_state=desired,
        operation_journal_path=tmp_path / "operations.jsonl",
    )


def _query(*, correlation_id: str) -> PluginManagementQueryV1:
    return PluginManagementQueryV1(
        correlation_id=correlation_id,
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace-1",
    )


def _package() -> PluginPackageRevisionRefV1:
    return PluginPackageRevisionRefV1(
        plugin_id="coding.base",
        plugin_version="1.0.0",
        package_content_digest="1" * 64,
        dependency_lock_digest="2" * 64,
        package_source_identity="embedded:coding.base",
    )


def _key() -> PluginInstallationKeyV1:
    return PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace-1",
        plugin_id="coding.base",
    )


def _command(
    *,
    action: str,
    revision: int,
    package: PluginPackageRevisionRefV1 | None = None,
    operation: int = 1,
) -> PluginManagementCommandV1:
    desired = {
        "install": "installed_disabled",
        "enable": "installed_enabled",
        "disable": "installed_disabled",
        "remove": "absent",
    }[action]
    return PluginManagementCommandV1(
        action=action,
        mutation=PluginDesiredStateMutationV1(
            operation_id=f"operation-{operation}",
            idempotency_key=f"request-{operation}",
            expected_inventory_revision=revision,
            installation_key=_key(),
            desired_state=desired,
            package_revision=package,
            actor_id="operator-1",
            policy_revision="policy-1",
        ),
    )
