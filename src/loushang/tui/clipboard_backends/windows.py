"""Windows clipboard command."""

from __future__ import annotations

from collections.abc import Mapping

encoding = "utf-16le"


def candidates(_env: Mapping[str, str]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (("clip.exe", ()),)
