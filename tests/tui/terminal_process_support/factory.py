from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from .protocol import TerminalProcessDriver


def selected_backend_name() -> str:
    return "conpty" if os.name == "nt" else "posix-pty"


def spawn_terminal_process(
    args: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    columns: int = 80,
    rows: int = 24,
) -> TerminalProcessDriver:
    selected = selected_backend_name()
    required = os.environ.get("LOUSHANG_REQUIRED_TERMINAL_BACKEND")
    if required is not None and required != selected:
        raise RuntimeError(
            f"required terminal backend is {required!r}, selected {selected!r}"
        )
    if selected == "conpty":
        from .windows_conpty import WindowsConPtyDriver

        driver = WindowsConPtyDriver
    else:
        from .posix_pty import PosixPtyDriver

        driver = PosixPtyDriver
    return driver.spawn(
        args,
        cwd=cwd,
        env=env,
        columns=columns,
        rows=rows,
    )
