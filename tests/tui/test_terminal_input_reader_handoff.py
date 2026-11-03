"""A loading reader can stop between UTF-8 bytes without losing them."""

import asyncio
from types import SimpleNamespace

import pytest

from loushang.tui.terminal_backends import posix


def test_partial_utf8_survives_cancellation_and_new_loop(monkeypatch):
    available = [b"\xe4"]
    reads = []

    def read(fd, count):
        assert available, "must not block reading an unavailable UTF-8 tail"
        reads.append(fd)
        return available.pop(0)

    monkeypatch.setattr(posix.os, "read", read)
    monkeypatch.setattr(
        posix.select, "select", lambda *args: ([42] if available else [], [], [])
    )
    reader = posix.PosixTerminalInput().open_reader(SimpleNamespace(fileno=lambda: 42))

    async def pause():
        task = asyncio.create_task(reader.read_chunk())
        await asyncio.sleep(0)
        assert reads == [42] and not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(pause())
    available.extend([b"\xbd", b"\xa0"])
    assert asyncio.run(reader.read_chunk()) == "你"
    assert reads == [42, 42, 42]


@pytest.mark.parametrize(
    "chunks,expected",
    [([b"\xe4", b"\x03"], "\ufffd\x03"), ([b"\xe4", b""], "\ufffd"), ([b""], "")],
)
def test_malformed_or_eof_input_does_not_wait_for_nonexistent_tail(
    monkeypatch, chunks, expected
):
    available = list(chunks)
    monkeypatch.setattr(posix.os, "read", lambda *args: available.pop(0))
    monkeypatch.setattr(
        posix.select, "select", lambda *args: ([42] if available else [], [], [])
    )
    reader = posix.PosixTerminalInput().open_reader(SimpleNamespace(fileno=lambda: 42))
    assert asyncio.run(asyncio.wait_for(reader.read_chunk(), 1)) == expected


def test_reader_rejects_overlapping_owners(monkeypatch):
    monkeypatch.setattr(posix.select, "select", lambda *args: ([], [], []))
    reader = posix.PosixTerminalInput().open_reader(SimpleNamespace(fileno=lambda: 42))

    async def scenario():
        first = asyncio.create_task(reader.read_chunk())
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError, match="already active"):
            await reader.read_chunk()
        with pytest.raises(RuntimeError, match="read is active"):
            reader.at_input_boundary()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

    asyncio.run(scenario())


def test_admission_boundary_preserves_queued_bytes_and_partial_utf8(monkeypatch):
    available = [b"\xe4"]
    monkeypatch.setattr(posix.os, "read", lambda *args: available.pop(0))
    monkeypatch.setattr(
        posix.select, "select", lambda *args: ([42] if available else [], [], [])
    )
    reader = posix.PosixTerminalInputReader(42)
    assert not reader.at_input_boundary()
    assert available == [b"\xe4"]

    async def partial():
        task = asyncio.create_task(reader.read_chunk())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(partial())
    assert not available
    assert not reader.at_input_boundary(), "partial decoder is not an empty boundary"
    available.append(b"\xbd\xa0")
    assert asyncio.run(reader.read_chunk()) == "你"
    assert reader.at_input_boundary()
