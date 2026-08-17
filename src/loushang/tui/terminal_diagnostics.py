from __future__ import annotations

from loushang.tui.terminal_capabilities import format_terminal_capability_diagnostics

__all__ = ["format_terminal_diagnostics"]


def format_terminal_diagnostics(terminal_context: object) -> str:
    """Format capability and live runtime diagnostics for a terminal context."""
    sections: list[str] = []
    environment = getattr(terminal_context, "environment", None)
    capabilities = getattr(terminal_context, "capabilities", None)
    if environment is not None or capabilities is not None:
        sections.append(
            format_terminal_capability_diagnostics(environment, capabilities)
        )
    diagnostics_getter = getattr(terminal_context, "diagnostics", None)
    if callable(diagnostics_getter):
        diagnostics = diagnostics_getter()
        sections.append(
            "\n".join(
                (
                    f"keyboard_protocol_state: {_diagnostic_value(diagnostics, 'keyboard_protocol_state')}",
                    f"mouse_mode_active: {_format_bool(_diagnostic_value(diagnostics, 'mouse_mode_active'))}",
                    f"cell_size: {_format_cell_size(_diagnostic_value(diagnostics, 'cell_size'))}",
                    f"runtime_image_protocol: {_diagnostic_value(diagnostics, 'image_protocol')}",
                    f"alternate_screen_active: {_format_bool(_diagnostic_value(diagnostics, 'alternate_screen'))}",
                    f"tmux_passthrough_active: {_format_bool(_diagnostic_value(diagnostics, 'tmux_passthrough'))}",
                    f"windows_vt_input_active: {_format_bool(_diagnostic_value(diagnostics, 'windows_vt_input'))}",
                    f"windows_vt_output_active: {_format_bool(_diagnostic_value(diagnostics, 'windows_vt_output'))}",
                    f"windows_console_mode_active: {_format_bool(_diagnostic_value(diagnostics, 'windows_console_mode_active'))}",
                    f"windows_output_mode_active: {_format_bool(_diagnostic_value(diagnostics, 'windows_output_mode_active'))}",
                    f"termux_session_active: {_format_bool(_diagnostic_value(diagnostics, 'termux_session'))}",
                    f"multiplexer_active: {_format_bool(_diagnostic_value(diagnostics, 'is_multiplexer'))}",
                    f"ssh_active: {_format_bool(_diagnostic_value(diagnostics, 'inside_ssh'))}",
                )
            )
        )
    return (
        "\n\n".join(section for section in sections if section)
        or "Terminal diagnostics are unavailable."
    )


def _diagnostic_value(diagnostics: object, name: str) -> object:
    return getattr(diagnostics, name, "<unknown>")


def _format_bool(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _format_cell_size(value: object) -> str:
    width = getattr(value, "width_px", None)
    height = getattr(value, "height_px", None)
    if isinstance(width, int) and isinstance(height, int):
        return f"{width}x{height}"
    return "<unknown>"
