"""Canonical header authority in the existing Transcript source component."""

from __future__ import annotations

import hashlib
import stat as stat_module
import threading
from collections.abc import Callable
from pathlib import Path

from loushang.harness.conversation import ConversationHeader


class _CanonicalTranscriptSourceMethods:
    """Original canonical header authority; no summary/index fallback."""

    def _catalog_error_class(self) -> type[RuntimeError]:
        raise NotImplementedError

    def _catalog_error(self) -> RuntimeError:
        return self._catalog_error_class()()

    def _maximum_transcript_bytes(self) -> int:
        raise NotImplementedError

    def _source_revision(self, path: Path) -> str:
        return canonical_transcript_revision(
            path,
            maximum_bytes=self._maximum_transcript_bytes,
            error=self._catalog_error,
        )

    def _directory_revision(self, path: Path) -> tuple[int, int, int] | None:
        return canonical_transcript_directory_revision(path, error=self._catalog_error)


def canonical_transcript_directory_revision(
    path: Path, *, error: Callable[[], RuntimeError]
) -> tuple[int, int, int] | None:
    try:
        status = path.lstat()
    except FileNotFoundError:
        return None
    if not stat_module.S_ISDIR(status.st_mode) or (
        getattr(status, "st_file_attributes", 0)
        & getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise error()
    return status.st_dev, status.st_ino, status.st_mtime_ns


def canonical_transcript_revision(
    path: Path, *, maximum_bytes: Callable[[], int], error: Callable[[], RuntimeError]
) -> str:
    from loushang.harness.transcript.session_catalog import (
        session_file_authority_fingerprint,
    )

    status = path.lstat()
    if (
        not stat_module.S_ISREG(status.st_mode)
        or getattr(status, "st_file_attributes", 0)
        & getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        or status.st_size > maximum_bytes()
    ):
        raise error()
    return hashlib.sha256(session_file_authority_fingerprint(path).encode()).hexdigest()


def read_canonical_transcript_header(
    root: Path,
    path: Path,
    *,
    owned: bool,
    discovery: bool,
    root_observed: threading.Event | None,
    maximum_bytes: Callable[[], int],
    error: Callable[[], RuntimeError],
) -> tuple[str, ConversationHeader]:
    from loushang.harness.transcript.jsonl_file import load_agent_transcript_header

    if path.parent != root:
        raise error()
    if root_observed is not None:
        root_observed.set()
    before = canonical_transcript_revision(
        path, maximum_bytes=maximum_bytes, error=error
    )
    header = (
        load_agent_transcript_header(path, read_only=True)
        if owned
        else load_agent_transcript_header(path, blocking=False, create_lock=False)
        if discovery
        else load_agent_transcript_header(path)
    )
    if (
        canonical_transcript_revision(path, maximum_bytes=maximum_bytes, error=error)
        != before
    ):
        raise error()
    return before, header
