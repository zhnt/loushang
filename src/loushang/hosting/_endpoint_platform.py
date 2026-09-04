"""Private fail-closed selection of inherited endpoint platform adapters."""

from __future__ import annotations

import os
from dataclasses import dataclass

from ._endpoint_backend import _EndpointBackend
from ._process_backend import _ProcessBackend
from .errors import HostingError, HostingFailureCategory


def _select_endpoint_backend(*, max_endpoints: int) -> _EndpointBackend:
    if os.name == "posix":
        from ._posix_endpoint import _PosixEndpointBackend

        return _PosixEndpointBackend()
    if os.name == "nt":
        from ._windows_endpoint import _WindowsEndpointBackend

        return _WindowsEndpointBackend(max_endpoints=max_endpoints)
    raise HostingError(
        HostingFailureCategory.PLATFORM_UNSUPPORTED,
        "no exact Hosting endpoint backend exists for this platform",
    )


@dataclass(frozen=True, slots=True)
class _ChildSessionBackends:
    process: _ProcessBackend
    endpoint: _EndpointBackend


def _select_child_session_backends(
    *,
    max_sessions: int,
    endpoint_io_settlement_seconds: float,
) -> _ChildSessionBackends:
    """Build one exact compatible platform set without partial fallback."""

    if os.name == "posix":
        from ._posix_endpoint import _PosixEndpointBackend
        from ._posix_process import _PosixProcessBackend

        return _ChildSessionBackends(
            process=_PosixProcessBackend(),
            endpoint=_PosixEndpointBackend(),
        )
    if os.name == "nt":
        from ._win32_process import _CtypesWin32Api
        from ._windows_endpoint import _WindowsEndpointBackend
        from ._windows_process import _WindowsProcessBackend

        api = _CtypesWin32Api()
        process = _WindowsProcessBackend(max_processes=max_sessions, api=api)
        try:
            endpoint = _WindowsEndpointBackend(
                max_endpoints=max_sessions,
                io_settlement_seconds=endpoint_io_settlement_seconds,
                api=api,
            )
        except BaseException:
            process._abort_construction()
            raise
        return _ChildSessionBackends(process=process, endpoint=endpoint)
    raise HostingError(
        HostingFailureCategory.PLATFORM_UNSUPPORTED,
        "no exact Hosting child-session backend set exists for this platform",
    )


__all__: list[str] = []
