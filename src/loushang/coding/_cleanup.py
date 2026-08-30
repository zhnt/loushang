"""Coding-owned helpers for failure-preserving cleanup chains."""

from __future__ import annotations

from collections.abc import Callable, Iterable

CleanupStep = tuple[str, Callable[[], None]]


def run_cleanup_steps(
    primary_error: BaseException | None,
    steps: Iterable[CleanupStep],
) -> BaseException | None:
    """Attempt every cleanup step without replacing an earlier failure."""

    settled_error = primary_error
    for label, cleanup in steps:
        try:
            cleanup()
        except BaseException as cleanup_error:
            if settled_error is None:
                settled_error = cleanup_error
            else:
                settled_error.add_note(f"{label} also failed: {cleanup_error}")
    return settled_error


__all__ = ["CleanupStep", "run_cleanup_steps"]
