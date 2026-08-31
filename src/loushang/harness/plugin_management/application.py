from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeInventorySnapshotV1,
    PluginInstanceRuntimeSnapshotV1,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginManagementOperationEvent,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.package_lifecycle import (
    PluginPackageLifecycleSnapshotV1,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1,
    PluginInstallationStateV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.plugin_management.retirement_sets import (
    PluginRetirementSetInventorySnapshotV1,
)
from loushang.harness.plugin_management.service import PluginManagementCommand
from loushang.harness.plugin_management.updates import PluginManagementUpdateCommandV2
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

PLUGIN_MANAGEMENT_APPLICATION_COMMAND_VERSION = 1
PLUGIN_MANAGEMENT_APPLICATION_RESULT_VERSION = 1
PLUGIN_MANAGEMENT_PROJECTION_VERSION = 1
PLUGIN_MANAGEMENT_QUERY_VERSION = 1
PLUGIN_MANAGEMENT_MIGRATION_SNAPSHOT_VERSION = 1
PLUGIN_MANAGEMENT_SOURCE_SNAPSHOT_VERSION = 1

PluginManagementSourceKind = Literal["local", "remote", "builtin", "unknown"]
PluginManagementSourceAvailability = Literal[
    "available",
    "unavailable",
    "unknown",
]
PluginManagementMigrationPhase = Literal[
    "accepted",
    "desired_committed",
    "compatibility_window",
    "finalized",
]
PluginManagementConvergence = Literal[
    "active",
    "inactive",
    "retirement_pending",
    "draining",
    "revoking",
    "cleanup_debt",
    "stale",
    "unknown",
]
PluginManagementSkewDisposition = Literal[
    "expected_refresh",
    "transitional_retirement",
    "invariant_violation",
    "unclassified",
]


class PluginManagementCommandServicePort(Protocol):
    def submit(
        self,
        command: PluginManagementCommand,
    ) -> PluginManagementOperationEvent: ...

    def operation(
        self,
        operation_id: str,
    ) -> PluginManagementOperationEvent | None: ...

    def operations(self) -> tuple[PluginManagementOperationEvent, ...]: ...


class PluginDesiredStateProjectionSourcePort(Protocol):
    def snapshot(self) -> PluginDesiredStateSnapshotV1: ...


class PluginInstanceProjectionSourcePort(Protocol):
    def snapshot(self) -> PluginInstanceRuntimeInventorySnapshotV1: ...


class PluginPackageProjectionSourcePort(Protocol):
    def snapshot(self) -> PluginPackageLifecycleSnapshotV1: ...


class PluginRetirementProjectionSourcePort(Protocol):
    def snapshot(self) -> PluginRetirementSetInventorySnapshotV1: ...


@dataclass(frozen=True, slots=True)
class PluginManagementApplicationCommandV1:
    correlation_id: str
    command: PluginManagementCommand
    command_version: int = PLUGIN_MANAGEMENT_APPLICATION_COMMAND_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.correlation_id, name="correlation id")
        if self.command_version != PLUGIN_MANAGEMENT_APPLICATION_COMMAND_VERSION:
            raise ValueError("Unsupported Plugin management application command")


@dataclass(frozen=True, slots=True)
class PluginManagementApplicationResultV1:
    correlation_id: str
    operation: PluginManagementOperationEvent
    result_version: int = PLUGIN_MANAGEMENT_APPLICATION_RESULT_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.correlation_id, name="correlation id")
        if self.result_version != PLUGIN_MANAGEMENT_APPLICATION_RESULT_VERSION:
            raise ValueError("Unsupported Plugin management application result")

    def to_dict(self) -> dict[str, object]:
        return {
            "correlationId": self.correlation_id,
            "operation": self.operation.to_dict(),
            "resultVersion": self.result_version,
        }


class PluginManagementCommandPort(Protocol):
    def submit(
        self,
        request: PluginManagementApplicationCommandV1,
    ) -> PluginManagementApplicationResultV1: ...

    def operation(
        self,
        operation_id: str,
        *,
        correlation_id: str,
    ) -> PluginManagementApplicationResultV1 | None: ...


