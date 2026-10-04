"""Query-only Plugin management application ports and empty owner projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Never

from loushang.harness.plugin_management.application import (
    PluginManagementApplicationCommandV1,
    PluginManagementApplicationPorts,
    PluginManagementApplicationResultV1,
    PluginManagementCommandApplication,
    PluginManagementCommandPort,
    PluginManagementReadModelProjector,
    PluginSourceProjectionSourcePort,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1


@dataclass(frozen=True, slots=True)
class _ReadOnlyCommands:
    delegate: PluginManagementCommandPort

    def submit(self, _request: PluginManagementApplicationCommandV1) -> Never:
        raise PermissionError("Plugin management read binding cannot submit commands")

    def operation(
        self, operation_id: str, *, correlation_id: str
    ) -> PluginManagementApplicationResultV1 | None:
        return self.delegate.operation(operation_id, correlation_id=correlation_id)


class _EmptyDesiredState:
    def snapshot(self) -> PluginDesiredStateSnapshotV1:
        return PluginDesiredStateSnapshotV1(inventory_revision=0, installations=())


class _EmptyOperations:
    def submit(self, _request: object) -> Never:
        raise PermissionError("Plugin management read binding cannot submit commands")

    def operation(self, _operation_id: str) -> None:
        return None

    def operations(self) -> tuple[()]:
        return ()


def read_only_management_ports(
    ports: PluginManagementApplicationPorts,
) -> PluginManagementApplicationPorts:
    """Keep query and operation lookup while denying submission at the port."""

    return PluginManagementApplicationPorts(
        commands=_ReadOnlyCommands(ports.commands),
        queries=ports.queries,
    )


def empty_management_read_ports(
    source: PluginSourceProjectionSourcePort,
) -> PluginManagementApplicationPorts:
    """Project a workspace with no owner state without creating journal files."""

    operations = _EmptyOperations()
    return PluginManagementApplicationPorts(
        commands=_ReadOnlyCommands(PluginManagementCommandApplication(operations)),
        queries=PluginManagementReadModelProjector(
            desired_state=_EmptyDesiredState(),
            operations=operations,
            source=source,
        ),
    )


__all__ = ["empty_management_read_ports", "read_only_management_ports"]
