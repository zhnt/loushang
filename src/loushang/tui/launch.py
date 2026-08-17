"""Product-neutral launch routing for terminal applications."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Protocol, TextIO


class TuiLaunchRunner(Protocol):
    """Run one already-assembled terminal presentation."""

    async def __call__(self) -> int: ...


@dataclass(frozen=True, slots=True)
class TuiLaunchProfile:
    """Presentation runners, copy, and exit policy for a TUI launch."""

    run_screen: TuiLaunchRunner
    run_plain: TuiLaunchRunner
    error_prefix: str
    failure_exit_code: int = 1


def is_interactive_terminal(*, stdin: TextIO, stdout: TextIO) -> bool:
    """Return whether both terminal streams support interactive presentation."""

    stdin_is_tty = getattr(stdin, "isatty", lambda: False)
    stdout_is_tty = getattr(stdout, "isatty", lambda: False)
    return bool(stdin_is_tty() and stdout_is_tty())


def select_tui_launch_runner(
    *,
    stdin: TextIO,
    stdout: TextIO,
    profile: TuiLaunchProfile,
) -> TuiLaunchRunner:
    """Select the screen runner only when both streams are interactive."""

    if is_interactive_terminal(stdin=stdin, stdout=stdout):
        return profile.run_screen
    return profile.run_plain


async def run_tui_launch_shell(
    *,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    profile: TuiLaunchProfile,
    verbose: bool = False,
) -> int:
    """Route an assembled TUI and map outer failures to terminal output."""

    try:
        runner = select_tui_launch_runner(
            stdin=stdin,
            stdout=stdout,
            profile=profile,
        )
        return await runner()
    except Exception as error:
        detail = str(error) or error.__class__.__name__
        stdout.write(f"{profile.error_prefix}{detail}\n")
        stdout.flush()
        if verbose:
            stderr.write(traceback.format_exc())
            stderr.flush()
        return profile.failure_exit_code


__all__ = [
    "TuiLaunchProfile",
    "TuiLaunchRunner",
    "is_interactive_terminal",
    "run_tui_launch_shell",
    "select_tui_launch_runner",
]