class PluginManagementCommandApplication:
    """Correlation-preserving adapter over the sole durable command owner."""

    def __init__(self, service: PluginManagementCommandServicePort) -> None:
        if not all(
            callable(getattr(service, name, None))
            for name in ("submit", "operation", "operations")
        ):
            raise TypeError("Plugin management command service is required")
        self._service = service

    def submit(
        self,
        request: PluginManagementApplicationCommandV1,
    ) -> PluginManagementApplicationResultV1:
        if not isinstance(request, PluginManagementApplicationCommandV1):
            raise TypeError("Plugin management application command is required")
        return PluginManagementApplicationResultV1(
            correlation_id=request.correlation_id,
            operation=self._service.submit(request.command),
        )

    def operation(
        self,
        operation_id: str,
        *,
        correlation_id: str,
    ) -> PluginManagementApplicationResultV1 | None:
        _require_nonempty(operation_id, name="operation id")
        _require_nonempty(correlation_id, name="correlation id")
        event = self._service.operation(operation_id)
        if event is None:
            return None
        return PluginManagementApplicationResultV1(
            correlation_id=correlation_id,
            operation=event,
        )


@dataclass(frozen=True, slots=True)
class PluginManagementSourceRecordV1:
    installation_key: PluginInstallationKeyV1
    source_identity: str
    source_kind: PluginManagementSourceKind
    availability: PluginManagementSourceAvailability
    source_location: str | None = None
    plugin_version: str | None = None
    manifest_enabled_default: bool | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.source_identity, name="source identity")
        if self.source_kind not in {"local", "remote", "builtin", "unknown"}:
            raise ValueError("Unsupported Plugin management source kind")
        if self.availability not in {"available", "unavailable", "unknown"}:
            raise ValueError("Unsupported Plugin source availability")
        if self.source_location is not None:
            _require_nonempty(self.source_location, name="source location")
        if self.plugin_version is not None:
            _require_nonempty(self.plugin_version, name="Plugin version")
        if self.manifest_enabled_default is not None and not isinstance(
            self.manifest_enabled_default, bool
        ):
            raise TypeError("Plugin manifest enabled default must be boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "availability": self.availability,
            "installationKey": self.installation_key.to_dict(),
            "manifestEnabledDefault": self.manifest_enabled_default,
            "pluginVersion": self.plugin_version,
            "sourceIdentity": self.source_identity,
            "sourceKind": self.source_kind,
            "sourceLocation": self.source_location,
        }


@dataclass(frozen=True, slots=True)
class PluginManagementSourceSnapshotV1:
    owner_revision: str
    records: tuple[PluginManagementSourceRecordV1, ...]
    snapshot_version: int = PLUGIN_MANAGEMENT_SOURCE_SNAPSHOT_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.owner_revision, name="source owner revision")
        if self.snapshot_version != PLUGIN_MANAGEMENT_SOURCE_SNAPSHOT_VERSION:
            raise ValueError("Unsupported Plugin source snapshot")
        if self.records != tuple(
            sorted(self.records, key=lambda item: item.installation_key)
        ):
            raise ValueError("Plugin source records must be sorted")
        keys = tuple(item.installation_key for item in self.records)
        if len(keys) != len(set(keys)):
            raise ValueError("Plugin source records must be unique by Installation")


class PluginSourceProjectionSourcePort(Protocol):
    def snapshot(self) -> PluginManagementSourceSnapshotV1: ...


@dataclass(frozen=True, order=True, slots=True)
class PluginManagementMigrationRecordV1:
    installation_key: PluginInstallationKeyV1
    phase: PluginManagementMigrationPhase
    journal_revision: int

    def __post_init__(self) -> None:
        if self.phase not in {
            "accepted",
            "desired_committed",
            "compatibility_window",
            "finalized",
        }:
            raise ValueError("Unsupported Plugin management migration phase")
        _require_nonnegative(self.journal_revision, name="migration journal revision")


@dataclass(frozen=True, slots=True)
class PluginManagementMigrationSnapshotV1:
    journal_revision: int
    records: tuple[PluginManagementMigrationRecordV1, ...]
    snapshot_version: int = PLUGIN_MANAGEMENT_MIGRATION_SNAPSHOT_VERSION

    def __post_init__(self) -> None:
        _require_nonnegative(self.journal_revision, name="migration journal revision")
        if self.snapshot_version != PLUGIN_MANAGEMENT_MIGRATION_SNAPSHOT_VERSION:
            raise ValueError("Unsupported Plugin management migration snapshot")
        if self.records != tuple(
            sorted(self.records, key=lambda item: item.installation_key)
        ):
            raise ValueError("Plugin migration records must be sorted")
        keys = tuple(item.installation_key for item in self.records)
        if len(keys) != len(set(keys)):
            raise ValueError("Plugin migration records must be unique by Installation")


