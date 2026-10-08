"""Termux clipboard command."""

from __future__ import annotations

from collections.abc import Mapping


def candidates(_env: Mapping[str, str]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (("termux-clipboard-set", ()),)
