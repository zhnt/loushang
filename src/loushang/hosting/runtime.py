"""Restrained composition entrypoints for local Hosting owners."""

from __future__ import annotations

import math

from ._child_session_host import _ChildSessionHost
from ._endpoint_host import _InheritedEndpointHost
from ._endpoint_platform import _select_child_session_backends
from ._platform import _select_process_backend
from ._process_host import _ProcessHost, _ProcessHostLimits
from .contracts import (
    ChildSessionHostingPort,
    HostingObservationSink,
    ProcessHostingPort,
)


def create_process_host(
    *,
    max_processes: int = 4,
    max_read_bytes: int = 64 * 1024,
    max_write_bytes: int = 1024 * 1024,
    stderr_tail_bytes: int = 64 * 1024,
    termination_grace_seconds: float = 1.0,
    stderr_drain_seconds: float = 1.0,
    observation_sink: HostingObservationSink | None = None,
) -> ProcessHostingPort:
    """Create the exact supported local process owner or fail closed."""

    limits = _ProcessHostLimits(
        max_processes=max_processes,
        max_read_bytes=max_read_bytes,
        max_write_bytes=max_write_bytes,
        stderr_tail_bytes=stderr_tail_bytes,
        termination_grace_seconds=termination_grace_seconds,
        stderr_drain_seconds=stderr_drain_seconds,
    )
    return _ProcessHost(
        _select_process_backend(max_processes=max_processes),
        limits=limits,
        observation_sink=observation_sink,
    )


def create_child_session_host(
    *,
    max_sessions: int = 4,
    max_read_bytes: int = 64 * 1024,
    max_write_bytes: int = 1024 * 1024,
    stderr_tail_bytes: int = 64 * 1024,
    termination_grace_seconds: float = 1.0,
    stderr_drain_seconds: float = 1.0,
    endpoint_io_settlement_seconds: float = 1.0,
    observation_sink: HostingObservationSink | None = None,
) -> ChildSessionHostingPort:
    """Create an exact atomic child-session owner or fail closed."""

    limits = _ProcessHostLimits(
        max_processes=max_sessions,
        max_read_bytes=max_read_bytes,
        max_write_bytes=max_write_bytes,
        stderr_tail_bytes=stderr_tail_bytes,
        termination_grace_seconds=termination_grace_seconds,
        stderr_drain_seconds=stderr_drain_seconds,
    )
    if (
        not isinstance(endpoint_io_settlement_seconds, (int, float))
        or isinstance(endpoint_io_settlement_seconds, bool)
        or not math.isfinite(endpoint_io_settlement_seconds)
        or endpoint_io_settlement_seconds <= 0
    ):
        raise ValueError(
            "endpoint_io_settlement_seconds must be positive and finite"
        )
    backends = _select_child_session_backends(
        max_sessions=max_sessions,
        endpoint_io_settlement_seconds=float(endpoint_io_settlement_seconds),
    )
    process_host = _ProcessHost(
        backends.process,
        limits=limits,
        observation_sink=observation_sink,
    )
    endpoint_host = _InheritedEndpointHost(
        backends.endpoint,
        max_endpoints=max_sessions,
        max_read_bytes=max_read_bytes,
        max_write_bytes=max_write_bytes,
        observation_sink=observation_sink,
    )
    return _ChildSessionHost(
        process_host,
        endpoint_host,
        max_sessions=max_sessions,
        observation_sink=observation_sink,
    )


__all__ = ["create_child_session_host", "create_process_host"]
