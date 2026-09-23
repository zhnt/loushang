"""Product transaction guard paired with the Package cutover coordination lock."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.journal import journal_file_lock

_SAFE_STORE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")


@dataclass(frozen=True, slots=True)
class PackageProductFileEpochTransactionGuard:
    """Hold the Product's shared coordination lock across admission and effects.

    Offline cutover must acquire the same lock path exclusively before its
    quiescence and root-switch proof. This guard does not issue a runtime lease
    or turn an uncut legacy root into a B-epoch Store.
    """

    store_id: str
    coordination_lock: Path

    def __post_init__(self) -> None:
        if (
            not isinstance(self.store_id, str)
            or _SAFE_STORE_ID.fullmatch(self.store_id) is None
        ):
            raise ValueError("Package Product store identity is invalid")
        path = self.coordination_lock
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or ".." in path.parts
            or path == Path(path.anchor)
        ):
            raise ValueError("Package Product coordination lock must be absolute")

    @contextmanager
    def shared_runtime(self, *, store_id: str) -> Iterator[None]:
        if store_id != self.store_id:
            raise ValueError("Package Product store identity changed")
        with journal_file_lock(self.coordination_lock, "shared"):
            yield


__all__ = ["PackageProductFileEpochTransactionGuard"]