class PluginMigrationProjectionSourcePort(Protocol):
    def management_snapshot(self) -> PluginManagementMigrationSnapshotV1: ...


@dataclass(frozen=True, slots=True)
class PluginManagementQueryV1:
    correlation_id: str
    product_id: str
    installation_scope: Literal["process", "tenant", "workspace"]
    scope_id: str
    plugin_ids: tuple[str, ...] = ()
    query_version: int = PLUGIN_MANAGEMENT_QUERY_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.correlation_id, "correlation id"),
            (self.product_id, "Product id"),
            (self.scope_id, "scope id"),
        ):
            _require_nonempty(value, name=name)
        if self.installation_scope not in {"process", "tenant", "workspace"}:
            raise ValueError("Unsupported Plugin Installation scope")
        if self.query_version != PLUGIN_MANAGEMENT_QUERY_VERSION:
            raise ValueError("Unsupported Plugin management query")
        if self.plugin_ids != tuple(sorted(set(self.plugin_ids))):
            raise ValueError("Plugin query ids must be sorted and unique")
        for plugin_id in self.plugin_ids:
            _require_nonempty(plugin_id, name="Plugin query id")

    def matches(self, key: PluginInstallationKeyV1) -> bool:
        return (
            key.product_id == self.product_id
            and key.installation_scope == self.installation_scope
            and key.scope_id == self.scope_id
            and (not self.plugin_ids or key.plugin_id in self.plugin_ids)
        )


@dataclass(frozen=True, slots=True)
class PluginManagementOwnerRevisionsV1:
    desired_state: int
    operations: int
    enablement_migration: int | None
    source: str | None
    instances: int | None
    packages: int | None
    retirement: int | None
    unsupported_dimensions: tuple[str, ...]

    def __post_init__(self) -> None:
        for required_value, name in (
            (self.desired_state, "desired-state revision"),
            (self.operations, "operation revision"),
        ):
            _require_nonnegative(required_value, name=name)
        for optional_value, name in (
            (self.enablement_migration, "enablement migration revision"),
            (self.instances, "Instance revision"),
            (self.packages, "Package revision"),
            (self.retirement, "retirement revision"),
        ):
            if optional_value is not None:
                _require_nonnegative(optional_value, name=name)
        if self.unsupported_dimensions != tuple(
            sorted(set(self.unsupported_dimensions))
        ):
            raise ValueError("Unsupported dimensions must be sorted and unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "desiredState": self.desired_state,
            "enablementMigration": self.enablement_migration,
            "instances": self.instances,
            "operations": self.operations,
            "packages": self.packages,
            "retirement": self.retirement,
            "source": self.source,
            "unsupportedDimensions": list(self.unsupported_dimensions),
        }


@dataclass(frozen=True, slots=True)
class PluginManagementSkewV1:
    code: str
    disposition: PluginManagementSkewDisposition
    installation_key: PluginInstallationKeyV1 | None
    left_owner: str
    left_value: str
    right_owner: str
    right_value: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.code, "skew code"),
            (self.left_owner, "left owner"),
            (self.left_value, "left value"),
            (self.right_owner, "right owner"),
            (self.right_value, "right value"),
        ):
            _require_nonempty(value, name=name)
        if self.disposition not in {
            "expected_refresh",
            "transitional_retirement",
            "invariant_violation",
            "unclassified",
        }:
            raise ValueError("Unsupported Plugin management skew disposition")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "disposition": self.disposition,
            "installationKey": (
                None
                if self.installation_key is None
                else self.installation_key.to_dict()
            ),
            "leftOwner": self.left_owner,
            "leftValue": self.left_value,
            "rightOwner": self.right_owner,
            "rightValue": self.right_value,
        }


@dataclass(frozen=True, order=True, slots=True)
class PluginManagementOperationSummaryV1:
    operation_id: str
    idempotency_key: str
    status: str
    progress_code: str
    disposition: str | None
    error_code: str | None
    journal_revision: int

    def to_dict(self) -> dict[str, object]:
        return {
            "disposition": self.disposition,
            "errorCode": self.error_code,
            "idempotencyKey": self.idempotency_key,
            "journalRevision": self.journal_revision,
            "operationId": self.operation_id,
            "progressCode": self.progress_code,
            "status": self.status,
        }


