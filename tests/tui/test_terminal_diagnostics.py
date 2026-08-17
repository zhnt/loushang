from __future__ import annotations

from types import SimpleNamespace

from loushang.tui.terminal_capabilities import (
    TerminalEnvironment,
    TerminalRuntimeCapabilities,
)
from loushang.tui.terminal_diagnostics import format_terminal_diagnostics


def test_format_terminal_diagnostics_preserves_capability_and_runtime_output() -> None:
    environment = TerminalEnvironment(
        term="xterm-kitty",
        term_program="kitty",
        inside_ssh=True,
    )
    capabilities = TerminalRuntimeCapabilities(
        truecolor=True,
        hyperlinks=True,
        image_protocol="kitty",
        keyboard_protocol_strategy="kitty_then_modify_other_keys",
        query_cell_size=True,
        alternate_screen=True,
        inside_ssh=True,
        capability_sources=("kitty", "ssh"),
    )
    runtime_diagnostics = SimpleNamespace(
        keyboard_protocol_state="kitty",
        mouse_mode_active=True,
        cell_size=SimpleNamespace(width_px=9, height_px=18),
        image_protocol="kitty",
        alternate_screen=True,
        tmux_passthrough=False,
        windows_vt_input=False,
        windows_vt_output=True,
        windows_console_mode_active=False,
        windows_output_mode_active=True,
        termux_session=False,
        is_multiplexer=False,
        inside_ssh=True,
    )
    context = SimpleNamespace(
        environment=environment,
        capabilities=capabilities,
        diagnostics=lambda: runtime_diagnostics,
    )

    assert format_terminal_diagnostics(context) == (
        "term: xterm-kitty\n"
        "terminal_program: kitty\n"
        "multiplexer: false\n"
        "inside_ssh: true\n"
        "truecolor: true\n"
        "hyperlinks: true\n"
        "image_protocol: kitty\n"
        "keyboard_protocol_strategy: kitty_then_modify_other_keys\n"
        "query_cell_size: true\n"
        "alternate_screen: true\n"
        "tmux_passthrough: false\n"
        "windows_vt_input: false\n"
        "termux_session: false\n"
        "apple_terminal_normalization: false\n"
        "capability_sources: kitty, ssh\n"
        "\n"
        "keyboard_protocol_state: kitty\n"
        "mouse_mode_active: true\n"
        "cell_size: 9x18\n"
        "runtime_image_protocol: kitty\n"
        "alternate_screen_active: true\n"
        "tmux_passthrough_active: false\n"
        "windows_vt_input_active: false\n"
        "windows_vt_output_active: true\n"
        "windows_console_mode_active: false\n"
        "windows_output_mode_active: true\n"
        "termux_session_active: false\n"
        "multiplexer_active: false\n"
        "ssh_active: true"
    )


def test_format_terminal_diagnostics_preserves_unavailable_fallback() -> None:
    assert (
        format_terminal_diagnostics(object()) == "Terminal diagnostics are unavailable."
    )


def test_format_terminal_diagnostics_preserves_unknown_runtime_values() -> None:
    context = SimpleNamespace(diagnostics=lambda: object())

    assert format_terminal_diagnostics(context) == (
        "keyboard_protocol_state: <unknown>\n"
        "mouse_mode_active: <unknown>\n"
        "cell_size: <unknown>\n"
        "runtime_image_protocol: <unknown>\n"
        "alternate_screen_active: <unknown>\n"
        "tmux_passthrough_active: <unknown>\n"
        "windows_vt_input_active: <unknown>\n"
        "windows_vt_output_active: <unknown>\n"
        "windows_console_mode_active: <unknown>\n"
        "windows_output_mode_active: <unknown>\n"
        "termux_session_active: <unknown>\n"
        "multiplexer_active: <unknown>\n"
        "ssh_active: <unknown>"
    )
