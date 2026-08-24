from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import StringIO
from typing import Any

import pytest

from loushang.tui.input import (
    BRACKETED_PASTE_END,
    BRACKETED_PASTE_START,
    InputEvent,
    InputReader,
)
from loushang.tui.terminal_input import (
    TerminalInputMode,
    drain_input,
    read_input_chunk,
    read_input_chunk_or_render_tick,
)


def test_terminal_input_mode_does_not_write_modes_for_non_tty_streams() -> None:
    stdout = StringIO()

    with TerminalInputMode(stdin=StringIO(), stdout=stdout):
        pass

    assert stdout.getvalue() == ""


def test_terminal_input_mode_holds_native_lease_until_protocol_cleanup(
    monkeypatch: Any,
) -> None:
    lease = _ModeLease()
    factory = _ModeFactory(lease)
    stdout = StringIO()
    monkeypatch.setattr(
        "loushang.tui.terminal_input.native_terminal_mode_factory",
        lambda _platform: factory,
    )
    monkeypatch.setattr(
        "loushang.tui.terminal_input.drain_input", lambda *args, **kwargs: ""
    )

    with TerminalInputMode(
        stdin=_TtyInput(), stdout=stdout, keyboard_protocols=False
    ):
        assert lease.restore_calls == 0

    assert factory.open_calls == 1
    assert lease.restore_calls == 1
    assert stdout.getvalue() == "\x1b[?2004h\x1b[?1004h\x1b[?2004l\x1b[?1004l"


def test_terminal_input_mode_restores_native_lease_when_protocol_startup_fails(
    monkeypatch: Any,
) -> None:
    lease = _ModeLease()
    monkeypatch.setattr(
        "loushang.tui.terminal_input.native_terminal_mode_factory",
        lambda _platform: _ModeFactory(lease),
    )

    with pytest.raises(RuntimeError, match="write failed"):
        TerminalInputMode(stdin=_TtyInput(), stdout=_FailingOutput()).__enter__()

    assert lease.restore_calls == 1


def test_read_input_chunk_or_render_tick_reads_raw_stringio_escape_without_tail_joining() -> (
    None
):
    runtime = _Runtime()

    result = asyncio.run(
        read_input_chunk_or_render_tick(
            StringIO("\x1b\r"), runtime=runtime, active_task=None
        )
    )

    assert result == "\x1b"
    assert runtime.rendered == 0


def test_read_input_chunk_reads_one_stringio_escape_byte_without_tail_joining() -> None:
    stdin = StringIO("\x1b[A")

    first = asyncio.run(read_input_chunk(stdin))
    second = asyncio.run(read_input_chunk(stdin))

    assert first == "\x1b"
    assert second == "["


def test_read_input_chunk_or_render_tick_wakes_for_deferred_render_request() -> None:
    async def run() -> tuple[str | None, int, int]:
        runtime = _DeferredRuntime()
        render_wakeup = asyncio.Event()
        release_input = asyncio.Event()

        async def read_after_render(_stdin: object) -> str:
            await release_input.wait()
            return ""

        async def wake_later() -> None:
            render_wakeup.set()
            while runtime.rendered == 0:
                await asyncio.sleep(0)
            release_input.set()

        wake_task = asyncio.create_task(wake_later())
        result = await read_input_chunk_or_render_tick(
            StringIO(""),
            runtime=runtime,
            active_task=None,
            input_chunk_reader=read_after_render,
            render_wakeup=render_wakeup,
        )
        await wake_task
        return result, runtime.rendered, runtime.decisions

    result, rendered, decisions = asyncio.run(run())

    assert result == ""
    assert rendered == 1
    assert decisions >= 2


def test_read_input_chunk_or_render_tick_wakes_for_terminal_runtime_deadline() -> None:
    async def run() -> tuple[str | None, int]:
        runtime = _Runtime()
        result = await read_input_chunk_or_render_tick(
            StringIO(""),
            runtime=runtime,
            active_task=None,
            input_chunk_reader=_DelayedInputReader(block_seconds=0.01),
            idle_wakeup_ms=1,
        )
        return result, runtime.rendered

    result, rendered = asyncio.run(run())

    assert result is None
    assert rendered == 0


def test_drain_input_consumes_buffered_stringio_text() -> None:
    stdin = StringIO("leftover")

    drained = drain_input(stdin)

    assert drained == "leftover"
    assert stdin.read() == ""


def test_input_batch_routes_kitty_protocol_response_as_control_event() -> None:
    batch = InputReader().feed_batch("\x1b[?7u")

    assert batch.app_events == ()
    assert len(batch.control_events) == 1
    assert batch.control_events[0].kind == "signal"
    assert batch.control_events[0].signal == "kitty_protocol"
    assert batch.control_events[0].text == "7"
    assert not batch.has_pending


