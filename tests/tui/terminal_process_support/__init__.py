"""Cross-platform native terminal process drivers used only by tests."""

from .environment import terminal_test_environment
from .factory import selected_backend_name, spawn_terminal_process
from .protocol import TerminalProcessDiagnostics, TerminalProcessDriver

__all__ = [
    "TerminalProcessDiagnostics",
    "TerminalProcessDriver",
    "selected_backend_name",
    "spawn_terminal_process",
    "terminal_test_environment",
]
