"""Restrained composition entrypoints for local Hosting owners."""

from __future__ import annotations

import os

from ._child_session_factory import _create_child_session_host
from ._platform import _select_process_backend
from ._process_host import _ProcessHost, _ProcessHostLimits
from .contracts import (
    ChildSessionHostingPort,
    HostingObservationSink,
    ProcessHostingPort,
)
from .errors import HostingError, HostingFailureCategory


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
    enable_posix_static_capture: bool = False,
    observation_sink: HostingObservationSink | None = None,
) -> ChildSessionHostingPort:
    """Create an exact atomic child-session owner or fail closed."""

    if type(enable_posix_static_capture) is not bool:
        raise TypeError("POSIX static capture selection must be boolean")
    if enable_posix_static_capture and os.name != "posix":
        raise HostingError(
            HostingFailureCategory.PLATFORM_UNSUPPORTED,
            "POSIX static capture is unavailable on this platform",
        )
    capture_backend = None
    if enable_posix_static_capture:
        from ._posix_launch_preparation import _PosixStaticLaunchCaptureBackend

        capture_backend = _PosixStaticLaunchCaptureBackend()
    return _create_child_session_host(
        max_sessions=max_sessions,
        max_read_bytes=max_read_bytes,
        max_write_bytes=max_write_bytes,
        stderr_tail_bytes=stderr_tail_bytes,
        termination_grace_seconds=termination_grace_seconds,
        stderr_drain_seconds=stderr_drain_seconds,
        endpoint_io_settlement_seconds=endpoint_io_settlement_seconds,
        observation_sink=observation_sink,
        launch_capture_backend=capture_backend,
    )


__all__ = ["create_child_session_host", "create_process_host"]
