"""Read fixed Transcript records through the original store admission.

This is a read capability selected by the Product, never a path recovered from
an untrusted reference. It owns no writer, index, retention policy or Work type.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from loushang.harness.conversation import ConversationRepository
from loushang.harness.journal._owned_io import settled_io
from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.transcript.jsonl_file import decode_agent_transcript_bytes
from loushang.harness.transcript.store_admission import TranscriptStoreAdmission
from loushang.harness.transcript.types import AgentTranscriptRecord


class TranscriptSourceError(ValueError):
    """The configured source cannot substantiate a fixed record reference."""


@dataclass(frozen=True)
class TranscriptSourceIdentity:
    store_identity: str
    conversation_id: str  # Product configuration; inspect does not verify a file.


@dataclass(frozen=True)
class TranscriptSourceRecord:
    record: AgentTranscriptRecord
    branch_digest: str


@dataclass(frozen=True)
class TranscriptSourceBatch:
    store_identity: str
    conversation_id: str
    records: tuple[TranscriptSourceRecord, ...]
    bytes_read: int
    ancestors_hashed: int


@dataclass
class _ReadOwner:
    admission: TranscriptStoreAdmission
    io: RootedFileIO | None = None

    def close(self) -> None:
        # Retain the borrowed root until every child descriptor is settled.
        if self.io is not None:
            self.io.cleanup()
            if self.io.cleanup_pending:
                raise TranscriptSourceError("source IO cleanup is unresolved")
        self.admission.close()


def _records(
    content: bytes, path: Path, conversation_id: str, requested: tuple[str, ...]
) -> tuple[tuple[TranscriptSourceRecord, ...], int]:
    # Source v1 is deliberately narrower than the general JSONL decoder.
    if b"\r" in content.replace(b"\r\n", b""):
        raise TranscriptSourceError("source v1 requires LF or CRLF records")
    committed = [line for line in content.split(b"\n")[:-1] if line.strip()]
    if not committed:
        raise TranscriptSourceError("source has no committed header")
    header, records = decode_agent_transcript_bytes(content, source_path=path)
    if header.conversation_id != conversation_id or len(committed) != len(records) + 1:
        raise TranscriptSourceError(
            "source conversation or committed line count differs"
        )
    ConversationRepository.create(
        header=header,
        records=records,
        record_id=lambda r: r.record_id,
        parent_id=lambda r: r.parent_id,
        mode="strict",
    )
    indexed = {
        r.record_id: (r, line) for r, line in zip(records, committed[1:], strict=True)
    }
    base = hashlib.sha256(b"loushang.transcript.branch/v1\0" + committed[0]).digest()
    digests: dict[str, bytes] = {}
    result = []
    for target in requested:
        if target not in indexed:
            raise TranscriptSourceError("source record is not committed")
        pending = []
        current: str | None = target
        while current is not None and current not in digests:
            record, raw = indexed[current]
            pending.append((record, raw))
            current = record.parent_id
        for record, raw in reversed(pending):
            parent = digests[record.parent_id] if record.parent_id is not None else base
            digests[record.record_id] = hashlib.sha256(
                b"loushang.transcript.record/v1\0"
                + parent
                + hashlib.sha256(raw).digest()
            ).digest()
        result.append(TranscriptSourceRecord(indexed[target][0], digests[target].hex()))
    return tuple(result), len(digests)


class TranscriptSourceReader:
    """Owner of explicitly authorized, bounded, read-only source observations.

    Same-user Linux stores only. ``aclose`` rejects new reads and waits for
    admitted native IO. A failed cleanup retains its owner for another close;
    unknown descriptor-close outcomes remain unresolved under the original IO
    ledger. Products must not release dependent roots while close fails.
    """

    def __init__(
        self,
        *,
        session_file: Path,
        conversation_id: str,
        store_state_root: Path,
        max_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        path = Path(session_file)
        if (
            not path.is_absolute()
            or ".." in path.parts
            or not conversation_id
            or type(max_bytes) is not int
            or max_bytes <= 0
        ):
            raise TranscriptSourceError("invalid source reader binding")
        self.session_file = path
        self.conversation_id = conversation_id
        self.store_state_root = Path(store_state_root)
        self.max_bytes = max_bytes
        self._lock = asyncio.Lock()
        self._closing = False
        self._owner: _ReadOwner | None = None

    async def read(self, record_ids: Sequence[str] = ()) -> TranscriptSourceBatch:
        requested = tuple(dict.fromkeys(record_ids))
        if any(type(value) is not str or not value for value in requested):
            raise TranscriptSourceError("record IDs must be nonempty strings")
        return cast(TranscriptSourceBatch, await self._observe(requested))

    def read_sync(self, record_ids: Sequence[str] = ()) -> TranscriptSourceBatch:
        """Blocking counterpart for synchronous inspection APIs.

        Uses the same admission, decoder and retained IO owner as read(). Do not
        call concurrently from another thread; an active async observation is
        rejected instead of waiting on its event loop. close() settles this owner.
        """
        requested = tuple(dict.fromkeys(record_ids))
        if any(type(value) is not str or not value for value in requested):
            raise TranscriptSourceError("record IDs must be nonempty strings")
        if self._lock.locked() or self._closing or self._owner is not None:
            raise TranscriptSourceError("source reader busy, closed or cleanup pending")
        self._owner = _ReadOwner(
            TranscriptStoreAdmission(
                self.session_file.parent, state_root=self.store_state_root
            )
        )
        return cast(TranscriptSourceBatch, self._read(self._owner, requested))

    def close(self) -> None:
        """Synchronous cleanup, retaining the same owner if cleanup fails."""
        self._closing = True
        if self._lock.locked():
            raise TranscriptSourceError(
                "async source observation still active; await aclose"
            )
        if self._owner is not None:
            self._owner.close()
            self._owner = None

    async def inspect_identity(self) -> TranscriptSourceIdentity:
        """Inspect the existing store, without requiring a lazy Session file.

        The conversation ID here is configured by the Product. Only ``read``
        substantiates the physical header and committed records.
        """
        return cast(TranscriptSourceIdentity, await self._observe(None))

    async def _observe(
        self, requested: tuple[str, ...] | None
    ) -> TranscriptSourceBatch | TranscriptSourceIdentity:
        async with self._lock:
            if self._closing or self._owner is not None:
                raise TranscriptSourceError("source reader closed or cleanup pending")
            # Register before dispatch: cancellation must not lose this owner.
            self._owner = _ReadOwner(
                TranscriptStoreAdmission(
                    self.session_file.parent, state_root=self.store_state_root
                )
            )
            return await settled_io(self._read, self._owner, requested)

    def _read(
        self, owner: _ReadOwner, requested: tuple[str, ...] | None
    ) -> TranscriptSourceBatch | TranscriptSourceIdentity:
        try:
            binding = owner.admission.inspect()
            if binding is None:
                raise TranscriptSourceError("source store is not admitted")
            fact = owner.admission._read()
            identity_fields = {
                name: fact.get(name)
                for name in (
                    "version",
                    "store",
                    "operation",
                    "family",
                    "member",
                    "root",
                    "parent",
                )
            }
            identity = (
                "transcript-source/v1:"
                + hashlib.sha256(
                    json.dumps(
                        identity_fields, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest()
            )
            if requested is None:
                owner.admission.check()
                return TranscriptSourceIdentity(identity, self.conversation_id)
            assert owner.admission._store is not None
            owner.io = RootedFileIO(
                self.session_file.parent, owner.admission._store._fds["root"]
            )
            content = owner.io.read_bytes(self.session_file, max_bytes=self.max_bytes)
            owner.admission.check()
            if owner.admission._read() != fact:
                raise TranscriptSourceError("source admission changed during read")
            records, hashed = _records(
                content, self.session_file, self.conversation_id, requested
            )
            return TranscriptSourceBatch(
                identity, self.conversation_id, records, len(content), hashed
            )
        finally:
            owner.close()
            self._owner = None

    async def aclose(self) -> None:
        self._closing = True
        async with self._lock:
            if self._owner is not None:
                owner = self._owner
                await settled_io(owner.close)
                self._owner = None


__all__ = [
    "TranscriptSourceBatch",
    "TranscriptSourceError",
    "TranscriptSourceIdentity",
    "TranscriptSourceReader",
    "TranscriptSourceRecord",
]
