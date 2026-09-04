from __future__ import annotations

import os
import platform
import sys

import pytest

from loushang.hosting import HostingError, HostingFailureCategory
from loushang.hosting._posix_launch_preparation import (
    _PosixStaticLaunchCaptureBackend,
)


def test_posix_static_launch_backend_is_exactly_linux_or_fails_closed() -> None:
    if (
        os.name == "posix"
        and sys.platform.startswith("linux")
        and platform.machine().lower() in {"amd64", "x86_64"}
    ):
        backend = _PosixStaticLaunchCaptureBackend()
        assert backend.backend_id == "posix-process-group-v1"
        return

    with pytest.raises(HostingError) as failure:
        _PosixStaticLaunchCaptureBackend()
    assert failure.value.category is HostingFailureCategory.PLATFORM_UNSUPPORTED
