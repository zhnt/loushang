"""Cross-platform text clipboard capability for terminal products."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ClipboardCopyResult:
    ok: bool
    command: str | None = None
    message: str | None = None


ClipboardCommandRunner = Callable[..., ClipboardCopyResult]


def copy_to_clipboard(
    text: str,
    *,
    env: Mapping[str, str] | None = None,
    runner: ClipboardCommandRunner | None = None,
    platform: str | None = None,
    timeout_seconds: float = 3,
) -> ClipboardCopyResult:
    environment = os.environ if env is None else env
    command_runner = _run_copy_command if runner is None else runner
    last_result = ClipboardCopyResult(
        ok=False,
        message="No clipboard command was available.",
    )

    for command, args in _clipboard_command_candidates(
        environment,
        platform or sys.platform,
    ):
        result = command_runner(
            command,
            args,
            input_text=text,
            timeout_seconds=timeout_seconds,
        )
        if result.ok:
            return result
        last_result = (
            result
            if result.message
            else ClipboardCopyResult(ok=False, command=command)
        )
    return last_result


def _clipboard_command_candidates(
    env: Mapping[str, str],
    platform: str,
) -> list[tuple[str, tuple[str, ...]]]:
    normalized_platform = platform.lower()
    if normalized_platform == "darwin":
        return [("pbcopy", tuple())]
    if normalized_platform.startswith(("win32", "cygwin", "msys")):
        return [("clip.exe", tuple())]
    if env.get("TERMUX_VERSION"):
        return [("termux-clipboard-set", tuple())]
    if env.get("WAYLAND_DISPLAY") or env.get("XDG_SESSION_TYPE") == "wayland":
        return [
            ("wl-copy", tuple()),
            ("xclip", ("-selection", "clipboard")),
            ("xsel", ("--clipboard", "--input")),
        ]
    return [
        ("xclip", ("-selection", "clipboard")),
        ("xsel", ("--clipboard", "--input")),
        ("wl-copy", tuple()),
    ]


def _run_copy_command(
    command: str,
    args: tuple[str, ...],
    *,
    input_text: str,
    timeout_seconds: float = 3,
) -> ClipboardCopyResult:
    try:
        result = subprocess.run(
            [command, *args],
            check=False,
            input=input_text,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ClipboardCopyResult(
            ok=False,
            command=command,
            message=str(exc),
        )
    return ClipboardCopyResult(ok=result.returncode == 0, command=command)


__all__ = ["ClipboardCopyResult", "copy_to_clipboard"]
