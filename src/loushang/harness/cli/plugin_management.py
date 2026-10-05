"""Transport-only binding for Plugin management CLI adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from loushang.harness.plugin_management import (
    PluginManagementApplicationPorts,
    PluginManagementProjectionV1,
    PluginManagementQueryV1,
)
from loushang.harness.plugin_management.application import (
    PluginSourceProjectionSourcePort,
)
from loushang.harness.plugin_management.read_binding import (
    empty_management_read_ports,
    read_only_management_ports,
)


def _validate_profile_identity(
    product_id: str,
    installation_scope: str,
    scope_id: str,
    actor_id: str,
    policy_revision: str,
) -> None:
    for value, name in (
        (product_id, "Product id"),
        (scope_id, "scope id"),
        (actor_id, "actor id"),
        (policy_revision, "policy revision"),
    ):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be non-empty")
    if installation_scope not in {"process", "tenant", "workspace"}:
        raise ValueError("Unsupported Plugin Installation scope")


@dataclass(frozen=True, slots=True)
class PluginManagementCliBinding:
    ports: PluginManagementApplicationPorts
    product_id: str
    installation_scope: Literal["process", "tenant", "workspace"]
    scope_id: str
    actor_id: str
    policy_revision: str
    publish_compatibility_projection: Callable[[], None] | None = None
    fresh_product: bool = False

    def __post_init__(self) -> None:
        _validate_profile_identity(
            self.product_id,
            self.installation_scope,
            self.scope_id,
            self.actor_id,
            self.policy_revision,
        )
        if type(self.fresh_product) is not bool:
            raise TypeError("Plugin management Product mode is invalid")

    def query(
        self,
        *,
        correlation_id: str,
        plugin_ids: tuple[str, ...] = (),
    ) -> PluginManagementProjectionV1:
        return self.ports.queries.snapshot(
            PluginManagementQueryV1(
                correlation_id=correlation_id,
                product_id=self.product_id,
                installation_scope=self.installation_scope,
                scope_id=self.scope_id,
                plugin_ids=tuple(sorted(set(plugin_ids))),
            )
        )

    def publish_compatibility(self) -> None:
        """Publish an optional Product-owned downgrade view after a write."""

        if self.publish_compatibility_projection is not None:
            self.publish_compatibility_projection()


@dataclass(frozen=True, slots=True)
class PluginManagementCliProfile:
    """Immutable Product facts shared by the command and read bindings."""

    product_id: str
    installation_scope: Literal["process", "tenant", "workspace"]
    scope_id: str
    actor_id: str
    policy_revision: str
    def __post_init__(self) -> None:
        _validate_profile_identity(
            self.product_id,
            self.installation_scope,
            self.scope_id,
            self.actor_id,
            self.policy_revision,
        )


@runtime_checkable
class PluginManagementCliReadOwnerStrategy(Protocol):
    """Only owner reads needed to choose fenced, legacy, or empty state."""

    @property
    def source(self) -> PluginSourceProjectionSourcePort: ...

    def fenced_product_exists(self) -> bool: ...

    def open_fenced_ports(self) -> PluginManagementApplicationPorts: ...

    def legacy_state_exists(self) -> bool: ...

    def open_legacy_read_ports(self) -> PluginManagementApplicationPorts: ...


@runtime_checkable
class PluginManagementCliCommandOwnerStrategy(Protocol):
    """Owner commands and Product-owned legacy startup cleanup."""

    def fenced_product_exists(self) -> bool: ...

    def open_fenced_ports(self) -> PluginManagementApplicationPorts: ...

    def acquire_legacy_startup(self) -> Callable[[], None] | None: ...

    def open_legacy_ports(self) -> PluginManagementApplicationPorts: ...

    def bind_legacy_compatibility(self) -> Callable[[], None] | None: ...


def bind_plugin_management_cli_commands(
    profile: PluginManagementCliProfile,
    owner: PluginManagementCliCommandOwnerStrategy,
) -> PluginManagementCliBinding:
    """Open one command owner; roll back a Product startup claim on failure."""

    if profile is None or not isinstance(profile, PluginManagementCliProfile):
        raise TypeError("Plugin management command Product profile is required")
    if not isinstance(owner, PluginManagementCliCommandOwnerStrategy):
        raise TypeError("Plugin management command owner strategy is required")
    if owner.fenced_product_exists():
        return PluginManagementCliBinding(
            ports=owner.open_fenced_ports(),
            product_id=profile.product_id,
            installation_scope=profile.installation_scope,
            scope_id=profile.scope_id,
            actor_id=profile.actor_id,
            policy_revision=profile.policy_revision,
            fresh_product=True,
        )
    release_on_failure = owner.acquire_legacy_startup()
    try:
        ports = owner.open_legacy_ports()
        publish = owner.bind_legacy_compatibility()
        if publish is not None:
            publish()
        return PluginManagementCliBinding(
            ports=ports,
            product_id=profile.product_id,
            installation_scope=profile.installation_scope,
            scope_id=profile.scope_id,
            actor_id=profile.actor_id,
            policy_revision=profile.policy_revision,
            publish_compatibility_projection=publish,
        )
    except BaseException:
        if release_on_failure is not None:
            release_on_failure()
        raise


def bind_plugin_management_cli_read(
    profile: PluginManagementCliProfile,
    owner: PluginManagementCliReadOwnerStrategy,
) -> PluginManagementCliBinding:
    """Choose the owner's existing state without starting or repairing it."""

    if profile is None or not isinstance(profile, PluginManagementCliProfile):
        raise TypeError("Plugin management read Product profile is required")
    if not isinstance(owner, PluginManagementCliReadOwnerStrategy):
        raise TypeError("Plugin management read owner strategy is required")
    if owner.fenced_product_exists():
        ports = owner.open_fenced_ports()
        fresh_product = True
    elif owner.legacy_state_exists():
        ports = owner.open_legacy_read_ports()
        fresh_product = False
    else:
        ports = empty_management_read_ports(owner.source)
        fresh_product = False
    return PluginManagementCliBinding(
        ports=read_only_management_ports(ports),
        product_id=profile.product_id,
        installation_scope=profile.installation_scope,
        scope_id=profile.scope_id,
        actor_id=profile.actor_id,
        policy_revision=profile.policy_revision,
        fresh_product=fresh_product,
    )


__all__ = [
    "PluginManagementCliBinding",
    "PluginManagementCliCommandOwnerStrategy",
    "PluginManagementCliProfile",
    "PluginManagementCliReadOwnerStrategy",
    "bind_plugin_management_cli_commands",
    "bind_plugin_management_cli_read",
]
