"""Pure layout for the optional lmux managed profile, not native admission.

Composition supplies normalized roots once. Filesystem owners must separately
check permissions, links, stable identity, capacity and Session-root isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING

from .contracts import (
    ManagedContractError,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
    _path,
)

if TYPE_CHECKING:
    from .invocation import ManagedChildInvocationV1

ManagedPath = PurePosixPath | PureWindowsPath

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

    registry: ManagedPath = field(repr=False)
    lifecycle: ManagedPath = field(repr=False)
    application: ManagedPath = field(repr=False)
    control: ManagedPath = field(repr=False)
    logs: ManagedPath = field(repr=False)
    cache: ManagedPath = field(repr=False)
    connection: ManagedPath = field(repr=False)
    runtime_control: ManagedPath = field(repr=False)


@dataclass(frozen=True, slots=True)
class ManagedDeploymentPathsV1:
    """Resolved locations only: possessing this value grants no IO capability."""

    registry: ManagedPath = field(repr=False)
    lifecycle: ManagedPath = field(repr=False)
    application: ManagedPath = field(repr=False)
    control: ManagedPath = field(repr=False)
    logs: ManagedPath = field(repr=False)
    temporary: ManagedPath = field(repr=False)
    cache: ManagedPath = field(repr=False)
    connection: ManagedPath = field(repr=False)
    runtime_control: ManagedPath = field(repr=False)


def _namespace_home(namespace: ManagedNamespaceV1) -> ManagedPath:
    if type(namespace) is not ManagedNamespaceV1:
        raise ManagedContractError()
    return _path(namespace.platform_home)


def resolve_managed_registry_root(namespace: ManagedNamespaceV1) -> ManagedPath:
    """Namespace-level index location, independent of service and client cwd."""
    return _namespace_home(namespace) / "hosts" / "machines" / namespace.machine_id / "registry"


def resolve_managed_admission_root(namespace: ManagedNamespaceV1) -> ManagedPath:
    """Independent durable initialization witness; resolving grants no IO."""
    return _namespace_home(namespace) / "state" / "managed-deployments" / namespace.namespace_key


def resolve_managed_service_paths(
    namespace: ManagedNamespaceV1, service: ManagedServiceKeyV1, *, runtime_root: str,
) -> ManagedServicePathsV1:
    if type(service) is not ManagedServiceKeyV1:
        raise ManagedContractError()
    home = _namespace_home(namespace)
    runtime_base = _path(runtime_root)
    if type(runtime_base) is not type(home) or type(_path(service.host_root)) is not type(home):
        raise ManagedContractError()
    root = home / "hosts"
    runtime = runtime_base / "hosts" / namespace.namespace_key / service.service_id
    # Durable shared state is not deployment scratch, regardless of which
    # subsystem owns a witness beneath it.
    admission = _path(namespace.platform_home) / "state"
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
    root = _path(namespace.platform_home) / "hosts"
    runtime_base = _path(runtime_root)
    runtime = runtime_base / "hosts" / namespace.namespace_key / service.service_id
    if _overlaps(root, runtime):
        raise ManagedContractError()
    machine = root / "machines" / namespace.machine_id
    server = machine / "servers" / service.service_id
    temporary = server / "tmp" / instance.instance_id
    if temporary_override is not None:
        scratch = _path(temporary_override)
        if type(scratch) is not type(root):
            raise ManagedContractError()
        temporary = (
            scratch
            / "hosts" / namespace.namespace_key / service.service_id
            / instance.instance_id
        )
        if (_overlaps(root, temporary) or _overlaps(runtime, temporary)
                or _overlaps(_path(namespace.platform_home) / "state", temporary)):
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


def _overlaps(left: PurePath, right: PurePath) -> bool:
    return left.is_relative_to(right) or right.is_relative_to(left)


def _session_storage_roots(session_root: Path) -> tuple[Path, ...]:
    return (
        session_root,
        session_root.parent / "session-assets",
        session_root.parent / ".session-blob-writers",
    )


def require_separate_managed_session_storage(
    invocation: ManagedChildInvocationV1, *session_roots: Path
) -> None:
    """Keep transcript, Blob and Writer roots outside managed deployment control."""
    home = Path(invocation.namespace.platform_home)
    controls = (
        home / "hosts",
        Path(invocation.runtime_root) / "hosts",
        Path(resolve_managed_admission_root(invocation.namespace)).parent,
        home / "state/session-stores",
        *(
            (Path(invocation.temporary_override) / "hosts",)
            if invocation.temporary_override is not None
            else ()
        ),
    )
    for session_root in session_roots:
        for data in _session_storage_roots(session_root):
            if any(_overlaps(data, control) for control in controls):
                raise ManagedContractError()


__all__ = ["ManagedDeploymentPathsV1", "ManagedServicePathsV1", "resolve_managed_paths", "resolve_managed_service_paths", "resolve_managed_registry_root", "resolve_managed_admission_root"]
