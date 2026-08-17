"""Public test support for Product-neutral RPC wire playback."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import StringIO

from .runtime import RpcHost


@dataclass(frozen=True, slots=True)
class RpcWirePlaybackResult:
    """Captured JSONL output and host status from one playback."""

    records: tuple[dict[str, object], ...]
    exit_codes: tuple[int, ...]
    stdout: str
    stderr: str


class RpcWirePlayback:
    """Drive one live ``RpcHost`` command by command in a test."""

    def __init__(
        self,
        *,
        runtime: object,
        event_view: str = "full",
        event_select: str | Sequence[str] | None = None,
        render_tool_events: bool = False,
    ) -> None:
        self._stdout = StringIO()
        self._stderr = StringIO()
        self._host = RpcHost(
            runtime=runtime,
            stdin=StringIO(),
            stdout=self._stdout,
            stderr=self._stderr,
            event_view=event_view,
            event_select=event_select,
            render_tool_events=render_tool_events,
        )
        self._exit_codes: list[int] = []
        self._finished = False

    @property
    def host(self) -> RpcHost:
        """Expose the host only for assertions outside the wire contract."""

        return self._host

    async def dispatch(self, command: Mapping[str, object]) -> int:
        """Submit one strict-JSON command without waiting for background work."""

        wire_line = json.dumps(dict(command), allow_nan=False)
        return await self.dispatch_line(wire_line)

    async def dispatch_line(self, wire_line: str) -> int:
        """Submit one raw JSONL line without waiting for background work."""

        if self._finished:
            raise RuntimeError("RPC wire playback is already finished")
        if not isinstance(wire_line, str):
            raise TypeError("RPC wire playback lines must be strings")
        exit_code = await self._host.submit_input(wire_line)
        self._exit_codes.append(exit_code)
        return exit_code

    def snapshot(self) -> RpcWirePlaybackResult:
        """Return output emitted so far without changing host lifecycle."""

        return _playback_result(
            stdout=self._stdout.getvalue(),
            stderr=self._stderr.getvalue(),
            exit_codes=tuple(self._exit_codes),
        )

    async def finish(self) -> RpcWirePlaybackResult:
        """Wait for Product-owned tasks and close transport subscriptions."""

        if not self._finished:
            await self._host.settle_background_tasks()
            await self._host.stop()
            self._finished = True
        return self.snapshot()

    async def dispose(self) -> RpcWirePlaybackResult:
        """Dispose the Product runtime and settle its outstanding host tasks."""

        if not self._finished:
            await self._host.dispose()
            self._finished = True
        return self.snapshot()


async def play_rpc_wire_async(
    *,
    runtime: object,
    commands: Sequence[Mapping[str, object]],
    event_view: str = "full",
    event_select: str | Sequence[str] | None = None,
    render_tool_events: bool = False,
) -> RpcWirePlaybackResult:
    """Play a finite command sequence through the live RPC host."""

    playback = RpcWirePlayback(
        runtime=runtime,
        event_view=event_view,
        event_select=event_select,
        render_tool_events=render_tool_events,
    )
    result: RpcWirePlaybackResult
    try:
        for command in commands:
            exit_code = await playback.dispatch(command)
            if exit_code != 0:
                raise RuntimeError(
                    f"RPC command dispatch failed with exit code {exit_code}"
                )
    finally:
        result = await playback.finish()
    return result


def play_rpc_wire(
    *,
    runtime: object,
    commands: Sequence[Mapping[str, object]],
    event_view: str = "full",
    event_select: str | Sequence[str] | None = None,
    render_tool_events: bool = False,
) -> RpcWirePlaybackResult:
    """Synchronous wrapper for tests that do not already own an event loop."""

    return asyncio.run(
        play_rpc_wire_async(
            runtime=runtime,
            commands=commands,
            event_view=event_view,
            event_select=event_select,
            render_tool_events=render_tool_events,
        )
    )


async def play_rpc_lines_async(
    *,
    runtime: object,
    lines: Sequence[str],
    event_view: str = "full",
    event_select: str | Sequence[str] | None = None,
    render_tool_events: bool = False,
) -> RpcWirePlaybackResult:
    """Run raw JSONL fragments exactly as one finite stdin transcript."""

    if not all(isinstance(line, str) for line in lines):
        raise TypeError("RPC wire playback lines must be strings")
    stdout = StringIO()
    stderr = StringIO()
    host = RpcHost(
        runtime=runtime,
        stdin=StringIO("".join(lines)),
        stdout=stdout,
        stderr=stderr,
        event_view=event_view,
        event_select=event_select,
        render_tool_events=render_tool_events,
    )
    exit_code = await host.run()
    return _playback_result(
        stdout=stdout.getvalue(),
        stderr=stderr.getvalue(),
        exit_codes=(exit_code,),
    )


def play_rpc_lines(
    *,
    runtime: object,
    lines: Sequence[str],
    event_view: str = "full",
    event_select: str | Sequence[str] | None = None,
    render_tool_events: bool = False,
) -> RpcWirePlaybackResult:
    """Synchronous raw-transcript wrapper for framing and parser tests."""

    return asyncio.run(
        play_rpc_lines_async(
            runtime=runtime,
            lines=lines,
            event_view=event_view,
            event_select=event_select,
            render_tool_events=render_tool_events,
        )
    )


def _playback_result(
    *,
    stdout: str,
    stderr: str,
    exit_codes: tuple[int, ...],
) -> RpcWirePlaybackResult:
    records: list[dict[str, object]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            raise AssertionError("RPC playback emitted a non-object JSON record")
        records.append(record)
    return RpcWirePlaybackResult(
        records=tuple(records),
        exit_codes=exit_codes,
        stdout=stdout,
        stderr=stderr,
    )


__all__ = [
    "RpcWirePlayback",
    "RpcWirePlaybackResult",
    "play_rpc_lines",
    "play_rpc_lines_async",
    "play_rpc_wire",
    "play_rpc_wire_async",
]
