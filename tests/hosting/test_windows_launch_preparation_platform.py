from __future__ import annotations

import os
import platform

import pytest

from loushang.hosting import HostingError, HostingFailureCategory
from loushang.hosting._windows_launch_preparation import (
    _WindowsRestrictedLaunchCaptureBackend,
)


def test_windows_restricted_native_backend_is_exact_platform_or_fails_closed() -> None:
    if os.name == "nt" and platform.machine().lower() in {"amd64", "x86_64"}:
        assert _WindowsRestrictedLaunchCaptureBackend().backend_id == "windows-job-v1"
    else:
        with pytest.raises(HostingError) as failure:
            _WindowsRestrictedLaunchCaptureBackend()
        assert failure.value.category is HostingFailureCategory.PLATFORM_UNSUPPORTED