@dataclass(frozen=True, order=True, slots=True)
class PluginManagementInstanceSummaryV1:
    instance_revision_ref: PluginInstanceRevisionRef
    package_revision: PluginPackageRevisionRefV1
    state: str
    open_lease_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "openLeaseCount": self.open_lease_count,
            "packageRevision": self.package_revision.to_dict(),
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class PluginManagementInstallationViewV1:
    installation_key: PluginInstallationKeyV1
    source: PluginManagementSourceRecordV1 | None
    desired_state: str
    enablement_migration_phase: PluginManagementMigrationPhase | None
    selected_package_revision: PluginPackageRevisionRefV1 | None
    selected_instance_revision_ref: PluginInstanceRevisionRef | None
    operations: tuple[PluginManagementOperationSummaryV1, ...]
    instances: tuple[PluginManagementInstanceSummaryV1, ...]
    retirement_states: tuple[str, ...]
    cleanup_debt_ids: tuple[str, ...]
    convergence: PluginManagementConvergence
    unknown_dimensions: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.operations != tuple(
            sorted(self.operations, key=lambda item: item.operation_id)
        ):
            raise ValueError("Plugin management operation summaries must be sorted")
        if self.instances != tuple(
            sorted(
                self.instances,
                key=lambda item: (
                    item.instance_revision_ref.plugin_id,
                    item.instance_revision_ref.instance_id,
                    item.instance_revision_ref.revision,
                ),
            )
        ):
            raise ValueError("Plugin Instance summaries must be sorted")
        for values, name in (
            (self.retirement_states, "retirement states"),
            (self.cleanup_debt_ids, "cleanup debt ids"),
            (self.unknown_dimensions, "unknown dimensions"),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"Plugin management {name} must be sorted and unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "cleanupDebtIds": list(self.cleanup_debt_ids),
            "convergence": self.convergence,
            "desiredState": self.desired_state,
            "enablementMigrationPhase": self.enablement_migration_phase,
            "installationKey": self.installation_key.to_dict(),
            "instances": [item.to_dict() for item in self.instances],
            "operations": [item.to_dict() for item in self.operations],
            "retirementStates": list(self.retirement_states),
            "selectedInstanceRevisionRef": (
                None
                if self.selected_instance_revision_ref is None
                else self.selected_instance_revision_ref.to_dict()
            ),
            "selectedPackageRevision": (
                None
                if self.selected_package_revision is None
                else self.selected_package_revision.to_dict()
            ),
            "source": None if self.source is None else self.source.to_dict(),
            "unknownDimensions": list(self.unknown_dimensions),
        }


@dataclass(frozen=True, slots=True)
class PluginManagementProjectionV1:
    correlation_id: str
    owner_revisions: PluginManagementOwnerRevisionsV1
    installations: tuple[PluginManagementInstallationViewV1, ...]
    skew: tuple[PluginManagementSkewV1, ...]
    projection_version: int = PLUGIN_MANAGEMENT_PROJECTION_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.correlation_id, name="correlation id")
        if self.projection_version != PLUGIN_MANAGEMENT_PROJECTION_VERSION:
            raise ValueError("Unsupported Plugin management projection")
        if self.installations != tuple(
            sorted(self.installations, key=lambda item: item.installation_key)
        ):
            raise ValueError("Plugin management Installations must be sorted")
        if self.skew != tuple(sorted(self.skew, key=_skew_sort_key)):
            raise ValueError("Plugin management skew must be sorted")

    def to_dict(self) -> dict[str, object]:
        return {
            "correlationId": self.correlation_id,
            "installations": [item.to_dict() for item in self.installations],
            "ownerRevisions": self.owner_revisions.to_dict(),
            "projectionVersion": self.projection_version,
            "skew": [item.to_dict() for item in self.skew],
        }


class PluginManagementQueryPort(Protocol):
    def snapshot(
        self,
        query: PluginManagementQueryV1,
    ) -> PluginManagementProjectionV1: ...