def test_input_batch_routes_cell_size_response_as_control_event() -> None:
    batch = InputReader().feed_batch("\x1b[6;18;9t")

    assert batch.app_events == ()
    assert len(batch.control_events) == 1
    assert batch.control_events[0].signal == "cell_size"
    assert batch.control_events[0].text == "18;9"


def test_input_batch_routes_arrow_as_app_event() -> None:
    batch = InputReader().feed_batch("\x1b[A")

    assert batch.control_events == ()
    assert len(batch.app_events) == 1
    assert batch.app_events[0].kind == "key"
    assert batch.app_events[0].key == "up"


def test_input_batch_routes_alt_angle_as_app_key_events() -> None:
    batch = InputReader().feed_batch("\x1b<\x1b>")

    assert batch.control_events == ()
    assert batch.app_events == (
        InputEvent(kind="key", key="alt+<", raw="\x1b<"),
        InputEvent(kind="key", key="alt+>", raw="\x1b>"),
    )


def test_input_batch_routes_esc_prefixed_arrows_as_alt_arrows() -> None:
    batch = InputReader().feed_batch("\x1b\x1b[A\x1b\x1b[B\x1b\x1b[C\x1b\x1b[D")

    assert batch.control_events == ()
    assert batch.app_events == (
        InputEvent(kind="key", key="alt+up", raw="\x1b\x1b[A"),
        InputEvent(kind="key", key="alt+down", raw="\x1b\x1b[B"),
        InputEvent(kind="key", key="alt+right", raw="\x1b\x1b[C"),
        InputEvent(kind="key", key="alt+left", raw="\x1b\x1b[D"),
    )


def test_input_batch_normalizes_kitty_keypad_digits_symbols_and_navigation() -> None:
    batch = InputReader().feed_batch(
        "\x1b[57399u"
        "\x1b[57400u"
        "\x1b[57409u"
        "\x1b[57410u"
        "\x1b[57413u"
        "\x1b[57416u"
        "\x1b[57417u"
        "\x1b[57419u"
        "\x1b[57424u"
        "\x1b[57426u"
    )

    assert batch.control_events == ()
    assert batch.app_events == (
        InputEvent(kind="text", text="01./+,"),
        InputEvent(kind="key", key="left", raw="\x1b[57417u"),
        InputEvent(kind="key", key="up", raw="\x1b[57419u"),
        InputEvent(kind="key", key="end", raw="\x1b[57424u"),
        InputEvent(kind="key", key="delete", raw="\x1b[57426u"),
    )


def test_input_batch_routes_legacy_function_keys_and_clear() -> None:
    batch = InputReader().feed_batch("\x1bOP\x1b[15~\x1b[24~\x1b[E")

    assert batch.control_events == ()
    assert batch.app_events == (
        InputEvent(kind="key", key="f1", raw="\x1bOP"),
        InputEvent(kind="key", key="f5", raw="\x1b[15~"),
        InputEvent(kind="key", key="f12", raw="\x1b[24~"),
        InputEvent(kind="key", key="clear", raw="\x1b[E"),
    )


def test_input_batch_routes_windows_terminal_ctrl_backspace(monkeypatch: Any) -> None:
    monkeypatch.setenv("WT_SESSION", "abc")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.delenv("SSH_CLIENT", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)

    batch = InputReader().feed_batch("\x08")

    assert batch.control_events == ()
    assert batch.app_events == (
        InputEvent(kind="key", key="ctrl+backspace", raw="\x08"),
    )


def test_input_batch_uses_kitty_base_layout_for_non_latin_shortcuts() -> None:
    batch = InputReader().feed_batch("\x1b[1089::99;5u")

    assert batch.control_events == ()
    assert batch.app_events == (
        InputEvent(kind="key", key="ctrl+c", raw="\x1b[1089::99;5u"),
    )


def test_input_batch_routes_alt_control_and_alt_backspace_legacy_sequences() -> None:
    batch = InputReader().feed_batch("\x1b\b\x1b\x03\x1b\x1d\x1b\x1f")

    assert batch.control_events == ()
    assert batch.app_events == (
        InputEvent(kind="key", key="alt+backspace", raw="\x1b\b"),
        InputEvent(kind="key", key="ctrl+alt+c", raw="\x1b\x03"),
        InputEvent(kind="key", key="ctrl+alt+]", raw="\x1b\x1d"),
        InputEvent(kind="key", key="ctrl+alt+-", raw="\x1b\x1f"),
    )


