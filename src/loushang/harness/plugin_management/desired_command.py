"""Transport-neutral exact Desired State commands through the management owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from .application import (
    PluginManagementApplicationCommandV1,
    PluginManagementApplicationPorts,
    PluginManagementApplicationResultV1,
)
from .operations import PluginManagementCommandV1, PluginManagementOperationEventV1
from .records import (
    PluginDesiredState,
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
)

PluginDesiredActionV1 = Literal["enable", "disable", "remove"]
PluginDesiredRepairDispositionV1 = Literal[
    "unknown", "already_terminal", "replayed_pending"
]


class PluginDesiredCommandRepairError(RuntimeError):
    """A repair request cannot replay the observed operation under this owner."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PluginDesiredCommandAuthorityV1:
    """Product-owned scope and audit identity; transports cannot choose these."""

    product_id: str
    installation_scope: Literal["process", "tenant", "workspace"]
    scope_id: str
    actor_id: str
    policy_revision: str

    def __post_init__(self) -> None:
        for name in ("product_id", "scope_id", "actor_id", "policy_revision"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"Plugin desired command {name} is invalid")
        if self.installation_scope not in {"process", "tenant", "workspace"}:
            raise ValueError("Plugin desired command Installation scope is invalid")


@dataclass(frozen=True, slots=True)
class PluginDesiredCommandRequestV1:
    """One caller-chosen idempotency identity and explicit Desired State CAS."""

    correlation_id: str
    operation_id: str
    plugin_id: str
    action: PluginDesiredActionV1
    expected_inventory_revision: int

    def __post_init__(self) -> None:
        for name in ("correlation_id", "operation_id", "plugin_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"Plugin desired command {name} is invalid")
        if self.action not in {"enable", "disable", "remove"}:
            raise ValueError("Plugin desired command action is unsupported")
        if (
            type(self.expected_inventory_revision) is not int
            or self.expected_inventory_revision < 0
        ):
            raise ValueError("Plugin desired command inventory revision is invalid")


def submit_plugin_desired_command(
    ports: PluginManagementApplicationPorts,
    authority: PluginDesiredCommandAuthorityV1,
    request: PluginDesiredCommandRequestV1,
) -> PluginManagementApplicationResultV1:
    """Submit exactly one owner command; the journal owns replay and CAS refusal."""

    if not isinstance(ports, PluginManagementApplicationPorts):
        raise TypeError("Plugin management application ports are required")
    if not isinstance(authority, PluginDesiredCommandAuthorityV1):
        raise TypeError("Plugin desired command Product authority is required")
    if not isinstance(request, PluginDesiredCommandRequestV1):
        raise TypeError("Plugin desired command request is required")
    target_by_action: dict[PluginDesiredActionV1, PluginDesiredState] = {
        "enable": "installed_enabled",
        "disable": "installed_disabled",
        "remove": "absent",
    }
    target = target_by_action[request.action]
    command = PluginManagementCommandV1(
        action=request.action,
        mutation=PluginDesiredStateMutationV1(
            operation_id=request.operation_id,
            idempotency_key=request.operation_id,
            expected_inventory_revision=request.expected_inventory_revision,
            installation_key=PluginInstallationKeyV1(
                product_id=authority.product_id,
                installation_scope=authority.installation_scope,
                scope_id=authority.scope_id,
                plugin_id=request.plugin_id,
            ),
            desired_state=target,
            package_revision=None,
            actor_id=authority.actor_id,
            policy_revision=authority.policy_revision,
        ),
    )
    result = ports.commands.submit(
        PluginManagementApplicationCommandV1(
            correlation_id=request.correlation_id,
            command=command,
        )
    )
    if (
        not isinstance(result, PluginManagementApplicationResultV1)
        or result.correlation_id != request.correlation_id
        or not isinstance(result.operation, PluginManagementOperationEventV1)
        or result.operation.command != command
    ):
        raise RuntimeError("Plugin command owner returned different operation evidence")
    return result


@dataclass(frozen=True, slots=True)
class PluginDesiredRepairResultV1:
    correlation_id: str
    disposition: PluginDesiredRepairDispositionV1
    status_before: Literal["accepted", "running", "terminal"] | None
    result: PluginManagementApplicationResultV1 | None

    def __post_init__(self) -> None:
        if not isinstance(self.correlation_id, str) or not self.correlation_id:
            raise ValueError("Plugin desired repair correlation id is invalid")
        if self.disposition == "unknown":
            if self.status_before is not None or self.result is not None:
                raise ValueError("Unknown Plugin repair cannot carry an operation")
        elif (
            self.disposition not in {"already_terminal", "replayed_pending"}
            or self.result is None
            or self.result.correlation_id != self.correlation_id
            or (
                self.disposition == "already_terminal"
                and self.status_before != "terminal"
            )
            or (
                self.disposition == "replayed_pending"
                and self.status_before not in {"accepted", "running"}
            )
        ):
            raise ValueError("Plugin desired repair evidence is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "correlationId": self.correlation_id,
            "disposition": self.disposition,
            "statusBefore": self.status_before,
            "result": None if self.result is None else self.result.to_dict(),
            "resultVersion": 1,
        }


def resume_plugin_desired_operation(
    ports: PluginManagementApplicationPorts,
    authority: PluginDesiredCommandAuthorityV1,
    *,
    operation_id: str,
    correlation_id: str,
) -> PluginDesiredRepairResultV1:
    """Re-submit only this Product's original pending A1 command.

    Reading an unknown or terminal operation is inert. A concurrent owner may
    finish a pending command before replay, so the disposition reports the
    observed pre-submit status rather than claiming this caller performed it.
    """

    if not isinstance(ports, PluginManagementApplicationPorts):
        raise TypeError("Plugin management application ports are required")
    if not isinstance(authority, PluginDesiredCommandAuthorityV1):
        raise TypeError("Plugin desired command Product authority is required")
    for value, name in (
        (operation_id, "operation id"),
        (correlation_id, "correlation id"),
    ):
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"Plugin desired repair {name} is invalid")
    observed = ports.commands.operation(
        operation_id, correlation_id=correlation_id
    )
    if observed is None:
        return PluginDesiredRepairResultV1(
            correlation_id=correlation_id,
            disposition="unknown",
            status_before=None,
            result=None,
        )
    if (
        not isinstance(observed, PluginManagementApplicationResultV1)
        or observed.correlation_id != correlation_id
        or not isinstance(observed.operation, PluginManagementOperationEventV1)
    ):
        raise PluginDesiredCommandRepairError(
            "Plugin desired repair operation evidence is incompatible",
            code="plugin_management_repair_evidence_invalid",
        )
    event = observed.operation
    command = event.command
    mutation = command.mutation
    key = mutation.installation_key
    if (
        command.action not in {"enable", "disable", "remove"}
        or mutation.package_revision is not None
    ):
        raise PluginDesiredCommandRepairError(
            "Plugin desired repair does not own this operation kind",
            code="plugin_management_repair_unsupported_operation",
        )
    if (
        mutation.operation_id != operation_id
        or mutation.idempotency_key != operation_id
        or key.product_id != authority.product_id
        or key.installation_scope != authority.installation_scope
        or key.scope_id != authority.scope_id
        or mutation.actor_id != authority.actor_id
        or mutation.policy_revision != authority.policy_revision
    ):
        raise PluginDesiredCommandRepairError(
            "Plugin desired repair operation belongs to another authority",
            code="plugin_management_repair_foreign_operation",
        )
    if event.status == "terminal":
        return PluginDesiredRepairResultV1(
            correlation_id=correlation_id,
            disposition="already_terminal",
            status_before="terminal",
            result=observed,
        )
    replayed = submit_plugin_desired_command(
        ports,
        authority,
        PluginDesiredCommandRequestV1(
            correlation_id=correlation_id,
            operation_id=operation_id,
            plugin_id=key.plugin_id,
            action=cast(PluginDesiredActionV1, command.action),
            expected_inventory_revision=mutation.expected_inventory_revision,
        ),
    )
    if replayed.operation.status != "terminal":
        raise RuntimeError("Plugin desired repair did not settle the operation")
    return PluginDesiredRepairResultV1(
        correlation_id=correlation_id,
        disposition="replayed_pending",
        status_before=event.status,
        result=replayed,
    )


__all__ = [
    "PluginDesiredActionV1",
    "PluginDesiredCommandAuthorityV1",
    "PluginDesiredCommandRepairError",
    "PluginDesiredCommandRequestV1",
    "PluginDesiredRepairDispositionV1",
    "PluginDesiredRepairResultV1",
    "resume_plugin_desired_operation",
    "submit_plugin_desired_command",
]
