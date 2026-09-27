from __future__ import annotations

from types import SimpleNamespace

from loushang.tui.mouse_policy import (
    MouseEnvironment,
    probe_tmux_mouse,
    requested_mouse_policy,
    resolve_mouse_policy,
)


def test_auto_mouse_policy_preserves_selection_without_clipboard_or_tmux_forwarding() -> (
    None
):
    cases = (
        ("off", True, "terminal", "tmux_mouse_off"),
        ("unknown", True, "terminal", "tmux_mouse_unknown"),
        ("on", False, "terminal", "no_user_clipboard"),
        ("absent", False, "terminal", "no_user_clipboard"),
        ("on", True, "application", "interactive_copy_available"),
        ("absent", True, "application", "interactive_copy_available"),
    )
    for tmux_mouse, clipboard, owner, reason in cases:
        result = resolve_mouse_policy(
            "auto",
            MouseEnvironment(tmux_mouse=tmux_mouse, user_clipboard_available=clipboard),
        )
        assert (result.owner, result.reason) == (owner, reason)


def test_explicit_mouse_policy_overrides_environment() -> None:
    environment = MouseEnvironment(tmux_mouse="off", user_clipboard_available=False)
    assert resolve_mouse_policy("terminal", environment).owner == "terminal"
    assert resolve_mouse_policy("application", environment).owner == "application"
    assert (
        requested_mouse_policy({"LOUSHANG_TUI_MOUSE_POLICY": "application"})
        == "application"
    )
    assert requested_mouse_policy({"LOUSHANG_TUI_MOUSE_POLICY": "nonsense"}) == "auto"


def test_tmux_adapter_is_loaded_only_for_tmux_environment() -> None:
    loads: list[str] = []

    def loader(name: str) -> object:
        loads.append(name)
        return SimpleNamespace(probe=lambda _env: "off")

    assert probe_tmux_mouse({}, loader=loader) == "absent"
    assert loads == []
    assert probe_tmux_mouse({"TMUX": "/tmp/tmux"}, loader=loader) == "off"
    assert loads == ["loushang.tui.mouse_backends.tmux"]