def test_input_batch_keeps_split_kitty_response_pending_until_complete() -> None:
    reader = InputReader()

    first = reader.feed_batch("\x1b")
    second = reader.feed_batch("[?7u")

    assert first.app_events == ()
    assert first.control_events == ()
    assert first.has_pending
    assert second.app_events == ()
    assert len(second.control_events) == 1
    assert second.control_events[0].signal == "kitty_protocol"
    assert not second.has_pending


def test_input_batch_keeps_split_bracketed_paste_atomic() -> None:
    reader = InputReader()

    first = reader.feed_batch(f"{BRACKETED_PASTE_START}hello")
    second = reader.feed_batch(f" world{BRACKETED_PASTE_END}")

    assert first.app_events == ()
    assert first.control_events == ()
    assert first.has_pending
    assert second.control_events == ()
    assert len(second.app_events) == 1
    assert second.app_events[0].kind == "paste"
    assert second.app_events[0].text == "hello world"


def test_input_batch_keeps_split_bracketed_paste_end_marker_atomic_with_surrounding_text() -> (
    None
):
    reader = InputReader()

    first = reader.feed_batch(f"pre{BRACKETED_PASTE_START[:-1]}")
    second = reader.feed_batch(f"{BRACKETED_PASTE_START[-1]}hello")
    third = reader.feed_batch(f"\nworld{BRACKETED_PASTE_END[:-1]}")

    assert first.control_events == ()
    assert first.app_events == (InputEvent(kind="text", text="pre"),)
    assert first.has_pending
    assert second.app_events == ()
    assert second.control_events == ()
    assert second.has_pending
    assert third.app_events == ()
    assert third.control_events == ()
    assert third.has_pending
    idle = reader.flush_pending_batch()
    assert idle.app_events == ()
    assert idle.control_events == ()
    assert idle.has_pending
    fourth = reader.feed_batch(f"{BRACKETED_PASTE_END[-1]}post")
    assert fourth.control_events == ()
    assert fourth.app_events == (
        InputEvent(kind="paste", text="hello\nworld"),
        InputEvent(kind="text", text="post"),
    )
    assert not fourth.has_pending


def test_input_batch_keeps_split_terminal_control_sequences_pending_until_terminator() -> (
    None
):
    cases = (
        (("\x1b]0;title", "\x07ok"), "osc", "0;title"),
        (("\x1b]0;title\x1b", "\\ok"), "osc", "0;title"),
        (("\x1bP>|vers", "ion\x1b\\ok"), "dcs", ">|version"),
        (("\x1b_Gi=1", ";OK\x1b\\ok"), "apc", "Gi=1;OK"),
    )

    for chunks, signal, text in cases:
        reader = InputReader()
        first = reader.feed_batch(chunks[0])
        second = reader.feed_batch(chunks[1])

        assert first.app_events == ()
        assert first.control_events == ()
        assert first.has_pending
        assert second.control_events == (
            InputEvent(kind="signal", signal=signal, text=text),
        )
        assert second.app_events == (InputEvent(kind="text", text="ok"),)
        assert not second.has_pending


def test_flush_pending_batch_routes_standalone_escape_as_app_event() -> None:
    reader = InputReader()
    first = reader.feed_batch("\x1b")
    flushed = reader.flush_pending_batch()

    assert first.has_pending
    assert flushed.control_events == ()
    assert len(flushed.app_events) == 1
    assert flushed.app_events[0].kind == "key"
    assert flushed.app_events[0].key == "escape"


class _Runtime:
    rendered = 0

    def request_next_animation_frame(self):
        return _Decision()

    def render_now(self) -> None:
        self.rendered += 1


class _Decision:
    render_now = False
    delay_ms = 0


class _DeferredRuntime:
    def __init__(self) -> None:
        self.rendered = 0
        self.decisions = 0

    def request_next_animation_frame(self):
        self.decisions += 1
        if self.decisions == 1 or self.rendered > 0:
            return _DelayedDecision()
        return _ImmediateDecision()

    def render_now(self) -> None:
        self.rendered += 1


class _DelayedDecision:
    render_now = False
    delay_ms = 1_000


class _ImmediateDecision:
    render_now = True
    delay_ms = 0


class _DelayedInputReader:
    def __init__(self, *, block_seconds: float) -> None:
        self.block_seconds = block_seconds

    async def __call__(self, _stdin: object) -> str:
        await asyncio.sleep(self.block_seconds)
        return ""


class _TtyInput:
    def isatty(self) -> bool:
        return True


@dataclass
class _ModeLease:
    restore_calls: int = 0

    def restore(self) -> None:
        self.restore_calls += 1


@dataclass
class _ModeFactory:
    lease: _ModeLease
    open_calls: int = 0

    def open(self, _stdin: object) -> _ModeLease:
        self.open_calls += 1
        return self.lease


class _FailingOutput(StringIO):
    def write(self, value: str) -> int:
        del value
        raise RuntimeError("write failed")
