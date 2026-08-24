from __future__ import annotations

from loushang.tui.terminal_capabilities import (
    TerminalEnvironment,
    TerminalRuntimeCapabilities,
    detect_terminal_capabilities,
    format_terminal_capability_diagnostics,
    terminal_environment_from_env,
)


def test_terminal_environment_normalizes_common_hints() -> None:
    env = terminal_environment_from_env(
        {
            "TERM": "xterm-kitty",
            "TERM_PROGRAM": "kitty",
            "COLORTERM": "truecolor",
            "KITTY_WINDOW_ID": "42",
            "SSH_CONNECTION": "client server",
        },
        platform_name="linux",
    )

    assert env.term == "xterm-kitty"
    assert env.term_program == "kitty"
    assert env.colorterm == "truecolor"
    assert env.has_kitty_env
    assert env.inside_ssh
    assert env.is_linux
    assert not env.is_windows


def test_detects_kitty_capabilities_from_term() -> None:
    capabilities = _detect({"TERM": "xterm-kitty"})

    assert capabilities.image_protocol == "kitty"
    assert capabilities.truecolor
    assert capabilities.hyperlinks
    assert capabilities.keyboard_protocol_strategy == "kitty_then_modify_other_keys"
    assert capabilities.query_cell_size
    assert "kitty" in capabilities.capability_sources


def test_detects_kitty_capabilities_from_window_id() -> None:
    capabilities = _detect({"TERM": "xterm-256color", "KITTY_WINDOW_ID": "1"})

    assert capabilities.image_protocol == "kitty"
    assert capabilities.truecolor
    assert capabilities.hyperlinks


def test_detects_ghostty_and_wezterm_as_kitty_image_terminals() -> None:
    ghostty = _detect({"TERM": "xterm-256color", "GHOSTTY_RESOURCES_DIR": "/app/ghostty"})
    wezterm = _detect({"TERM": "xterm-256color", "WEZTERM_PANE": "12"})

    assert ghostty.image_protocol == "kitty"
    assert ghostty.truecolor
    assert wezterm.image_protocol == "kitty"
    assert wezterm.hyperlinks


def test_detects_iterm2_capabilities() -> None:
    capabilities = _detect({"TERM_PROGRAM": "iTerm.app", "ITERM_SESSION_ID": "abc"})

    assert capabilities.image_protocol == "iterm2"
    assert capabilities.truecolor
    assert capabilities.hyperlinks
    assert capabilities.query_cell_size


def test_detects_vscode_without_images() -> None:
    capabilities = _detect({"TERM_PROGRAM": "vscode"})

    assert capabilities.image_protocol == "none"
    assert capabilities.truecolor
    assert capabilities.hyperlinks
    assert not capabilities.query_cell_size


def test_detects_windows_terminal_truecolor_without_images() -> None:
    capabilities = _detect({"WT_SESSION": "abc"}, platform_name="win32")

    assert capabilities.image_protocol == "none"
    assert capabilities.truecolor
    assert not capabilities.hyperlinks
    assert capabilities.windows_vt_input


def test_windows_console_attempts_input_mode_without_windows_terminal_env() -> None:
    capabilities = _detect({}, platform_name="win32")

    assert capabilities.image_protocol == "none"
    assert capabilities.windows_vt_input


def test_tmux_and_screen_disable_images_and_hyperlinks() -> None:
    tmux = _detect({"TERM": "xterm-kitty", "TMUX": "/tmp/tmux.sock", "COLORTERM": "truecolor"})
    screen = _detect({"TERM": "screen-256color", "STY": "123.screen"})

    assert tmux.is_multiplexer
    assert tmux.image_protocol == "none"
    assert not tmux.hyperlinks
    assert tmux.truecolor
    assert screen.is_multiplexer
    assert screen.image_protocol == "none"
    assert not screen.hyperlinks


def test_tmux_passthrough_opt_in_restores_forwarded_image_and_hyperlink_capabilities() -> None:
    capabilities = _detect(
        {
            "TERM": "xterm-kitty",
            "TMUX": "/tmp/tmux.sock",
            "COLORTERM": "truecolor",
            "LOUSHANG_TUI_TMUX_PASSTHROUGH": "1",
        }
    )

    assert capabilities.is_multiplexer
    assert capabilities.tmux_passthrough
    assert capabilities.image_protocol == "kitty"
    assert capabilities.hyperlinks
    assert capabilities.query_cell_size
    assert "tmux-passthrough" in capabilities.capability_sources


