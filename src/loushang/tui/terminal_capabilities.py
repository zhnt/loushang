from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

ImageProtocol = Literal["kitty", "iterm2", "none"]
KeyboardProtocolStrategy = Literal["kitty_then_modify_other_keys", "modify_other_keys", "legacy"]
MouseSelectionOwner = Literal["terminal", "application"]


@dataclass(frozen=True, slots=True)
class TerminalEnvironment:
    term: str = ""
    term_program: str = ""
    colorterm: str = ""
    inside_tmux: bool = False
    inside_screen: bool = False
    inside_ssh: bool = False
    is_windows: bool = False
    is_macos: bool = False
    is_linux: bool = False
    is_wsl: bool = False
    has_kitty_env: bool = False
    has_iterm_env: bool = False
    has_wezterm_env: bool = False
    has_ghostty_env: bool = False
    has_windows_terminal_env: bool = False
    termux_session: bool = False
    raw_env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TerminalRuntimeCapabilities:
    truecolor: bool = False
    hyperlinks: bool = False
    image_protocol: ImageProtocol = "none"
    keyboard_protocol_strategy: KeyboardProtocolStrategy = "legacy"
    query_cell_size: bool = False
    enable_bracketed_paste: bool = True
    enable_focus_events: bool = True
    enable_mouse: bool = False
    alternate_screen: bool = False
    tmux_passthrough: bool = False
    windows_vt_input: bool = False
    termux_session: bool = False
    apple_terminal_normalization: bool = False
    is_multiplexer: bool = False
    inside_ssh: bool = False
    capability_sources: tuple[str, ...] = ()
    mouse_selection_owner: MouseSelectionOwner = "terminal"

    @property
    def effective_mouse_selection_owner(self) -> MouseSelectionOwner:
        """Resolve the explicit policy while preserving the legacy mouse flag."""

        if self.enable_mouse:
            return "application"
        return self.mouse_selection_owner

    @property
    def application_mouse_tracking_enabled(self) -> bool:
        return self.effective_mouse_selection_owner == "application"


def terminal_environment_from_env(
    env: Mapping[str, str] | None = None,
    *,
    platform_name: str | None = None,
) -> TerminalEnvironment:
    values = dict(os.environ if env is None else env)
    platform = (platform_name or sys.platform).lower()
    term = values.get("TERM", "")
    term_program = values.get("TERM_PROGRAM", "")
    colorterm = values.get("COLORTERM", "")
    has_wezterm_env = bool(values.get("WEZTERM_PANE") or values.get("WEZTERM_EXECUTABLE") or _matches(term_program, "WezTerm"))
    has_ghostty_env = bool(values.get("GHOSTTY_RESOURCES_DIR") or _matches(term_program, "ghostty"))
    has_iterm_env = bool(values.get("ITERM_SESSION_ID") or term_program in {"iTerm.app", "iTerm2"})
    has_kitty_env = bool(values.get("KITTY_WINDOW_ID") or "kitty" in term.lower() or _matches(term_program, "kitty"))
    termux_session = bool(values.get("TERMUX_VERSION") or values.get("PREFIX", "").startswith("/data/data/com.termux/"))
    return TerminalEnvironment(
        term=term,
        term_program=term_program,
        colorterm=colorterm,
        inside_tmux=bool(values.get("TMUX") or term.lower().startswith("tmux")),
        inside_screen=bool(values.get("STY") or term.lower().startswith("screen")),
        inside_ssh=bool(values.get("SSH_TTY") or values.get("SSH_CONNECTION") or values.get("SSH_CLIENT")),
        is_windows=platform.startswith(("win32", "cygwin", "msys")),
        is_macos=platform == "darwin",
        is_linux=platform.startswith("linux"),
        is_wsl=bool(values.get("WSL_DISTRO_NAME") or values.get("WSL_INTEROP")),
        has_kitty_env=has_kitty_env,
        has_iterm_env=has_iterm_env,
        has_wezterm_env=has_wezterm_env,
        has_ghostty_env=has_ghostty_env,
        has_windows_terminal_env=bool(values.get("WT_SESSION")),
        termux_session=termux_session,
        raw_env=values,
    )


