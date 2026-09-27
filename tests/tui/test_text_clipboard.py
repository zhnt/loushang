from __future__ import annotations

import asyncio
from types import SimpleNamespace

from loushang.tui.text_clipboard import (
    CommandClipboardWriter,
    Osc52ClipboardWriter,
    select_text_clipboard_writer,
    user_clipboard_route_available,
)


def test_clipboard_route_loads_only_selected_host_adapter() -> None:
    loads: list[str] = []

    def loader(name: str) -> object:
        loads.append(name)
        return SimpleNamespace(candidates=lambda _env: (("copy-command", ()),))

    writer = select_text_clipboard_writer(
        {},
        platform="darwin",
        loader=loader,
        which=lambda command: (
            "/bin/copy-command" if command == "copy-command" else None
        ),
    )

    assert isinstance(writer, CommandClipboardWriter)
    assert loads == ["loushang.tui.clipboard_backends.darwin"]


def test_platform_adapters_are_lazy_and_headless_linux_retains_terminal_selection() -> (
    None
):
    assert (
        select_text_clipboard_writer(
            {}, platform="linux", which=lambda _command: "/bin/command"
        )
        is None
    )
    for platform, env, suffix in (
        ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, "linux"),
        ("darwin", {}, "darwin"),
        ("win32", {}, "windows"),
        ("linux", {"WSL_DISTRO_NAME": "Ubuntu"}, "wsl"),
        ("linux", {"TERMUX_VERSION": "1"}, "termux"),
    ):
        loads: list[str] = []

        def loader(name: str, captured: list[str] = loads) -> object:
            captured.append(name)
            return SimpleNamespace(candidates=lambda _env: (("copy", ()),))

        assert (
            select_text_clipboard_writer(
                env,
                platform=platform,
                loader=loader,
                which=lambda _command: "/bin/copy",
            )
            is not None
        )
        assert loads == [f"loushang.tui.clipboard_backends.{suffix}"]


def test_ssh_never_uses_a_remote_host_clipboard_command_as_user_copy() -> None:
    loads: list[str] = []

    def loader(name: str) -> object:
        loads.append(name)
        raise AssertionError("remote host adapter must not be loaded")

    assert (
        select_text_clipboard_writer({"SSH_TTY": "/dev/pts/1"}, loader=loader) is None
    )
    assert loads == []

    writer = select_text_clipboard_writer(
        {"SSH_TTY": "/dev/pts/1", "LOUSHANG_TUI_OSC52": "1"},
        loader=loader,
        write_control=lambda _sequence: True,
    )
    assert isinstance(writer, Osc52ClipboardWriter)
    assert loads == []
    assert user_clipboard_route_available(
        None, {"SSH_TTY": "/dev/pts/1", "LOUSHANG_TUI_OSC52": "1"}
    )


def test_local_tmux_can_opt_into_osc52_without_desktop_clipboard() -> None:
    writer = select_text_clipboard_writer(
        {"TMUX": "/tmp/tmux", "LOUSHANG_TUI_OSC52": "1"},
        platform="linux",
        write_control=lambda _sequence: True,
        which=lambda _command: None,
    )
    assert isinstance(writer, Osc52ClipboardWriter)


def test_windows_clipboard_adapters_select_unicode_payload_encoding() -> None:
    for platform, env in (("win32", {}), ("linux", {"WSL_DISTRO_NAME": "Ubuntu"})):
        writer = select_text_clipboard_writer(
            env, platform=platform, which=lambda command: command
        )
        assert isinstance(writer, CommandClipboardWriter)
        assert writer.encoding == "utf-16le"
        assert "é中文😀".encode(writer.encoding) == b"\xe9\x00-N\x87e=\xd8\x00\xde"


def test_osc52_writer_reports_unacknowledged_delivery_and_bounds_payload() -> None:
    sequences: list[str] = []
    writer = Osc52ClipboardWriter(
        lambda sequence: sequences.append(sequence) or True, max_bytes=5
    )

    assert asyncio.run(writer.write("hello")).outcome == "sent"
    assert sequences == ["\x1b]52;c;aGVsbG8=\x07"]
    assert asyncio.run(writer.write("too long")).outcome == "failed"
    assert len(sequences) == 1