@dataclass(frozen=True, slots=True)
class PluginManagementApplicationPorts:
    commands: PluginManagementCommandPort
    queries: PluginManagementQueryPort

    def __post_init__(self) -> None:
        if not all(
            callable(getattr(self.commands, name, None))
            for name in ("submit", "operation")
        ):
            raise TypeError("Plugin management command port is required")
        if not callable(getattr(self.queries, "snapshot", None)):
            raise TypeError("Plugin management query port is required")


@dataclass(frozen=True, slots=True)
class _CapturedOwners:
    desired: PluginDesiredStateSnapshotV1
    operations: tuple[PluginManagementOperationEvent, ...]
    migrations: PluginManagementMigrationSnapshotV1 | None
    source: PluginManagementSourceSnapshotV1 | None
    instances: PluginInstanceRuntimeInventorySnapshotV1 | None
    packages: PluginPackageLifecycleSnapshotV1 | None
    retirement: PluginRetirementSetInventorySnapshotV1 | None


class PluginManagementReadModelProjector:
    """Read-only join over independently revisioned lifecycle owners."""

    def __init__(
        self,
        *,
        desired_state: PluginDesiredStateProjectionSourcePort,
        operations: PluginManagementCommandServicePort,
        migrations: PluginMigrationProjectionSourcePort | None = None,
        source: PluginSourceProjectionSourcePort | None = None,
        instances: PluginInstanceProjectionSourcePort | None = None,
        packages: PluginPackageProjectionSourcePort | None = None,
        retirement: PluginRetirementProjectionSourcePort | None = None,
    ) -> None:
        self._desired_state = desired_state
        self._operations = operations
        self._migrations = migrations
        self._source = source
        self._instances = instances
        self._packages = packages
        self._retirement = retirement

    def snapshot(
        self,
        query: PluginManagementQueryV1,
    ) -> PluginManagementProjectionV1:
        if not isinstance(query, PluginManagementQueryV1):
            raise TypeError("Plugin management query is required")
        captured = self._capture()
        desired_by_key = {
            state.installation_key: state
            for state in captured.desired.installations
            if query.matches(state.installation_key)
        }
        source_by_key = {
            record.installation_key: record
            for record in (() if captured.source is None else captured.source.records)
            if query.matches(record.installation_key)
        }
        operation_by_key = _operations_by_key(captured.operations, query=query)
        migration_by_key = {
            record.installation_key: record
            for record in (
                () if captured.migrations is None else captured.migrations.records
            )
            if query.matches(record.installation_key)
        }
        instance_by_key = _instances_by_key(captured.instances, query=query)
        keys = tuple(
            sorted(
                set(desired_by_key)
                | set(source_by_key)
                | set(operation_by_key)
                | set(migration_by_key)
                | set(instance_by_key)
            )
        )
        skew = _projection_skew(
            query,
            desired_by_key=desired_by_key,
            instance_by_key=instance_by_key,
            instances_supported=captured.instances is not None,
            packages=captured.packages,
        )
        views = tuple(
            _project_installation(
                key,
                desired=desired_by_key.get(key),
                migration=migration_by_key.get(key),
                source=source_by_key.get(key),
                operations=operation_by_key.get(key, ()),
                instances=instance_by_key.get(key, ()),
                packages=captured.packages,
                retirement=captured.retirement,
                source_supported=captured.source is not None,
                migration_supported=captured.migrations is not None,
                instances_supported=captured.instances is not None,
                packages_supported=captured.packages is not None,
                retirement_supported=captured.retirement is not None,
            )
            for key in keys
        )
        unsupported = ["backup_retention", "private_data", "worker_process"]
        for supported, dimension in (
            (captured.source is not None, "source"),
            (captured.migrations is not None, "enablement_migration"),
            (captured.instances is not None, "instances"),
            (captured.packages is not None, "packages"),
            (captured.retirement is not None, "retirement"),
        ):
            if not supported:
                unsupported.append(dimension)
        return PluginManagementProjectionV1(
            correlation_id=query.correlation_id,
            owner_revisions=PluginManagementOwnerRevisionsV1(
                desired_state=captured.desired.inventory_revision,
                operations=max(
                    (event.journal_revision for event in captured.operations),
                    default=0,
                ),
                enablement_migration=(
                    None
                    if captured.migrations is None
                    else captured.migrations.journal_revision
                ),
                source=(
                    None if captured.source is None else captured.source.owner_revision
                ),
                instances=(
                    None
                    if captured.instances is None
                    else captured.instances.journal_revision
                ),
                packages=(
                    None
                    if captured.packages is None
                    else captured.packages.journal_revision
                ),
                retirement=(
                    None
                    if captured.retirement is None
                    else captured.retirement.journal_revision
                ),
                unsupported_dimensions=tuple(sorted(unsupported)),
            ),
            installations=views,
            skew=skew,
        )

    def _capture(self) -> _CapturedOwners:
        return _CapturedOwners(
            desired=self._desired_state.snapshot(),
            operations=self._operations.operations(),
            migrations=(
                None
                if self._migrations is None
                else self._migrations.management_snapshot()
            ),
            source=None if self._source is None else self._source.snapshot(),
            instances=(None if self._instances is None else self._instances.snapshot()),
            packages=None if self._packages is None else self._packages.snapshot(),
            retirement=(
                None if self._retirement is None else self._retirement.snapshot()
            ),
        )