def test_ssh_keeps_forwarded_terminal_hints_visible_but_does_not_disable_them() -> None:
    capabilities = _detect({"TERM": "xterm-kitty", "SSH_TTY": "/dev/pts/1"})

    assert capabilities.inside_ssh
    assert capabilities.image_protocol == "kitty"
    assert capabilities.hyperlinks


def test_unknown_terminal_is_conservative() -> None:
    capabilities = _detect({"TERM": "xterm-256color"})

    assert capabilities == TerminalRuntimeCapabilities(
        truecolor=False,
        hyperlinks=False,
        image_protocol="none",
        keyboard_protocol_strategy="kitty_then_modify_other_keys",
        query_cell_size=False,
        enable_bracketed_paste=True,
        enable_focus_events=True,
        capability_sources=("keyboard:kitty_then_modify_other_keys",),
    )
    assert capabilities.effective_mouse_selection_owner == "terminal"
    assert capabilities.application_mouse_tracking_enabled is False


def test_legacy_mouse_flag_upgrades_selection_ownership_to_application() -> None:
    capabilities = TerminalRuntimeCapabilities(
        enable_mouse=True,
        mouse_selection_owner="terminal",
    )

    assert capabilities.effective_mouse_selection_owner == "application"
    assert capabilities.application_mouse_tracking_enabled is True


def test_colorterm_truecolor_enables_truecolor_for_unknown_terminal() -> None:
    capabilities = _detect({"TERM": "xterm-256color", "COLORTERM": "truecolor"})

    assert capabilities.truecolor
    assert capabilities.image_protocol == "none"
    assert not capabilities.hyperlinks


def test_termux_hint_is_reported_without_special_policy() -> None:
    capabilities = _detect({"TERMUX_VERSION": "0.118"})

    assert capabilities.termux_session
    assert "termux" in capabilities.capability_sources


def test_apple_terminal_shift_enter_normalization_requires_macos() -> None:
    linux = _detect({"TERM_PROGRAM": "Apple_Terminal"}, platform_name="linux")
    macos = _detect({"TERM_PROGRAM": "Apple_Terminal"}, platform_name="darwin")

    assert not linux.apple_terminal_normalization
    assert macos.apple_terminal_normalization
    assert "apple-terminal" in macos.capability_sources


def test_terminal_capability_diagnostics_include_runtime_fields() -> None:
    environment = terminal_environment_from_env(
        {
            "TERM": "xterm-kitty",
            "TERM_PROGRAM": "kitty",
            "KITTY_WINDOW_ID": "1",
            "SSH_TTY": "/dev/pts/1",
        },
        platform_name="linux",
    )
    capabilities = detect_terminal_capabilities(environment)

    diagnostics = format_terminal_capability_diagnostics(environment, capabilities)

    assert "terminal_program: kitty" in diagnostics
    assert "term: xterm-kitty" in diagnostics
    assert "multiplexer: false" in diagnostics
    assert "inside_ssh: true" in diagnostics
    assert "truecolor: true" in diagnostics
    assert "hyperlinks: true" in diagnostics
    assert "image_protocol: kitty" in diagnostics
    assert "keyboard_protocol_strategy: kitty_then_modify_other_keys" in diagnostics
    assert "mouse_selection_owner: terminal" in diagnostics
    assert "alternate_screen: false" in diagnostics
    assert "tmux_passthrough: false" in diagnostics
    assert "windows_vt_input: false" in diagnostics
    assert "termux_session: false" in diagnostics
    assert "apple_terminal_normalization: false" in diagnostics
    assert "capability_sources: kitty, ssh, keyboard:kitty_then_modify_other_keys" in diagnostics


def _detect(env: dict[str, str], *, platform_name: str = "linux") -> TerminalRuntimeCapabilities:
    terminal_env = terminal_environment_from_env(env, platform_name=platform_name)
    assert isinstance(terminal_env, TerminalEnvironment)
    return detect_terminal_capabilities(terminal_env)
