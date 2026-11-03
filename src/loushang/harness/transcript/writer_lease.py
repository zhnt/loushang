"""Optional transcript writer projection over the shared directory mechanism."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loushang.harness.journal._directory_lease import (
    DirectoryWriterError,
    DirectoryWriterLease,
)

if TYPE_CHECKING:
    from loushang.harness.journal._rooted_io import RootedFileIO


class TranscriptWriterError(DirectoryWriterError):
    """Bounded transcript admission failure; preserves the existing error API."""

    prefix = "transcript_writer"


class TranscriptStoreAdmissionError(TranscriptWriterError):
    """Local admission diagnostics without changing the bounded error string."""

    def __init__(self, code: str, *, stage: str, record_path: Path) -> None:
        super().__init__(code)
        self.stage = stage
        self.record_path = record_path
        self.add_note(
            f"Transcript admission stage={stage}; record={record_path}. "
            "Keep the original state. A missing committed record can only be "
            "restored from a matching initialized backup using "
            "TranscriptStoreAdmission.restore_record_from_backup(). "
            "Do not substitute a default identity."
        )


class TranscriptWriterLease(DirectoryWriterLease):
    """Root + conversation exclusion, independent of Product identity."""

    _error_type = TranscriptWriterError
    _lock_directory = ".transcript-writers"
    _hash_domain = "transcript-writer/v1"

    def __init__(self, root: Path, product_id: str, conversation_id: str, *, create_root: bool = False,
                 expected_root_identity: tuple[int, int] | None = None,
                 expected_parent_identity: tuple[int, int] | None = None) -> None:
        super().__init__(root, product_id, conversation_id, create_root=create_root,
                         expected_root_identity=expected_root_identity, expected_parent_identity=expected_parent_identity)

    def check(self, *, product_id: str, conversation_id: str) -> None:
        self.check_binding(owner_id=product_id, authority_id=conversation_id)

    def _claim(self, owner: object, *, root: Path, product_id: str, conversation_id: str) -> None:
        self._claim_binding(owner, root=root, owner_id=product_id, authority_id=conversation_id)

    def _borrow_file_io(self, *, root: Path, product_id: str, conversation_id: str) -> RootedFileIO:
        return self._borrow_root_io(root=root, owner_id=product_id, authority_id=conversation_id)