def _operations_by_key(
    operations: tuple[PluginManagementOperationEvent, ...],
    *,
    query: PluginManagementQueryV1,
) -> dict[PluginInstallationKeyV1, tuple[PluginManagementOperationEvent, ...]]:
    mutable: dict[PluginInstallationKeyV1, list[PluginManagementOperationEvent]] = {}
    for event in operations:
        key = _operation_installation_key(event)
        if query.matches(key):
            mutable.setdefault(key, []).append(event)
    return {
        key: tuple(sorted(events, key=lambda event: event.command.operation_id))
        for key, events in mutable.items()
    }


def _instances_by_key(
    snapshot: PluginInstanceRuntimeInventorySnapshotV1 | None,
    *,
    query: PluginManagementQueryV1,
) -> dict[
    PluginInstallationKeyV1,
    tuple[PluginInstanceRuntimeSnapshotV1, ...],
]:
    if snapshot is None:
        return {}
    mutable: dict[
        PluginInstallationKeyV1,
        list[PluginInstanceRuntimeSnapshotV1],
    ] = {}
    for instance in snapshot.instances:
        if query.matches(instance.installation_key):
            mutable.setdefault(instance.installation_key, []).append(instance)
    return {
        key: tuple(
            sorted(
                values,
                key=lambda item: (
                    item.instance_revision_ref.plugin_id,
                    item.instance_revision_ref.instance_id,
                    item.instance_revision_ref.revision,
                ),
            )
        )
        for key, values in mutable.items()
    }


def _project_installation(
    key: PluginInstallationKeyV1,
    *,
    desired: PluginInstallationStateV1 | None,
    migration: PluginManagementMigrationRecordV1 | None,
    source: PluginManagementSourceRecordV1 | None,
    operations: tuple[PluginManagementOperationEvent, ...],
    instances: tuple[PluginInstanceRuntimeSnapshotV1, ...],
    packages: PluginPackageLifecycleSnapshotV1 | None,
    retirement: PluginRetirementSetInventorySnapshotV1 | None,
    source_supported: bool,
    migration_supported: bool,
    instances_supported: bool,
    packages_supported: bool,
    retirement_supported: bool,
) -> PluginManagementInstallationViewV1:
    selection = None if desired is None else desired.selection
    desired_state = "unknown" if selection is None else selection.desired_state
    selected_package = None if selection is None else selection.package_revision
    selected_instance = None if selection is None else selection.instance_revision_ref
    operation_summaries = tuple(_operation_summary(event) for event in operations)
    instance_summaries = tuple(
        PluginManagementInstanceSummaryV1(
            instance_revision_ref=item.instance_revision_ref,
            package_revision=item.package_revision,
            state=item.state,
            open_lease_count=item.open_lease_count,
        )
        for item in instances
    )
    instance_refs = {item.instance_revision_ref for item in instances}
    retirement_states = tuple(
        sorted(
            {
                item.state
                for item in (() if retirement is None else retirement.sets)
                if item.intent.instance_revision_ref in instance_refs
            }
        )
    )
    relevant_packages = {item.package_revision for item in instances}
    if selected_package is not None:
        relevant_packages.add(selected_package)
    retention = tuple(
        item
        for item in (() if packages is None else packages.packages)
        if item.package_revision in relevant_packages
    )
    cleanup_debt = tuple(
        sorted(
            {
                cleanup_id
                for item in retention
                for cleanup_id in item.terminal_failure_cleanup_ids
            }
        )
    )
    unknown = []
    for supported, dimension in (
        (source_supported, "source"),
        (migration_supported, "enablement_migration"),
        (instances_supported, "instances"),
        (packages_supported, "packages"),
        (retirement_supported, "retirement"),
    ):
        if supported:
            continue
        unknown.append(dimension)
    if source_supported and source is None:
        unknown.append("source")
    if migration_supported and migration is None:
        unknown.append("enablement_migration")
    if (
        instances_supported
        and selected_instance is not None
        and selected_instance not in instance_refs
    ):
        unknown.append("instances")
    if packages_supported and selected_package is not None and not retention:
        unknown.append("packages")
    if (
        packages is not None
        and selected_package is not None
        and not _package_observes_selection(packages, key, selected_package)
    ):
        unknown.append("packages")
    convergence = _convergence(
        desired_state=desired_state,
        enablement_migration_phase=(None if migration is None else migration.phase),
        instances_supported=instances_supported,
        source=source,
        selected_instance=selected_instance,
        instances=instance_summaries,
        cleanup_debt=cleanup_debt,
    )
    return PluginManagementInstallationViewV1(
        installation_key=key,
        source=source,
        desired_state=desired_state,
        enablement_migration_phase=(None if migration is None else migration.phase),
        selected_package_revision=selected_package,
        selected_instance_revision_ref=selected_instance,
        operations=operation_summaries,
        instances=instance_summaries,
        retirement_states=retirement_states,
        cleanup_debt_ids=cleanup_debt,
        convergence=convergence,
        unknown_dimensions=tuple(sorted(set(unknown))),
    )


