"""Pure layout for the optional lmux managed profile, not native admission.

Composition supplies normalized roots once. Filesystem owners must separately
check permissions, links, stable identity, capacity and Session-root isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .contracts import (
    ManagedContractError,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
    _path,
)


@dataclass(frozen=True, slots=True)
class ManagedDeploymentPathsV1:
    """Resolved locations only: possessing this value grants no IO capability."""

    registry: PurePosixPath = field(repr=False)
    lifecycle: PurePosixPath = field(repr=False)
    application: PurePosixPath = field(repr=False)
    control: PurePosixPath = field(repr=False)
    logs: PurePosixPath = field(repr=False)
    temporary: PurePosixPath = field(repr=False)
    cache: PurePosixPath = field(repr=False)
    connection: PurePosixPath = field(repr=False)
    runtime_control: PurePosixPath = field(repr=False)


def resolve_managed_paths(
    namespace: ManagedNamespaceV1,
    service: ManagedServiceKeyV1,
    instance: ManagedInstanceRefV1,
    *,
    runtime_root: str,
    temporary_override: str | None = None,
) -> ManagedDeploymentPathsV1:
    """Bind all paths to the same namespace/service/instance without IO.

    An explicit temporary override wins over centralized scratch. The derived
    runtime/temporary namespaces cannot overlap the durable root or one another;
    Default centralized scratch is a separate instance leaf, never an application
    record or Session directory.
    """
    if (
        type(namespace) is not ManagedNamespaceV1
        or type(service) is not ManagedServiceKeyV1
        or type(instance) is not ManagedInstanceRefV1
        or instance.namespace_key != namespace.namespace_key
        or instance.service_id != service.service_id
    ):
        raise ManagedContractError()
    _path(runtime_root)
    root = PurePosixPath(namespace.platform_home) / "lmux"
    runtime_base = PurePosixPath(runtime_root)
    runtime = runtime_base / "lmux" / namespace.namespace_key / service.service_id
    if _overlaps(root, runtime):
        raise ManagedContractError()
    machine = root / "machines" / namespace.machine_id
    server = machine / "servers" / service.service_id
    temporary = server / "tmp" / instance.instance_id
    if temporary_override is not None:
        _path(temporary_override)
        temporary = (
            PurePosixPath(temporary_override)
            / "lmux" / namespace.namespace_key / service.service_id
            / instance.instance_id
        )
        if _overlaps(root, temporary) or _overlaps(runtime, temporary):
            raise ManagedContractError()
    return ManagedDeploymentPathsV1(
        registry=machine / "registry",
        lifecycle=machine / "lifecycle" / service.service_id,
        application=server / "state" / "application",
        control=server / "state" / "control",
        logs=server / "logs",
        temporary=temporary,
        cache=machine / "cache",
        connection=runtime / "connection",
        runtime_control=runtime / "control",
    )


def _overlaps(left: PurePosixPath, right: PurePosixPath) -> bool:
    return left.is_relative_to(right) or right.is_relative_to(left)


__all__ = ["ManagedDeploymentPathsV1", "resolve_managed_paths"]
