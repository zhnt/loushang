from __future__ import annotations

from types import SimpleNamespace

from loushang.tui.mouse_policy import (
    MouseEnvironment,
    probe_tmux_mouse,
    requested_mouse_policy,
    resolve_mouse_policy,
)
from loushang.tui.text_clipboard import (
    select_text_clipboard_writer,
    user_clipboard_route_available,
)


def test_auto_mouse_policy_enables_clicks_when_mouse_reports_can_arrive() -> (
    None
):
    cases = (
        ("off", True, "terminal", "tmux_mouse_off"),
        ("unknown", True, "terminal", "tmux_mouse_unknown"),
        ("on", False, "application", "interactive_clicks_no_clipboard"),
        ("absent", False, "application", "interactive_clicks_no_clipboard"),
        ("on", True, "application", "interactive_copy_available"),
        ("absent", True, "application", "interactive_copy_available"),
    )
    for tmux_mouse, clipboard, owner, reason in cases:
        result = resolve_mouse_policy(
            "auto",
            MouseEnvironment(tmux_mouse=tmux_mouse, user_clipboard_available=clipboard),
        )
        assert (result.owner, result.reason) == (owner, reason)


def test_direct_ssh_auto_policy_enables_clicks_without_remote_clipboard() -> None:
    env = {"SSH_CONNECTION": "client 1234 server 22", "TERM": "xterm-256color"}
    writer = select_text_clipboard_writer(env, platform="linux", which=lambda _: None)
    assert writer is None
    result = resolve_mouse_policy(
        requested_mouse_policy(env),
        MouseEnvironment(
            tmux_mouse=probe_tmux_mouse(env),
            user_clipboard_available=user_clipboard_route_available(writer, env),
        ),
    )
    assert (result.owner, result.reason) == (
        "application",
        "interactive_clicks_no_clipboard",
    )


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
