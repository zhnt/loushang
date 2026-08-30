from __future__ import annotations

from loushang.harness.workspace.exec import ExecBackend

from ..registry import (
    SandboxBackendRegistration,
    SandboxBackendRegistry,
    _builtin_sandbox_backend_registry,
)
from .linux import LinuxBubblewrapBackend


def default_sandbox_backend_registry(
    *,
    local_backend: ExecBackend | None = None,
) -> SandboxBackendRegistry:
    """Return lazy platform registrations used by enabled sandbox bindings."""

    return _builtin_sandbox_backend_registry(
        (
            SandboxBackendRegistration(
                backend_id=LinuxBubblewrapBackend.backend_id,
                os_families=frozenset({"linux"}),
                factory=lambda: LinuxBubblewrapBackend(
                    local_backend=local_backend,
                ),
            ),
        )
    )


__all__ = ["LinuxBubblewrapBackend", "default_sandbox_backend_registry"]
