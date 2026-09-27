"""Resolve mouse ownership from product preference and terminal environment."""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from loushang.tui.terminal_capabilities import MouseSelectionOwner

MousePolicy = Literal["auto", "terminal", "application"]
TmuxMouseState = Literal["absent", "on", "off", "unknown"]


def requested_mouse_policy(env: Mapping[str, str]) -> MousePolicy:
    value = env.get("LOUSHANG_TUI_MOUSE_POLICY", "auto").lower()
    return value if value in {"auto", "terminal", "application"} else "auto"  # type: ignore[return-value]


class TmuxMouseProbe(Protocol):
    def __call__(self, env: Mapping[str, str]) -> TmuxMouseState: ...


@dataclass(frozen=True, slots=True)
class MouseEnvironment:
    tmux_mouse: TmuxMouseState
    user_clipboard_available: bool


@dataclass(frozen=True, slots=True)
class MousePolicyResolution:
    requested: MousePolicy
    owner: MouseSelectionOwner
    reason: str
    tmux_mouse: TmuxMouseState


def probe_tmux_mouse(
    env: Mapping[str, str] | None = None,
    *,
    loader: Callable[[str], object] = importlib.import_module,
) -> TmuxMouseState:
    values = os.environ if env is None else env
    if not values.get("TMUX") and not values.get("TMUX_PANE"):
        return "absent"
    adapter = loader("loushang.tui.mouse_backends.tmux")
    return adapter.probe(values)  # type: ignore[attr-defined, no-any-return]


def resolve_mouse_policy(
    requested: MousePolicy,
    environment: MouseEnvironment,
) -> MousePolicyResolution:
    tmux_mouse = environment.tmux_mouse
    if requested == "terminal":
        return MousePolicyResolution(
            requested, "terminal", "terminal_requested", tmux_mouse
        )
    if requested == "application":
        return MousePolicyResolution(
            requested, "application", "application_requested", tmux_mouse
        )
    if tmux_mouse == "off":
        return MousePolicyResolution(
            requested, "terminal", "tmux_mouse_off", tmux_mouse
        )
    if tmux_mouse == "unknown":
        return MousePolicyResolution(
            requested, "terminal", "tmux_mouse_unknown", tmux_mouse
        )
    if not environment.user_clipboard_available:
        return MousePolicyResolution(
            requested, "terminal", "no_user_clipboard", tmux_mouse
        )
    return MousePolicyResolution(
        requested, "application", "interactive_copy_available", tmux_mouse
    )


__all__ = [
    "MouseEnvironment",
    "MousePolicy",
    "MousePolicyResolution",
    "TmuxMouseProbe",
    "TmuxMouseState",
    "probe_tmux_mouse",
    "requested_mouse_policy",
    "resolve_mouse_policy",
]
