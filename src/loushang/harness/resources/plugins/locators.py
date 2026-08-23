"""Canonical path and symbol codecs for inert Plugin metadata."""

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath

_SYMBOL = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")


def canonical_plugin_relative_path(value: object) -> PurePosixPath:
    """Return one host-independent, contained Plugin-relative path."""

    if isinstance(value, PurePosixPath):
        text = value.as_posix()
    elif isinstance(value, str):
        text = value
    else:
        raise ValueError("Plugin path must be a canonical contained relative path")
    if text != text.strip() or "\\" in text:
        raise ValueError("Plugin path must be a canonical contained relative path")
    path = PurePosixPath(text)
    windows_path = PureWindowsPath(text)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or not path.parts
        or path.as_posix() != text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Plugin path must be a canonical contained relative path")
    return path


def canonical_plugin_python_path(value: object) -> PurePosixPath:
    """Return one canonical Plugin-relative Python source path."""

    path = canonical_plugin_relative_path(value)
    if path.suffix != ".py":
        raise ValueError("Plugin path must identify a Python source file")
    return path


def canonical_plugin_symbol(value: object) -> str:
    """Return one canonical dotted Python symbol."""

    if not isinstance(value, str) or not _SYMBOL.fullmatch(value):
        raise ValueError("Plugin symbol must be a dotted Python symbol")
    return value


def parse_plugin_entrypoint(value: object) -> tuple[PurePosixPath, str]:
    """Parse canonical ``path.py:symbol`` Plugin entrypoint syntax."""

    if not isinstance(value, str) or value != value.strip():
        raise ValueError("Plugin entrypoint must use contained path.py:symbol syntax")
    raw_path, separator, raw_symbol = value.rpartition(":")
    try:
        path = canonical_plugin_python_path(raw_path)
        symbol = canonical_plugin_symbol(raw_symbol)
    except ValueError as exc:
        raise ValueError(
            "Plugin entrypoint must use contained path.py:symbol syntax"
        ) from exc
    if separator != ":":
        raise ValueError("Plugin entrypoint must use contained path.py:symbol syntax")
    return path, symbol


__all__: list[str] = []
