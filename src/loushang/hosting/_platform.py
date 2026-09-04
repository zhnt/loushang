"""Private fail-closed selection of exact process-platform adapters."""

from __future__ import annotations

import os

from ._process_backend import _ProcessBackend
from .errors import HostingError, HostingFailureCategory


def _select_process_backend(*, max_processes: int) -> _ProcessBackend:
    if os.name == "posix":
        from ._posix_process import _PosixProcessBackend

        return _PosixProcessBackend()
    if os.name == "nt":
        from ._windows_process import _WindowsProcessBackend

        return _WindowsProcessBackend(max_processes=max_processes)
    raise HostingError(
        HostingFailureCategory.PLATFORM_UNSUPPORTED,
        "no exact Hosting process backend exists for this platform",
    )


__all__: list[str] = []