def detect_terminal_capabilities(environment: TerminalEnvironment | None = None) -> TerminalRuntimeCapabilities:
    env = environment or terminal_environment_from_env()
    sources: list[str] = []
    truecolor = _has_truecolor_hint(env)
    hyperlinks = False
    image_protocol: ImageProtocol = "none"
    query_cell_size = False
    keyboard_protocol_strategy: KeyboardProtocolStrategy = "kitty_then_modify_other_keys"
    apple_terminal_normalization = env.is_macos and _matches(env.term_program, "Apple_Terminal")
    is_multiplexer = env.inside_tmux or env.inside_screen
    tmux_passthrough = env.inside_tmux and _truthy_env(env.raw_env.get("LOUSHANG_TUI_TMUX_PASSTHROUGH", ""))

    if is_multiplexer:
        sources.append("multiplexer")
        if truecolor:
            sources.append("color:truecolor")
        if tmux_passthrough:
            forwarded_protocol = _forwarded_image_protocol(env)
            if forwarded_protocol is not None:
                image_protocol = forwarded_protocol
                truecolor = True
                hyperlinks = True
                query_cell_size = True
                sources.append("tmux-passthrough")
    elif env.has_iterm_env:
        image_protocol = "iterm2"
        truecolor = True
        hyperlinks = True
        query_cell_size = True
        sources.append("iterm2")
    elif env.has_kitty_env or env.has_ghostty_env or env.has_wezterm_env:
        image_protocol = "kitty"
        truecolor = True
        hyperlinks = True
        query_cell_size = True
        if env.has_kitty_env:
            sources.append("kitty")
        elif env.has_ghostty_env:
            sources.append("ghostty")
        else:
            sources.append("wezterm")
    elif _matches(env.term_program, "vscode"):
        truecolor = True
        hyperlinks = True
        sources.append("vscode")
    elif env.has_windows_terminal_env:
        truecolor = True
        sources.append("windows-terminal")
    elif truecolor:
        sources.append("color:truecolor")

    if env.termux_session:
        sources.append("termux")
    if apple_terminal_normalization:
        sources.append("apple-terminal")
    if env.inside_ssh:
        sources.append("ssh")
    if not is_multiplexer:
        sources.append(f"keyboard:{keyboard_protocol_strategy}")
    else:
        keyboard_protocol_strategy = "kitty_then_modify_other_keys"
        sources.append(f"keyboard:{keyboard_protocol_strategy}")

    return TerminalRuntimeCapabilities(
        truecolor=truecolor,
        hyperlinks=hyperlinks,
        image_protocol=image_protocol,
        keyboard_protocol_strategy=keyboard_protocol_strategy,
        query_cell_size=query_cell_size,
        enable_bracketed_paste=True,
        enable_focus_events=True,
        tmux_passthrough=tmux_passthrough and image_protocol != "none",
        windows_vt_input=env.is_windows,
        termux_session=env.termux_session,
        apple_terminal_normalization=apple_terminal_normalization,
        is_multiplexer=is_multiplexer,
        inside_ssh=env.inside_ssh,
        capability_sources=tuple(sources),
    )


def format_terminal_capability_diagnostics(
    environment: TerminalEnvironment | None = None,
    capabilities: TerminalRuntimeCapabilities | None = None,
) -> str:
    env = environment or terminal_environment_from_env()
    caps = capabilities or detect_terminal_capabilities(env)
    rows = (
        ("term", env.term or "<unset>"),
        ("terminal_program", env.term_program or "<unset>"),
        ("multiplexer", _format_bool(caps.is_multiplexer)),
        ("inside_ssh", _format_bool(caps.inside_ssh)),
        ("truecolor", _format_bool(caps.truecolor)),
        ("hyperlinks", _format_bool(caps.hyperlinks)),
        ("image_protocol", caps.image_protocol),
        ("keyboard_protocol_strategy", caps.keyboard_protocol_strategy),
        ("query_cell_size", _format_bool(caps.query_cell_size)),
        ("mouse_selection_owner", caps.effective_mouse_selection_owner),
        ("alternate_screen", _format_bool(caps.alternate_screen)),
        ("tmux_passthrough", _format_bool(caps.tmux_passthrough)),
        ("windows_vt_input", _format_bool(caps.windows_vt_input)),
        ("termux_session", _format_bool(caps.termux_session)),
        ("apple_terminal_normalization", _format_bool(caps.apple_terminal_normalization)),
        ("capability_sources", ", ".join(caps.capability_sources) if caps.capability_sources else "<none>"),
    )
    return "\n".join(f"{key}: {value}" for key, value in rows)


def _has_truecolor_hint(env: TerminalEnvironment) -> bool:
    return env.colorterm.lower() in {"truecolor", "24bit"} or env.has_windows_terminal_env


def _forwarded_image_protocol(env: TerminalEnvironment) -> ImageProtocol | None:
    if env.has_iterm_env:
        return "iterm2"
    if env.has_kitty_env or env.has_ghostty_env or env.has_wezterm_env:
        return "kitty"
    return None


def _truthy_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _matches(value: str, expected: str) -> bool:
    return value.lower() == expected.lower()


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


__all__ = [
    "ImageProtocol",
    "KeyboardProtocolStrategy",
    "MouseSelectionOwner",
    "TerminalEnvironment",
    "TerminalRuntimeCapabilities",
    "detect_terminal_capabilities",
    "format_terminal_capability_diagnostics",
    "terminal_environment_from_env",
]
