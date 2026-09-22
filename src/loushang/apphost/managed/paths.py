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

# Names shared by the two diagnostic formats in one retained directory. These
# are layout facts only; each consumer must validate its own files and charges.
LIFECYCLE_LOG_NAMES = tuple(f"lifecycle-{slot}.jsonl" for slot in range(5))
TRACE_LOG_NAMES = ("trace-0.jsonl", "trace-1.jsonl")
MANAGED_LOG_DIRECTORY_NAMES = frozenset({
    "lifecycle.lock", *LIFECYCLE_LOG_NAMES, "trace.lock", *TRACE_LOG_NAMES,
})


@dataclass(frozen=True, slots=True)
class ManagedServicePathsV1:
    """Stable service paths, available before an instance is reserved."""

    registry: PurePosixPath = field(repr=False)
    lifecycle: PurePosixPath = field(repr=False)
    application: PurePosixPath = field(repr=False)
    control: PurePosixPath = field(repr=False)
    logs: PurePosixPath = field(repr=False)
    cache: PurePosixPath = field(repr=False)
    connection: PurePosixPath = field(repr=False)
    runtime_control: PurePosixPath = field(repr=False)


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


def resolve_managed_registry_root(namespace: ManagedNamespaceV1) -> PurePosixPath:
    """Namespace-level index location, independent of service and client cwd."""
    if type(namespace) is not ManagedNamespaceV1:
        raise ManagedContractError()
    return PurePosixPath(namespace.platform_home) / "lmux" / "machines" / namespace.machine_id / "registry"


def resolve_managed_admission_root(namespace: ManagedNamespaceV1) -> PurePosixPath:
    """Independent durable initialization witness; resolving grants no IO."""
    if type(namespace) is not ManagedNamespaceV1:
        raise ManagedContractError()
    return PurePosixPath(namespace.platform_home) / "state" / "managed-deployments" / namespace.namespace_key


def resolve_managed_service_paths(
    namespace: ManagedNamespaceV1, service: ManagedServiceKeyV1, *, runtime_root: str,
) -> ManagedServicePathsV1:
    if type(namespace) is not ManagedNamespaceV1 or type(service) is not ManagedServiceKeyV1:
        raise ManagedContractError()
    _path(runtime_root)
    root = PurePosixPath(namespace.platform_home) / "lmux"
    runtime = PurePosixPath(runtime_root) / "lmux" / namespace.namespace_key / service.service_id
    # Durable shared state is not deployment scratch, regardless of which
    # subsystem owns a witness beneath it.
    admission = PurePosixPath(namespace.platform_home) / "state"
    if _overlaps(root, runtime) or _overlaps(admission, runtime):
        raise ManagedContractError()
    machine = root / "machines" / namespace.machine_id
    server = machine / "servers" / service.service_id
    return ManagedServicePathsV1(
        registry=resolve_managed_registry_root(namespace), lifecycle=machine / "lifecycle" / service.service_id,
        application=server / "state" / "application", control=server / "state" / "control",
        logs=server / "logs", cache=machine / "cache",
        connection=runtime / "connection", runtime_control=runtime / "control",
    )


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
    stable = resolve_managed_service_paths(namespace, service, runtime_root=runtime_root)
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
        if (_overlaps(root, temporary) or _overlaps(runtime, temporary)
                or _overlaps(PurePosixPath(namespace.platform_home) / "state", temporary)):
            raise ManagedContractError()
    return ManagedDeploymentPathsV1(
        registry=stable.registry,
        lifecycle=stable.lifecycle,
        application=stable.application,
        control=stable.control,
        logs=stable.logs,
        temporary=temporary,
        cache=stable.cache,
        connection=stable.connection,
        runtime_control=stable.runtime_control,
    )


def _overlaps(left: PurePosixPath, right: PurePosixPath) -> bool:
    return left.is_relative_to(right) or right.is_relative_to(left)


__all__ = ["ManagedDeploymentPathsV1", "ManagedServicePathsV1", "resolve_managed_paths", "resolve_managed_service_paths", "resolve_managed_registry_root", "resolve_managed_admission_root"]