def _operation_summary(
    event: PluginManagementOperationEvent,
) -> PluginManagementOperationSummaryV1:
    result = event.result
    return PluginManagementOperationSummaryV1(
        operation_id=event.command.operation_id,
        idempotency_key=event.command.idempotency_key,
        status=event.status,
        progress_code=event.progress_code,
        disposition=None if result is None else result.disposition,
        error_code=None if result is None else result.error_code,
        journal_revision=event.journal_revision,
    )


def _convergence(
    *,
    desired_state: str,
    enablement_migration_phase: PluginManagementMigrationPhase | None,
    instances_supported: bool,
    source: PluginManagementSourceRecordV1 | None,
    selected_instance: PluginInstanceRevisionRef | None,
    instances: tuple[PluginManagementInstanceSummaryV1, ...],
    cleanup_debt: tuple[str, ...],
) -> PluginManagementConvergence:
    if enablement_migration_phase in {"accepted", "desired_committed"}:
        return "unknown"
    if cleanup_debt:
        return "cleanup_debt"
    if source is not None and source.availability == "unavailable":
        return "stale"
    if not instances_supported:
        return "unknown"
    states = {item.state for item in instances}
    if "REVOKING" in states:
        return "revoking"
    if "DRAINING" in states:
        return "draining"
    if desired_state == "installed_enabled":
        if any(
            item.instance_revision_ref == selected_instance and item.state == "ACTIVE"
            for item in instances
        ):
            return "active"
        return "inactive"
    if desired_state in {"installed_disabled", "absent"}:
        if any(item.state != "RETIRED" for item in instances):
            return "retirement_pending"
        return "inactive"
    return "unknown"


