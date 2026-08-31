"""Transport-only binding for Plugin management CLI adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from loushang.harness.plugin_management import (
    PluginManagementApplicationPorts,
    PluginManagementProjectionV1,
    PluginManagementQueryV1,
)


@dataclass(frozen=True, slots=True)
class PluginManagementCliBinding:
    ports: PluginManagementApplicationPorts
    product_id: str
    installation_scope: Literal["process", "tenant", "workspace"]
    scope_id: str
    actor_id: str
    policy_revision: str
    publish_compatibility_projection: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.product_id, "Product id"),
            (self.scope_id, "scope id"),
            (self.actor_id, "actor id"),
            (self.policy_revision, "policy revision"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        if self.installation_scope not in {"process", "tenant", "workspace"}:
            raise ValueError("Unsupported Plugin Installation scope")

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


__all__ = ["PluginManagementCliBinding"]
