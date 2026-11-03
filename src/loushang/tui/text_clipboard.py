"""Asynchronous clipboard routes for interactive terminal selections."""

from __future__ import annotations

import asyncio
import base64
import importlib
import os
import shutil
import sys
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal, Protocol

ClipboardOutcome = Literal["confirmed", "sent", "failed"]
ClipboardDestination = Literal["user", "remote_host"]


@dataclass(frozen=True, slots=True)
class TextCopyResult:
    outcome: ClipboardOutcome
    destination: ClipboardDestination
    message: str = ""


class TextClipboardWriter(Protocol):
    destination: ClipboardDestination

    async def write(self, text: str) -> TextCopyResult: ...


@dataclass(slots=True)
class CommandClipboardWriter:
    commands: tuple[tuple[str, tuple[str, ...]], ...]
    destination: ClipboardDestination = "user"
    encoding: str = "utf-8"

    async def write(self, text: str) -> TextCopyResult:
        last_error = "No clipboard command was available."
        for command, args in self.commands:
            try:
                process = await asyncio.create_subprocess_exec(
                    command,
                    *args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(
                        process.communicate(text.encode(self.encoding)), timeout=3
                    )
                except asyncio.CancelledError:
                    with suppress(ProcessLookupError):
                        process.kill()
                    await process.wait()
                    raise
                except TimeoutError:
                    with suppress(ProcessLookupError):
                        process.kill()
                    await process.wait()
                    last_error = f"{command} timed out"
                    continue
            except OSError as exc:
                last_error = str(exc)
                continue
            if process.returncode == 0:
                return TextCopyResult("confirmed", self.destination)
            last_error = f"{command} exited with status {process.returncode}"
        return TextCopyResult("failed", self.destination, last_error)


@dataclass(slots=True)
class Osc52ClipboardWriter:
    """Send bounded OSC 52 through the active terminal owner without claiming ack."""

    write_control: Callable[[str], bool]
    destination: ClipboardDestination = "user"
    max_bytes: int = 16_384

    async def write(self, text: str) -> TextCopyResult:
        payload = text.encode()
        if len(payload) > self.max_bytes:
            return TextCopyResult(
                "failed", self.destination, "Selection exceeds OSC 52 limit"
            )
        encoded = base64.b64encode(payload).decode("ascii")
        if self.write_control(f"\x1b]52;c;{encoded}\x07"):
            return TextCopyResult("sent", self.destination)
        return TextCopyResult(
            "failed", self.destination, "Terminal session is no longer active"
        )


_ADAPTERS: tuple[tuple[Callable[[Mapping[str, str], str], bool], str], ...] = (
    (lambda env, _platform: bool(env.get("TERMUX_VERSION")), "termux"),
    (
        lambda env, _platform: bool(
            env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP")
        ),
        "wsl",
    ),
    (lambda _env, platform: platform.startswith(("win", "cygwin", "msys")), "windows"),
    (lambda _env, platform: platform == "darwin", "darwin"),
    (lambda _env, _platform: True, "linux"),
)


def select_text_clipboard_writer(
    env: Mapping[str, str] | None = None,
    *,
    platform: str | None = None,
    write_control: Callable[[str], bool] | None = None,
    loader: Callable[[str], object] = importlib.import_module,
    which: Callable[[str], str | None] = shutil.which,
) -> TextClipboardWriter | None:
    values = os.environ if env is None else env
    if (
        values.get("SSH_TTY")
        or values.get("SSH_CONNECTION")
        or values.get("SSH_CLIENT")
    ):
        return (
            Osc52ClipboardWriter(write_control)
            if values.get("LOUSHANG_TUI_OSC52") == "1" and write_control is not None
            else None
        )
    platform_name = platform or sys.platform
    adapter_name = next(
        name for accepts, name in _ADAPTERS if accepts(values, platform_name)
    )
    adapter = loader(f"loushang.tui.clipboard_backends.{adapter_name}")
    candidates = adapter.candidates(values)  # type: ignore[attr-defined]
    available = tuple((command, args) for command, args in candidates if which(command))
    if available:
        return CommandClipboardWriter(
            available, encoding=getattr(adapter, "encoding", "utf-8")
        )
    if values.get("LOUSHANG_TUI_OSC52") == "1" and write_control is not None:
        return Osc52ClipboardWriter(write_control)
    return None


def user_clipboard_route_available(
    writer: TextClipboardWriter | None,
    env: Mapping[str, str],
) -> bool:
    """Check route intent before OSC 52 is bound to a live terminal session."""
    return (writer is not None and writer.destination == "user") or env.get(
        "LOUSHANG_TUI_OSC52"
    ) == "1"


__all__ = [
    "CommandClipboardWriter",
    "Osc52ClipboardWriter",
    "TextClipboardWriter",
    "TextCopyResult",
    "select_text_clipboard_writer",
    "user_clipboard_route_available",
]
