from __future__ import annotations

import asyncio
import importlib
import os
import select
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

PosixModeModuleLoader = Callable[[], tuple[Any, Any] | None]


def _load_mode_modules() -> tuple[Any, Any] | None:
    try:
        return importlib.import_module("termios"), importlib.import_module("tty")
    except ModuleNotFoundError:
        return None


@dataclass(frozen=True, slots=True)
class PosixTerminalInput:
    """Read UTF-8 input from a POSIX terminal file descriptor."""

    async def read_chunk(self, stdin: Any) -> str:
        fd = stdin.fileno()
        while True:
            try:
                readable, _, _ = select.select([fd], [], [], 0)
            except (OSError, ValueError):
                return ""
            if readable:
                return _read_chunk(stdin)
            await asyncio.sleep(0.01)

    def read_chunk_blocking(self, stdin: Any) -> str:
        return _read_chunk(stdin)

    def drain(
        self,
        stdin: Any,
        *,
        max_bytes: int,
        idle_timeout: float,
        max_duration: float | None,
        now: Callable[[], float],
    ) -> str:
        fd = stdin.fileno()
        drained = bytearray()
        deadline = None if max_duration is None else now() + max(0.0, max_duration)
        while len(drained) < max_bytes:
            timeout = idle_timeout
            if deadline is not None:
                remaining = deadline - now()
                if remaining <= 0:
                    break
                timeout = min(timeout, remaining)
            try:
                readable, _, _ = select.select([fd], [], [], timeout)
            except (OSError, ValueError):
                break
            if not readable:
                break
            chunk = os.read(fd, min(1024, max_bytes - len(drained)))
            if not chunk:
                break
            drained.extend(chunk)
        return bytes(drained).decode("utf-8", errors="replace")


POSIX_TERMINAL_INPUT = PosixTerminalInput()


@dataclass(frozen=True, slots=True)
class PosixTerminalMode:
    """Enter cbreak mode and return exclusive ownership of its restoration."""

    module_loader: PosixModeModuleLoader = _load_mode_modules

    def open(self, stdin: Any) -> PosixTerminalModeLease | None:
        modules = self.module_loader()
        if modules is None:
            return None
        termios_module, tty_module = modules
        fd = stdin.fileno()
        original_attrs = termios_module.tcgetattr(fd)
        try:
            tty_module.setcbreak(fd)
            attrs = [*original_attrs[:6], list(original_attrs[6])]
            attrs[0] &= ~getattr(termios_module, "ICRNL", 0)
            attrs[3] &= ~(
                termios_module.ECHO
                | termios_module.ICANON
                | getattr(termios_module, "ISIG", 0)
                | getattr(termios_module, "IEXTEN", 0)
            )
            attrs[6][termios_module.VMIN] = 1
            attrs[6][termios_module.VTIME] = 0
            termios_module.tcsetattr(fd, termios_module.TCSADRAIN, attrs)
        except BaseException:
            termios_module.tcsetattr(
                fd,
                termios_module.TCSADRAIN,
                original_attrs,
            )
            raise
        return PosixTerminalModeLease(
            fd=fd,
            termios_module=termios_module,
            original_attrs=original_attrs,
        )


@dataclass(frozen=True, slots=True)
class PosixTerminalModeLease:
    fd: int
    termios_module: Any
    original_attrs: list[Any]

    def restore(self) -> None:
        self.termios_module.tcsetattr(
            self.fd,
            self.termios_module.TCSADRAIN,
            self.original_attrs,
        )


POSIX_TERMINAL_MODE = PosixTerminalMode()


def _read_chunk(stdin: Any) -> str:
    fd = stdin.fileno()
    first = os.read(fd, 1)
    if first == b"":
        return ""
    return (first + _read_utf8_tail(fd, first)).decode("utf-8", errors="replace")


def _read_utf8_tail(fd: int, first: bytes) -> bytes:
    needed = _utf8_sequence_length(first[0])
    tail = b""
    while len(tail) < needed - 1:
        chunk = os.read(fd, 1)
        if chunk == b"":
            break
        tail += chunk
    return tail


def _utf8_sequence_length(first_byte: int) -> int:
    if first_byte & 0b1000_0000 == 0:
        return 1
    if first_byte & 0b1110_0000 == 0b1100_0000:
        return 2
    if first_byte & 0b1111_0000 == 0b1110_0000:
        return 3
    if first_byte & 0b1111_1000 == 0b1111_0000:
        return 4
    return 1


__all__ = [
    "POSIX_TERMINAL_INPUT",
    "POSIX_TERMINAL_MODE",
    "PosixTerminalInput",
    "PosixTerminalMode",
    "PosixTerminalModeLease",
]
