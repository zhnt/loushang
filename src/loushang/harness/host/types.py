from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HostActionResult:
    """Product-neutral outcome returned by an interactive host action."""

    handled: bool = True
    exit_code: int | None = None
    error_message: str | None = None
    status_message: str | None = None
    traceback_text: str | None = None


__all__ = ["HostActionResult"]
