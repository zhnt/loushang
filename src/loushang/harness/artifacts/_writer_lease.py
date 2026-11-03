"""Optional Session blob lifetime writer; separate from each blob operation lock.

The data root must already exist. This lease neither creates an attachment tree
nor authorizes pathname IO; callers retain it through their IO and cleanup.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loushang.harness.journal._directory_lease import (
    DirectoryWriterError,
    DirectoryWriterLease,
)

from .references import session_blob_authority_id

if TYPE_CHECKING:
    from loushang.harness.journal._rooted_io import RootedFileIO


class SessionBlobWriterError(DirectoryWriterError):
    """Bounded Session attachment admission failure."""

    prefix = "session_blob_writer"


class SessionBlobWriterLease(DirectoryWriterLease):
    """One physical data-root + normalized Session attachment authority.

    Product/owner identity does not partition exclusion. The stable lifetime
    lock is outside session-assets and cannot disappear on Session deletion.
    """

    _error_type = SessionBlobWriterError
    _lock_directory = ".session-blob-writers"
    _hash_domain = "session-blob-writer/v1"

    def __init__(self, data_root: Path, owner_id: str, session_id: str, *,
                 expected_root_identity: tuple[int, int] | None = None) -> None:
        super().__init__(data_root, owner_id, session_blob_authority_id(session_id),
                         expected_root_identity=expected_root_identity)

    def check(self, *, owner_id: str, session_id: str) -> None:
        self.check_binding(owner_id=owner_id, authority_id=session_blob_authority_id(session_id))

    def borrow_file_io(self, *, data_root: Path, owner_id: str, session_id: str,
                       directory_bindings: tuple[tuple[tuple[int, int], str, tuple[int, int]], ...] = ()) -> RootedFileIO:
        return self._borrow_root_io(
            root=data_root, owner_id=owner_id, authority_id=session_blob_authority_id(session_id),
            directory_bindings=directory_bindings,
        )
