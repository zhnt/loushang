"""Supported access to the existing retained directory writer and borrowed IO.

This optional module does not acquire resources on import. The caller retains
its writer before acquisition, settles borrowed IO before closing that writer,
and retries cleanup on the same objects. Owner labels do not partition physical
exclusion. Subclasses select a fixed lock-directory and hash-domain protocol.
"""

from __future__ import annotations

from pathlib import Path

from loushang.harness.journal._directory_lease import (
    DirectoryWriterError as DirectoryWriterError,
)
from loushang.harness.journal._directory_lease import (
    DirectoryWriterLease as DirectoryWriterLease,
)
from loushang.harness.journal._rooted_io import RootedFileIO as RootedFileIO


def borrow_root_io(
    lease: DirectoryWriterLease, *, root: Path, owner_id: str, authority_id: str
) -> RootedFileIO:
    """Borrow only an acquired, unclaimed, exact existing writer binding.

    This does not open a root, acquire a lease or grant another authority. The
    existing lease validates binding and retains the sole root descriptor.
    """
    return lease._borrow_root_io(
        root=root, owner_id=owner_id, authority_id=authority_id
    )


__all__ = [
    "DirectoryWriterError",
    "DirectoryWriterLease",
    "RootedFileIO",
    "borrow_root_io",
]
