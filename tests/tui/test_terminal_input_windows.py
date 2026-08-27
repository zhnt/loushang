from __future__ import annotations

import asyncio
import sys
import threading
import time
from contextlib import suppress
from io import StringIO
from types import SimpleNamespace
from typing import Any

from loushang.tui.input import InputEvent, InputReader
from loushang.tui.terminal_backends.windows import WINDOWS_CONSOLE_INPUT
from loushang.tui.terminal_input import (
    TerminalInputMode,
    read_input_chunk,
    read_input_chunk_or_render_tick,
)


def test_terminal_input_mode_writes_control_modes_without_posix_modules(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    stdout = StringIO()

    with TerminalInputMode(stdin=_TtyInput(), stdout=stdout, keyboard_protocols=False):
        pass

    assert stdout.getvalue() == "\x1b[?2004h\x1b[?1004h\x1b[?2004l\x1b[?1004l"


def test_read_input_chunk_or_render_tick_waits_for_tty_input(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    _install_fake_console(monkeypatch, kbhit=lambda: False)

    result = asyncio.run(
        read_input_chunk_or_render_tick(
            _TtyInput(), runtime=_Runtime(), active_task=None, idle_wakeup_ms=1
        )
    )

    assert result is None


def test_read_input_chunk_reads_tty_key(monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    _install_fake_console(monkeypatch, chars=["x"])

    result = asyncio.run(read_input_chunk(_TtyInput()))

    assert result == "x"


def test_read_input_chunk_keeps_windows_focus_report_atomic(monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    _install_fake_console(monkeypatch, chars=["\x1b", "[", "I"])

    result = asyncio.run(read_input_chunk(_TtyInput()))

    assert result == "\x1b[I"
    assert InputReader().feed(result) == (
        InputEvent(kind="focus", focused=True, raw="\x1b[I"),
    )


def test_read_input_chunk_normalizes_native_windows_alt_v(monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    _install_fake_console(monkeypatch, chars=["\x00", "/"])

    result = asyncio.run(read_input_chunk(_TtyInput()))

    assert result == "\x1bv"
    assert InputReader().feed(result) == (
        InputEvent(kind="key", key="alt+v", raw="\x1bv"),
    )


def test_read_input_chunk_recovers_alt_v_when_vt_input_drops_modifier(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "loushang.tui.terminal_backends.windows._windows_pending_alt_modifier",
        lambda: True,
    )
    monkeypatch.setattr(
        "loushang.tui.terminal_backends.windows._windows_alt_pressed",
        lambda: False,
    )
    _install_fake_console(monkeypatch, chars=["v"])

    result = asyncio.run(read_input_chunk(_TtyInput()))

    assert result == "\x1bv"
    assert InputReader().feed(result) == (
        InputEvent(kind="key", key="alt+v", raw="\x1bv"),
    )


def test_read_input_chunk_does_not_duplicate_escape_for_legacy_alt_v(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "loushang.tui.terminal_backends.windows._windows_pending_alt_modifier",
        lambda: False,
    )
    monkeypatch.setattr(
        "loushang.tui.terminal_backends.windows._windows_alt_pressed",
        lambda: True,
    )
    _install_fake_console(monkeypatch, chars=["\x1b", "v"])

    result = asyncio.run(read_input_chunk(_TtyInput()))

    assert result == "\x1bv"
    assert InputReader().feed(result) == (
        InputEvent(kind="key", key="alt+v", raw="\x1bv"),
    )


def test_read_input_chunk_keeps_plain_v_without_alt_modifier(monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "loushang.tui.terminal_backends.windows._windows_alt_pressed",
        lambda: False,
    )
    _install_fake_console(monkeypatch, chars=["v"])

    result = asyncio.run(read_input_chunk(_TtyInput()))

    assert result == "v"
    assert InputReader().feed(result) == (InputEvent(kind="text", text="v"),)


def test_read_input_chunk_keeps_windows_bracketed_paste_atomic(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    sequence = "\x1b[200~hello\x1b[201~"
    _install_fake_console(monkeypatch, chars=list(sequence))

    result = asyncio.run(read_input_chunk(_TtyInput()))

    assert result == sequence
    assert InputReader().feed(result) == (InputEvent(kind="paste", text="hello"),)


def test_read_input_chunk_waits_for_fragmented_windows_focus_tail(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    pending = ["\x1b", "[", "I"]
    checks = 0

    def kbhit() -> bool:
        nonlocal checks
        checks += 1
        if checks == 2:
            return False
        return bool(pending)

    _install_fake_console(
        monkeypatch,
        kbhit=kbhit,
        getwch=lambda: pending.pop(0),
    )

    result = asyncio.run(read_input_chunk(_TtyInput()))

    assert result == "\x1b[I"


def test_read_input_chunk_combines_utf16_surrogate_pair(monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    _install_fake_console(monkeypatch, chars=["\ud83d", "\udc4b"])

    result = asyncio.run(read_input_chunk(_TtyInput()))

    assert result == "👋"
    assert result.encode("utf-8") == b"\xf0\x9f\x91\x8b"


def test_read_input_chunk_replaces_isolated_surrogates(monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    _install_fake_console(monkeypatch, chars=["\ud83d", "x", "\udc4b"])

    first = asyncio.run(read_input_chunk(_TtyInput()))
    second = asyncio.run(read_input_chunk(_TtyInput()))

    assert first == "�x"
    assert second == "�"
    assert (first + second).encode("utf-8") == "�x�".encode()


def test_blocking_key_read_does_not_block_render_wakeup(monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    def slow_getwch() -> str:
        time.sleep(0.05)
        return "x"

    _install_fake_console(monkeypatch, kbhit=lambda: True, getwch=slow_getwch)

    async def run() -> tuple[str | None, int]:
        runtime = _DeferredRuntime()
        render_wakeup = asyncio.Event()

        async def active() -> None:
            await asyncio.sleep(0.02)

        async def wake_later() -> None:
            await asyncio.sleep(0.001)
            render_wakeup.set()

        active_task = asyncio.create_task(active())
        wake_task = asyncio.create_task(wake_later())
        result = await read_input_chunk_or_render_tick(
            _TtyInput(),
            runtime=runtime,
            active_task=active_task,
            render_wakeup=render_wakeup,
        )
        await wake_task
        return result, runtime.rendered

    result, rendered = asyncio.run(run())

    assert result is None
    assert rendered >= 1


def test_canceled_key_read_is_reused_by_next_reader(monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    calls: list[str] = []
    started = threading.Event()
    kbhit_calls = 0

    def kbhit() -> bool:
        nonlocal kbhit_calls
        kbhit_calls += 1
        return kbhit_calls == 1

    def slow_getwch() -> str:
        calls.append("start")
        started.set()
        time.sleep(0.02)
        calls.append("end")
        return "h"

    _install_fake_console(monkeypatch, kbhit=kbhit, getwch=slow_getwch)

    async def run() -> str:
        first = asyncio.create_task(read_input_chunk(_TtyInput()))
        while not started.is_set():
            await asyncio.sleep(0.001)
        first.cancel()
        with suppress(asyncio.CancelledError):
            await first
        while calls != ["start", "end"]:
            await asyncio.sleep(0.001)
        return await asyncio.wait_for(read_input_chunk(_TtyInput()), timeout=0.1)

    result = asyncio.run(run())

    assert result == "h"
    assert calls == ["start", "end"]
    assert kbhit_calls == 1


class _Runtime:
    rendered = 0

    def request_next_animation_frame(self):
        return _DelayedDecision()

    def render_now(self) -> None:
        self.rendered += 1


class _DeferredRuntime:
    def __init__(self) -> None:
        self.rendered = 0
        self.decisions = 0

    def request_next_animation_frame(self):
        self.decisions += 1
        if self.decisions == 1 or self.rendered > 0:
            return _SlowDecision()
        return _ImmediateDecision()

    def render_now(self) -> None:
        self.rendered += 1


class _DelayedDecision:
    render_now = False
    delay_ms = 0


class _SlowDecision:
    render_now = False
    delay_ms = 1_000


class _ImmediateDecision:
    render_now = True
    delay_ms = 0


class _TtyInput:
    def fileno(self) -> int:
        return 42

    def isatty(self) -> bool:
        return True


def _install_fake_console(
    monkeypatch: Any,
    *,
    chars: list[str] | None = None,
    kbhit: object | None = None,
    getwch: object | None = None,
) -> None:
    pending = list(chars or ())
    console = SimpleNamespace(
        kbhit=kbhit or (lambda: bool(pending)),
        getwch=getwch or (lambda: pending.pop(0)),
    )
    monkeypatch.setattr(WINDOWS_CONSOLE_INPUT, "module_loader", lambda: console)
