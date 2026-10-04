"""Private, explicit Windows LPAC Child Session composition."""

from __future__ import annotations

from ._child_session_factory import _create_child_session_host
from ._windows_launch_preparation import _WindowsLpacLaunchCaptureBackend
from .contracts import ChildSessionHostingPort


def _create_windows_lpac_child_session_host(
    *, max_sessions: int = 4
) -> ChildSessionHostingPort:
    return _create_child_session_host(
        max_sessions=max_sessions,
        launch_capture_backend=_WindowsLpacLaunchCaptureBackend(),
    )
