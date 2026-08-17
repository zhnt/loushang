"""Provider contract for language-extensible import graph extraction."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from loushang.coding.arch.cache import ImportFactCache
from loushang.coding.arch.model import ImportProviderScan


class ImportGraphProvider(Protocol):
    """Extract normalized import facts for one programming language."""

    @property
    def language(self) -> str: ...

    def supports(self, root: Path) -> bool: ...

    def scan(
        self,
        root: Path,
        *,
        package_prefix: str | None = None,
        excludes: tuple[str, ...] = (),
        cache: ImportFactCache | None = None,
        refresh_cache: bool = False,
    ) -> ImportProviderScan: ...


__all__ = ["ImportGraphProvider"]
