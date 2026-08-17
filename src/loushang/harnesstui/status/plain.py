from __future__ import annotations

from dataclasses import dataclass

from loushang.tui.cell_width import strip_control_sequences
from loushang.tui.text_utils import fixed_width


@dataclass(frozen=True)
class PlainToolbarSnapshot:
    model: str | None = None
    cwd: str | None = None
    branch: str | None = None
    session: str | None = None
    thinking: str | None = None
    context: str | None = None
    window: str | None = None
    tokens: str | None = None
    message: str | None = None
    running: bool = False


def render_plain_toolbar(
    snapshot: PlainToolbarSnapshot,
    *,
    width: int | None = None,
) -> str:
    parts: list[str] = []
    _append_part(parts, "model", snapshot.model)
    _append_part(parts, "cwd", snapshot.cwd)
    _append_part(parts, "branch", snapshot.branch)
    _append_part(parts, "session", snapshot.session)
    _append_part(parts, "thinking", snapshot.thinking)
    _append_part(parts, "context", snapshot.context)
    _append_part(parts, "window", snapshot.window)
    _append_part(parts, "tokens", snapshot.tokens)
    if snapshot.running:
        parts.append("running")
    if snapshot.message:
        parts.append(snapshot.message)
    text = " | ".join(parts)
    if width is None:
        return text
    return strip_control_sequences(fixed_width(text, width=width))


def _append_part(parts: list[str], name: str, value: str | None) -> None:
    if value:
        parts.append(f"{name}={value}")


__all__ = ["PlainToolbarSnapshot", "render_plain_toolbar"]