def _projection_skew(
    query: PluginManagementQueryV1,
    *,
    desired_by_key: dict[PluginInstallationKeyV1, PluginInstallationStateV1],
    instance_by_key: dict[
        PluginInstallationKeyV1,
        tuple[PluginInstanceRuntimeSnapshotV1, ...],
    ],
    instances_supported: bool,
    packages: PluginPackageLifecycleSnapshotV1 | None,
) -> tuple[PluginManagementSkewV1, ...]:
    skew: list[PluginManagementSkewV1] = []
    for key, desired in desired_by_key.items():
        selected_instance = desired.selection.instance_revision_ref
        observed_instances = {
            item.instance_revision_ref for item in instance_by_key.get(key, ())
        }
        if (
            instances_supported
            and selected_instance is not None
            and selected_instance not in observed_instances
        ):
            skew.append(
                PluginManagementSkewV1(
                    code="desired_selected_instance_not_observed",
                    disposition="expected_refresh",
                    installation_key=key,
                    left_owner="desired.instance_revision",
                    left_value=f"{selected_instance.instance_id}:{selected_instance.revision}",
                    right_owner="instances.instance_revision",
                    right_value="missing",
                )
            )
        selected_package = desired.selection.package_revision
        if (
            packages is not None
            and selected_package is not None
            and not _package_observes_selection(packages, key, selected_package)
        ):
            skew.append(
                PluginManagementSkewV1(
                    code="desired_selected_package_not_observed",
                    disposition="expected_refresh",
                    installation_key=key,
                    left_owner="desired.package_revision",
                    left_value=selected_package.package_content_digest,
                    right_owner="packages.package_revision",
                    right_value="missing",
                )
            )
    for key, instances in instance_by_key.items():
        if key not in desired_by_key:
            skew.append(
                PluginManagementSkewV1(
                    code="instance_without_desired_history",
                    disposition="invariant_violation",
                    installation_key=key,
                    left_owner="instances.installation",
                    left_value=key.plugin_id,
                    right_owner="desired.installation",
                    right_value="missing",
                )
            )
    if packages is not None:
        for retention in packages.packages:
            for key in retention.desired_installations:
                if not query.matches(key):
                    continue
                desired_installation = desired_by_key.get(key)
                selected = (
                    None
                    if desired_installation is None
                    else desired_installation.selection.package_revision
                )
                if selected == retention.package_revision:
                    continue
                skew.append(
                    PluginManagementSkewV1(
                        code="package_desired_reference_skew",
                        disposition="expected_refresh",
                        installation_key=key,
                        left_owner="packages.desired_installation",
                        left_value=retention.package_revision.package_content_digest,
                        right_owner="desired.package_revision",
                        right_value=(
                            "missing"
                            if selected is None
                            else selected.package_content_digest
                        ),
                    )
                )
    return tuple(sorted(skew, key=_skew_sort_key))


def _package_observes_selection(
    packages: PluginPackageLifecycleSnapshotV1,
    key: PluginInstallationKeyV1,
    selected_package: PluginPackageRevisionRefV1,
) -> bool:
    return any(
        item.package_revision == selected_package and key in item.desired_installations
        for item in packages.packages
    )


def _operation_installation_key(
    event: PluginManagementOperationEvent,
) -> PluginInstallationKeyV1:
    command = event.command
    if isinstance(command, PluginManagementUpdateCommandV2):
        return command.installation_key
    return command.mutation.installation_key


def _skew_sort_key(
    item: PluginManagementSkewV1,
) -> tuple[str, ...]:
    key = item.installation_key
    return (
        item.code,
        item.disposition,
        "" if key is None else key.product_id,
        "" if key is None else key.installation_scope,
        "" if key is None else key.scope_id,
        "" if key is None else key.plugin_id,
        item.left_owner,
        item.left_value,
        item.right_owner,
        item.right_value,
    )


def _require_nonempty(value: object, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be non-empty")


def _require_nonnegative(value: object, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be non-negative")


__all__ = [
    "PLUGIN_MANAGEMENT_APPLICATION_COMMAND_VERSION",
    "PLUGIN_MANAGEMENT_APPLICATION_RESULT_VERSION",
    "PLUGIN_MANAGEMENT_PROJECTION_VERSION",
    "PLUGIN_MANAGEMENT_QUERY_VERSION",
    "PLUGIN_MANAGEMENT_MIGRATION_SNAPSHOT_VERSION",
    "PLUGIN_MANAGEMENT_SOURCE_SNAPSHOT_VERSION",
    "PluginManagementApplicationCommandV1",
    "PluginManagementApplicationPorts",
    "PluginManagementApplicationResultV1",
    "PluginManagementCommandApplication",
    "PluginManagementCommandPort",
    "PluginManagementInstallationViewV1",
    "PluginManagementMigrationRecordV1",
    "PluginManagementMigrationSnapshotV1",
    "PluginManagementInstanceSummaryV1",
    "PluginManagementOperationSummaryV1",
    "PluginManagementOwnerRevisionsV1",
    "PluginManagementProjectionV1",
    "PluginManagementQueryPort",
    "PluginManagementQueryV1",
    "PluginManagementReadModelProjector",
    "PluginManagementSkewV1",
    "PluginManagementSourceRecordV1",
    "PluginManagementSourceSnapshotV1",
    "PluginMigrationProjectionSourcePort",
    "PluginSourceProjectionSourcePort",
]
