from __future__ import annotations

from typing import Literal

ExecLaunchErrorKind = Literal[
    "cwd_not_found",
    "cwd_not_directory",
    "executable_not_found",
    "spawn_failed",
]


class ExecLaunchError(RuntimeError):
    """Typed local process launch failure without environment disclosure."""

    def __init__(
        self,
        kind: ExecLaunchErrorKind,
        *,
        command: tuple[str, ...],
        cwd: str,
        cause: BaseException | None = None,
    ) -> None:
        self.kind = kind
        self.command = command
        self.cwd = cwd
        self.executable = command[0] if command else None
        self.cause = cause
        super().__init__(self._message())

    def _message(self) -> str:
        if self.kind == "cwd_not_found":
            return f"execution cwd does not exist: {self.cwd}"
        if self.kind == "cwd_not_directory":
            return f"execution cwd is not a directory: {self.cwd}"
        if self.kind == "executable_not_found":
            executable = self.executable or "<empty command>"
            return f"execution executable was not found: {executable}"
        executable = self.executable or "<empty command>"
        detail = f": {self.cause}" if self.cause is not None else ""
        return f"failed to start execution executable {executable}{detail}"


__all__ = ["ExecLaunchError", "ExecLaunchErrorKind"]
