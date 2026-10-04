"""Linux desktop clipboard commands."""

from __future__ import annotations

from collections.abc import Mapping


def candidates(env: Mapping[str, str]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not (env.get("WAYLAND_DISPLAY") or env.get("DISPLAY")):
        return ()
    wayland = bool(
        env.get("WAYLAND_DISPLAY") or env.get("XDG_SESSION_TYPE") == "wayland"
    )
    commands = (
        ("wl-copy", ()),
        ("xclip", ("-selection", "clipboard")),
        ("xsel", ("--clipboard", "--input")),
    )
    return commands if wayland else (*commands[1:], commands[0])
