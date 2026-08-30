from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import math
import os
import stat
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Generic, TypeVar

from loushang.harness.conversation.store import (
    CommitReceipt,
    ConversationBatchCommitResult,
    ConversationCommitResult,
    ConversationHead,
    ConversationKey,
    ConversationLoadResult,
    ConversationPage,
    ConversationSnapshot,
    ConversationSourceDiagnostic,
    DeletionReceipt,
    StoreAlreadyExistsError,
    StoreCommitOutcomeUnknown,
    StoreConflictError,
    StoreDataError,
    StoreNotFoundError,
    StoreOperationConflictError,
    conversation_content_updated_at,
    page_offset,
    require_operation_id,
    require_page_limit,
    require_revision,
)
from loushang.harness.journal import (
    JournalFileError,
    JsonlJournal,
    JsonlSnapshot,
    append_jsonl_record,
    append_jsonl_records,
    journal_file_lock,
    load_jsonl,
    write_jsonl,
)

HeaderT = TypeVar("HeaderT")
RecordT = TypeVar("RecordT")
CreatePath = Callable[[ConversationKey], Path]
ResolvePath = Callable[[ConversationKey], Path | None]
ScanPaths = Callable[[str], Iterable[Path]]
KeyForPath = Callable[[str, Path], ConversationKey]
JournalFactory = Callable[[Path], JsonlJournal[HeaderT, RecordT]]
SnapshotLoader = Callable[[Path], JsonlSnapshot[HeaderT, RecordT]]
DeleteArtifacts = Callable[[Path], None]
Clock = Callable[[], datetime]
RecordId = Callable[[RecordT], str | None]
TombstonePath = Callable[[ConversationKey], Path]

_STORE_HEAD_VERSION = 2
# The head is an advisory acceleration structure. Journal bytes remain authoritative;
# any identity, checksum, compatibility, or schema mismatch falls back to replay.
_OPERATION_FILTER_INITIAL_CAPACITY = 10_000
_OPERATION_FILTER_FALSE_POSITIVE_BUDGET = 1e-5
_OPERATION_FILTER_MAX_SEGMENTS = 32
_RECENT_RECORD_LIMIT = 64
_TOMBSTONE_MAX_BYTES = 64 * 1024


@dataclass(frozen=True)
class _JournalIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class _OperationFilterSegment:
    payload: bytes
    insertions: int
    hashes: int

    def might_contain(self, operation_id: str) -> bool:
        bit_count = len(self.payload) * 8
        return all(
            self.payload[position // 8] & (1 << (position % 8))
            for position in _operation_filter_positions(
                operation_id,
                bit_count=bit_count,
                hashes=self.hashes,
            )
        )


@dataclass(frozen=True)
class _OperationFilter:
    segments: tuple[_OperationFilterSegment, ...]

    @classmethod
    def empty(cls) -> _OperationFilter:
        return cls(())

    def might_contain(self, operation_id: str) -> bool:
        return any(segment.might_contain(operation_id) for segment in self.segments)

    def add(self, operation_id: str) -> _OperationFilter:
        builder = _OperationFilterBuilder(self)
        builder.add(operation_id)
        return builder.freeze()


class _OperationFilterBuilder:
    def __init__(self, operation_filter: _OperationFilter) -> None:
        self._payloads = [
            bytearray(segment.payload) for segment in operation_filter.segments
        ]
        self._insertions = [segment.insertions for segment in operation_filter.segments]
        self._hashes = [segment.hashes for segment in operation_filter.segments]

    def might_contain(self, operation_id: str) -> bool:
        return any(
            all(
                payload[position // 8] & (1 << (position % 8))
                for position in _operation_filter_positions(
                    operation_id,
                    bit_count=len(payload) * 8,
                    hashes=hashes,
                )
            )
            for payload, hashes in zip(
                self._payloads,
                self._hashes,
                strict=True,
            )
        )

    def add(self, operation_id: str) -> bool:
        if self.might_contain(operation_id):
            return False
        if (
            not self._payloads
            or self._insertions[-1]
            >= _operation_filter_segment_shape(len(self._payloads) - 1)[0]
        ):
            _, bits, hashes = _operation_filter_segment_shape(len(self._payloads))
            self._payloads.append(bytearray(bits // 8))
            self._insertions.append(0)
            self._hashes.append(hashes)
        payload = self._payloads[-1]
        for position in _operation_filter_positions(
            operation_id,
            bit_count=len(payload) * 8,
            hashes=self._hashes[-1],
        ):
            payload[position // 8] |= 1 << (position % 8)
        self._insertions[-1] += 1
        return True

    def freeze(self) -> _OperationFilter:
        return _OperationFilter(
            tuple(
                _OperationFilterSegment(
                    payload=bytes(payload),
                    insertions=insertions,
                    hashes=hashes,
                )
                for payload, insertions, hashes in zip(
                    self._payloads,
                    self._insertions,
                    self._hashes,
                    strict=True,
                )
            )
        )


@dataclass(frozen=True)
class _RecentRecord:
    revision: int
    record_id: str
    digest: str
    unique: bool


@dataclass(frozen=True)
class _StoreHead:
    compatibility_token: str
    revision: int
    identity: _JournalIdentity
    operation_filter: _OperationFilter
    recent_records: tuple[_RecentRecord, ...] = ()


class FileConversationStore(Generic[HeaderT, RecordT]):
    """File-backed Store whose layout and codecs are Product supplied.

    Persistent append acceleration is opt-in. Products must provide a stable
    ``head_compatibility_token`` and bump it whenever writable codec, load-policy,
    or record-id projection semantics change. Without a token the journal is
    replayed before each append, preserving the conservative legacy behavior.
    """

    def __init__(
        self,
        *,
        create_path: CreatePath,
        resolve_path: ResolvePath,
        scan_paths: ScanPaths,
        key_for_path: KeyForPath,
        journal_factory: JournalFactory[HeaderT, RecordT],
        write_journal_factory: JournalFactory[HeaderT, RecordT] | None = None,
        clock: Clock | None = None,
        record_id: RecordId[RecordT] | None = None,
        tombstone_path: TombstonePath | None = None,
        head_compatibility_token: str | None = None,
        snapshot_loader: SnapshotLoader[HeaderT, RecordT] | None = None,
        delete_artifacts: DeleteArtifacts | None = None,
    ) -> None:
        self._create_path = create_path
        self._resolve_path = resolve_path
        self._scan_paths = scan_paths
        self._key_for_path = key_for_path
        self._journal_factory = journal_factory
        self._write_journal_factory = write_journal_factory or journal_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._record_id = record_id
        self._tombstone_path = tombstone_path
        self._head_compatibility_token = _require_head_compatibility_token(
            head_compatibility_token
        )
        self._snapshot_loader = snapshot_loader
        self._delete_artifacts = delete_artifacts

    async def create(
        self,
        key: ConversationKey,
        header: HeaderT,
        records: Sequence[RecordT] = (),
        *,
        operation_id: str,
    ) -> ConversationSnapshot[HeaderT, RecordT]:
        return await asyncio.to_thread(
            self._create_sync,
            key,
            header,
            records,
            operation_id=operation_id,
        )

    async def load(
        self,
        key: ConversationKey,
    ) -> ConversationLoadResult[HeaderT, RecordT]:
        return await asyncio.to_thread(self._load_sync, key)

    async def append(
        self,
        key: ConversationKey,
        record: RecordT,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> ConversationCommitResult:
        operation = asyncio.to_thread(
            self._append_sync,
            key,
            record,
            expected_revision=expected_revision,
            operation_id=operation_id,
        )
        return await asyncio.shield(operation)

    async def append_batch(
        self,
        key: ConversationKey,
        records: Sequence[RecordT],
        *,
        expected_revision: int,
        operation_ids: Sequence[str],
    ) -> ConversationBatchCommitResult:
        operation = asyncio.to_thread(
            self._append_batch_sync,
            key,
            tuple(records),
            expected_revision=expected_revision,
            operation_ids=tuple(operation_ids),
        )
        return await asyncio.shield(operation)

    async def delete(
        self,
        key: ConversationKey,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> DeletionReceipt:
        operation = asyncio.to_thread(
            self._delete_sync,
            key,
            expected_revision=expected_revision,
            operation_id=operation_id,
        )
        return await asyncio.shield(operation)

    async def scan(self, namespace: str) -> tuple[ConversationKey, ...]:
        return await asyncio.to_thread(self._scan_sync, namespace)

    async def scan_page(
        self,
        namespace: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> ConversationPage:
        return await asyncio.to_thread(
            self._scan_page_sync,
            namespace,
            cursor=cursor,
            limit=limit,
        )

    def _create_sync(
        self,
        key: ConversationKey,
        header: HeaderT,
        records: Sequence[RecordT] = (),
        *,
        operation_id: str,
    ) -> ConversationSnapshot[HeaderT, RecordT]:
        operation = require_operation_id(operation_id)
        durable_records = tuple(records)
        try:
            path = Path(self._create_path(key))
            journal = self._write_journal_factory(path)
            with _exclusive_lock(journal):
                tombstone = _load_tombstone(self._tombstone_for(key, path))
                if tombstone is not None:
                    raise StoreAlreadyExistsError(
                        f"conversation {key!r} has a retired identity"
                    )
                if path.exists():
                    current = _load_unlocked(journal)
                    recorded_operation = _load_create_operation(path)
                    if (
                        current.header == header
                        and current.records == durable_records
                        and operation
                        == (recorded_operation or _create_operation_id(key))
                    ):
                        return ConversationSnapshot(
                            header=header,
                            records=durable_records,
                            revision=len(durable_records),
                        )
                    if (
                        current.header == header
                        and current.records == durable_records
                        and recorded_operation is None
                    ):
                        raise StoreCommitOutcomeUnknown(
                            f"create outcome for conversation {key!r} is unknown"
                        )
                    raise StoreAlreadyExistsError(
                        f"conversation {key!r} already exists"
                    )
                _write_unlocked(journal, header=header, records=durable_records)
                try:
                    _write_create_operation(
                        path,
                        operation,
                        head=(
                            _build_store_head(
                                journal,
                                durable_records,
                                record_id=self._record_id,
                                compatibility_token=self._head_compatibility_token,
                            )
                            if self._head_compatibility_token is not None
                            else None
                        ),
                    )
                except Exception as exc:
                    raise StoreCommitOutcomeUnknown(
                        f"create outcome for conversation {key!r} is unknown"
                    ) from exc
        except (StoreAlreadyExistsError, StoreCommitOutcomeUnknown):
            raise
        except Exception as exc:
            raise _data_error("create", key, exc) from exc
        return ConversationSnapshot(
            header=header,
            records=durable_records,
            revision=len(durable_records),
        )

    def _load_sync(
        self,
        key: ConversationKey,
    ) -> ConversationLoadResult[HeaderT, RecordT]:
        path = self._required_path(key)
        try:
            snapshot = (
                self._snapshot_loader(path)
                if self._snapshot_loader is not None
                else self._journal_factory(path).load()
            )
        except FileNotFoundError as exc:
            raise StoreNotFoundError(f"conversation {key!r} was not found") from exc
        except Exception as exc:
            raise _data_error("load", key, exc) from exc
        if snapshot.header is None:
            raise StoreDataError(f"conversation {key!r} has no header")
        return ConversationLoadResult(
            snapshot=ConversationSnapshot(
                header=snapshot.header,
                records=snapshot.records,
                revision=len(snapshot.records),
            ),
            diagnostics=tuple(
                _source_diagnostic(diagnostic) for diagnostic in snapshot.diagnostics
            ),
        )

    def _append_sync(
        self,
        key: ConversationKey,
        record: RecordT,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> ConversationCommitResult:
        operation = require_operation_id(operation_id)
        expected = require_revision(expected_revision, name="expected revision")
        path = self._required_path(key)
        journal = self._write_journal_factory(path)
        receipt: CommitReceipt
        source_diagnostics: tuple[ConversationSourceDiagnostic, ...] = ()
        try:
            with _exclusive_lock(journal):
                if not path.is_file():
                    raise StoreNotFoundError(f"conversation {key!r} was not found")
                projected_id = (
                    self._record_id(record) if self._record_id is not None else None
                )
                record_digest = (
                    _record_digest(journal, record)
                    if projected_id is not None
                    else None
                )
                head = (
                    _try_load_store_head(
                        path,
                        compatibility_token=self._head_compatibility_token,
                    )
                    if self._head_compatibility_token is not None
                    else None
                )
                needs_full_reconciliation = bool(
                    head is not None
                    and projected_id == operation
                    and head.operation_filter.might_contain(operation)
                )
                if needs_full_reconciliation and head is not None:
                    matching_recent = tuple(
                        item
                        for item in head.recent_records
                        if item.record_id == operation
                    )
                    if (
                        len(matching_recent) == 1
                        and matching_recent[0].unique
                        and matching_recent[0].digest == record_digest
                    ):
                        return ConversationCommitResult(
                            receipt=CommitReceipt(
                                revision=matching_recent[0].revision,
                                committed_at=self._clock(),
                                record_id=projected_id,
                            )
                        )

                if head is None or needs_full_reconciliation:
                    snapshot = _load_unlocked(journal)
                    if snapshot.header is None:
                        raise StoreDataError(f"conversation {key!r} has no header")
                    source_diagnostics = tuple(
                        _source_diagnostic(item) for item in snapshot.diagnostics
                    )
                    reconciled = self._reconcile_append(
                        key,
                        snapshot.records,
                        record,
                        operation_id=operation,
                        diagnostics=snapshot.diagnostics,
                    )
                    if reconciled is not None:
                        if (
                            not snapshot.diagnostics
                            and self._head_compatibility_token is not None
                        ):
                            _try_write_store_head(
                                path,
                                _build_store_head(
                                    journal,
                                    snapshot.records,
                                    record_id=self._record_id,
                                    compatibility_token=self._head_compatibility_token,
                                ),
                            )
                        return reconciled
                    revision = len(snapshot.records)
                    head = (
                        _build_store_head(
                            journal,
                            snapshot.records,
                            record_id=self._record_id,
                            compatibility_token=self._head_compatibility_token,
                        )
                        if not snapshot.diagnostics
                        and self._head_compatibility_token is not None
                        else None
                    )
                else:
                    revision = head.revision
                if revision != expected:
                    raise StoreConflictError(
                        f"conversation {key!r} is at revision {revision}, "
                        f"not {expected}"
                    )
                receipt = CommitReceipt(
                    revision=revision + 1,
                    committed_at=self._clock(),
                    record_id=projected_id,
                )
                advanced_head = (
                    _advance_store_head(
                        head,
                        ((projected_id, record_digest),),
                    )
                    if head is not None
                    else None
                )
                try:
                    _append_unlocked(journal, record)
                except Exception as exc:
                    raise StoreCommitOutcomeUnknown(
                        f"append outcome for conversation {key!r} is unknown"
                    ) from exc
                if advanced_head is not None:
                    _try_write_store_head(path, advanced_head, refresh_identity=True)
        except (
            StoreCommitOutcomeUnknown,
            StoreConflictError,
            StoreDataError,
            StoreNotFoundError,
        ):
            raise
        except FileNotFoundError as exc:
            raise StoreNotFoundError(f"conversation {key!r} was not found") from exc
        except Exception as exc:
            raise _data_error("append to", key, exc) from exc
        return ConversationCommitResult(
            receipt=receipt,
            diagnostics=source_diagnostics,
        )

    def _append_batch_sync(
        self,
        key: ConversationKey,
        records: Sequence[RecordT],
        *,
        expected_revision: int,
        operation_ids: Sequence[str],
    ) -> ConversationBatchCommitResult:
        durable_records = tuple(records)
        operations = tuple(require_operation_id(value) for value in operation_ids)
        if not durable_records:
            raise ValueError("append batch requires at least one record")
        if len(durable_records) != len(operations):
            raise ValueError("append batch records and operation ids must align")
        if len(set(operations)) != len(operations):
            raise StoreOperationConflictError(
                "append batch operation ids must be unique"
            )
        if self._record_id is None:
            raise ValueError("append batch requires stable record ids")
        projected_ids = tuple(self._record_id(record) for record in durable_records)
        if projected_ids != operations:
            raise StoreOperationConflictError(
                "append batch operation ids must match stable record ids"
            )
        expected = require_revision(expected_revision, name="expected revision")
        path = self._required_path(key)
        journal = self._write_journal_factory(path)
        source_diagnostics: tuple[ConversationSourceDiagnostic, ...] = ()
        try:
            with _exclusive_lock(journal):
                if not path.is_file():
                    raise StoreNotFoundError(f"conversation {key!r} was not found")
                record_digests = tuple(
                    _record_digest(journal, record) for record in durable_records
                )
                head = (
                    _try_load_store_head(
                        path,
                        compatibility_token=self._head_compatibility_token,
                    )
                    if self._head_compatibility_token is not None
                    else None
                )
                prepared = (
                    self._prepare_batch_from_head(
                        key,
                        head,
                        durable_records,
                        operations,
                        record_digests,
                        expected=expected,
                    )
                    if head is not None
                    else None
                )
                replayed_authority = prepared is None
                if prepared is None:
                    snapshot = _load_unlocked(journal)
                    if snapshot.header is None:
                        raise StoreDataError(f"conversation {key!r} has no header")
                    source_diagnostics = tuple(
                        _source_diagnostic(item) for item in snapshot.diagnostics
                    )
                    receipts, appended = self._prepare_batch_from_records(
                        key,
                        snapshot.records,
                        durable_records,
                        operations,
                        expected=expected,
                    )
                    head = (
                        _build_store_head(
                            journal,
                            snapshot.records,
                            record_id=self._record_id,
                            compatibility_token=self._head_compatibility_token,
                        )
                        if not snapshot.diagnostics
                        and self._head_compatibility_token is not None
                        else None
                    )
                else:
                    receipts, appended = prepared
                advanced_head = (
                    _advance_store_head(
                        head,
                        tuple(
                            zip(
                                operations[len(durable_records) - len(appended) :],
                                record_digests[len(durable_records) - len(appended) :],
                                strict=True,
                            )
                        ),
                    )
                    if head is not None and appended
                    else None
                )
                if appended:
                    try:
                        _append_many_unlocked(journal, appended)
                    except Exception as exc:
                        raise StoreCommitOutcomeUnknown(
                            f"append batch outcome for conversation {key!r} is unknown"
                        ) from exc
                    if advanced_head is not None:
                        _try_write_store_head(
                            path,
                            advanced_head,
                            refresh_identity=True,
                        )
                elif replayed_authority and head is not None:
                    _try_write_store_head(path, head)
        except (
            StoreCommitOutcomeUnknown,
            StoreConflictError,
            StoreDataError,
            StoreNotFoundError,
            StoreOperationConflictError,
        ):
            raise
        except FileNotFoundError as exc:
            raise StoreNotFoundError(f"conversation {key!r} was not found") from exc
        except Exception as exc:
            raise _data_error("append batch to", key, exc) from exc
        return ConversationBatchCommitResult(
            receipts,
            source_diagnostics,
        )

    def _prepare_batch_from_head(
        self,
        key: ConversationKey,
        head: _StoreHead,
        records: Sequence[RecordT],
        operations: Sequence[str],
        record_digests: Sequence[str],
        *,
        expected: int,
    ) -> tuple[list[CommitReceipt], tuple[RecordT, ...]] | None:
        revision = head.revision
        if revision < expected:
            raise StoreConflictError(
                f"conversation {key!r} is at revision {revision}, not {expected}"
            )
        receipts: list[CommitReceipt] = []
        matched = 0
        for index, (operation, digest) in enumerate(
            zip(operations, record_digests, strict=True)
        ):
            position = expected + index
            if position >= revision:
                break
            matching_recent = tuple(
                item for item in head.recent_records if item.record_id == operation
            )
            if (
                len(matching_recent) != 1
                or not matching_recent[0].unique
                or matching_recent[0].revision != position + 1
                or matching_recent[0].digest != digest
            ):
                return None
            receipts.append(
                CommitReceipt(
                    revision=position + 1,
                    committed_at=self._clock(),
                    record_id=operation,
                )
            )
            matched += 1
        if matched < len(records) and revision != expected + matched:
            raise StoreConflictError(
                f"conversation {key!r} is at revision {revision}, "
                f"not {expected + matched}"
            )
        for operation in operations[matched:]:
            if head.operation_filter.might_contain(operation):
                return None
        appended = tuple(records[matched:])
        for offset, operation in enumerate(operations[matched:], start=matched):
            receipts.append(
                CommitReceipt(
                    revision=expected + offset + 1,
                    committed_at=self._clock(),
                    record_id=operation,
                )
            )
        return receipts, appended

    def _prepare_batch_from_records(
        self,
        key: ConversationKey,
        existing_records: Sequence[RecordT],
        records: Sequence[RecordT],
        operations: Sequence[str],
        *,
        expected: int,
    ) -> tuple[list[CommitReceipt], tuple[RecordT, ...]]:
        revision = len(existing_records)
        if revision < expected:
            raise StoreConflictError(
                f"conversation {key!r} is at revision {revision}, not {expected}"
            )
        if self._record_id is None:
            raise RuntimeError("batch append requires stable record ids")
        by_record_id: dict[str, list[tuple[int, RecordT]]] = {}
        for index, existing in enumerate(existing_records):
            existing_id = self._record_id(existing)
            if existing_id is not None:
                by_record_id.setdefault(existing_id, []).append((index, existing))
        receipts: list[CommitReceipt] = []
        matched = 0
        for index, (record, operation) in enumerate(
            zip(records, operations, strict=True)
        ):
            occurrences = by_record_id.get(operation, [])
            if len(occurrences) > 1:
                raise StoreOperationConflictError(
                    f"operation {operation!r} is not unique"
                )
            position = expected + index
            if occurrences and occurrences[0] != (position, record):
                raise StoreOperationConflictError(
                    f"operation {operation!r} was reused for a different append"
                )
            if position >= revision:
                break
            if existing_records[position] != record:
                raise StoreConflictError(
                    f"conversation {key!r} diverged inside append batch"
                )
            receipts.append(
                CommitReceipt(
                    revision=position + 1,
                    committed_at=self._clock(),
                    record_id=operation,
                )
            )
            matched += 1
        if matched < len(records) and revision != expected + matched:
            raise StoreConflictError(
                f"conversation {key!r} is at revision {revision}, "
                f"not {expected + matched}"
            )
        appended = tuple(records[matched:])
        for offset, operation in enumerate(operations[matched:], start=matched):
            receipts.append(
                CommitReceipt(
                    revision=expected + offset + 1,
                    committed_at=self._clock(),
                    record_id=operation,
                )
            )
        return receipts, appended

    def _delete_sync(
        self,
        key: ConversationKey,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> DeletionReceipt:
        expected = require_revision(expected_revision, name="expected revision")
        operation = require_operation_id(operation_id)
        resolved = self._resolve_path(key)
        path = Path(resolved) if resolved is not None else Path(self._create_path(key))
        tombstone_path = self._tombstone_for(key, path)
        prior_tombstone = _load_tombstone(tombstone_path)
        if prior_tombstone is not None:
            if (
                prior_tombstone.get("operation_id") == operation
                and prior_tombstone.get("revision") == expected
            ):
                receipt = _decode_deletion_receipt(prior_tombstone)
                if path.is_file():
                    try:
                        journal = self._write_journal_factory(path)
                        with _exclusive_lock(journal):
                            path.unlink(missing_ok=True)
                    except Exception as exc:
                        raise StoreCommitOutcomeUnknown(
                            f"delete outcome for conversation {key!r} is unknown"
                        ) from exc
                self._try_delete_artifacts(path)
                return receipt
            raise StoreNotFoundError(f"conversation {key!r} was not found")
        journal = self._write_journal_factory(path)
        try:
            with _exclusive_lock(journal):
                if not path.is_file():
                    raise StoreNotFoundError(f"conversation {key!r} was not found")
                snapshot = _load_unlocked(journal)
                revision = len(snapshot.records)
                if revision != expected:
                    raise StoreConflictError(
                        f"conversation {key!r} is at revision {revision}, "
                        f"not {expected}"
                    )
                receipt = DeletionReceipt(
                    revision=revision,
                    deleted_at=self._clock(),
                    operation_id=operation,
                )
                _write_tombstone(tombstone_path, receipt)
                path.unlink()
                self._try_delete_artifacts(path)
        except (StoreCommitOutcomeUnknown, StoreConflictError, StoreNotFoundError):
            raise
        except FileNotFoundError as exc:
            raise StoreNotFoundError(f"conversation {key!r} was not found") from exc
        except Exception as exc:
            if _load_tombstone(tombstone_path) is not None:
                raise StoreCommitOutcomeUnknown(
                    f"delete outcome for conversation {key!r} is unknown"
                ) from exc
            raise _data_error("delete", key, exc) from exc
        return receipt

    def _try_delete_artifacts(self, path: Path) -> None:
        if self._delete_artifacts is None:
            return
        try:
            self._delete_artifacts(path)
        except Exception:
            # Product caches are disposable.  Failure to remove one must not
            # make an already durable conversation deletion indeterminate.
            return

    def _scan_sync(self, namespace: str) -> tuple[ConversationKey, ...]:
        keys, _ = self._scan_entries_sync(namespace)
        return keys

    def _scan_entries_sync(
        self,
        namespace: str,
    ) -> tuple[
        tuple[ConversationKey, ...],
        tuple[ConversationSourceDiagnostic, ...],
    ]:
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("conversation namespace must be a non-empty string")
        keys: set[ConversationKey] = set()
        diagnostics: list[ConversationSourceDiagnostic] = []
        try:
            paths = tuple(self._scan_paths(namespace))
        except Exception as exc:
            raise StoreDataError(
                f"conversation namespace {namespace!r} could not be scanned"
            ) from exc
        for raw_path in paths:
            path = Path(raw_path)
            try:
                key = self._key_for_path(namespace, path)
            except Exception as exc:
                diagnostics.append(
                    ConversationSourceDiagnostic(
                        code="conversation_source_discovery_failed",
                        message=str(exc),
                        source_path=path,
                    )
                )
                continue
            if key.namespace == namespace:
                keys.add(key)
        return tuple(sorted(keys)), tuple(diagnostics)

    def _scan_page_sync(
        self,
        namespace: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> ConversationPage:
        keys, diagnostics = self._scan_entries_sync(namespace)
        offset = page_offset(cursor)
        page_limit = require_page_limit(limit)
        selected = keys[offset : offset + page_limit]
        heads = []
        for key in selected:
            try:
                snapshot = self._load_sync(key).snapshot
            except Exception as exc:
                resolved = self._resolve_path(key)
                diagnostics += (
                    ConversationSourceDiagnostic(
                        code="conversation_source_load_failed",
                        message=str(exc),
                        source_path=Path(resolved) if resolved is not None else None,
                    ),
                )
                continue
            heads.append(
                ConversationHead(
                    key=key,
                    revision=snapshot.revision,
                    updated_at=conversation_content_updated_at(
                        snapshot.header,
                        snapshot.records,
                    ),
                )
            )
        next_offset = offset + len(selected)
        return ConversationPage(
            heads=tuple(heads),
            next_cursor=str(next_offset) if next_offset < len(keys) else None,
            diagnostics=diagnostics if offset == 0 else (),
        )

    def _required_path(self, key: ConversationKey) -> Path:
        try:
            resolved = self._resolve_path(key)
        except Exception as exc:
            raise _data_error("resolve", key, exc) from exc
        if resolved is None:
            raise StoreNotFoundError(f"conversation {key!r} was not found")
        path = Path(resolved)
        if not path.is_file():
            raise StoreNotFoundError(f"conversation {key!r} was not found")
        return path

    def _reconcile_append(
        self,
        key: ConversationKey,
        records: Sequence[RecordT],
        requested: RecordT,
        *,
        operation_id: str,
        diagnostics,
    ) -> ConversationCommitResult | None:
        if self._record_id is None:
            return None
        requested_id = self._record_id(requested)
        if requested_id != operation_id:
            return None
        for index, existing in enumerate(records):
            if self._record_id(existing) != requested_id:
                continue
            if existing != requested:
                raise StoreOperationConflictError(
                    f"operation {operation_id!r} was reused for a different append"
                )
            return ConversationCommitResult(
                receipt=CommitReceipt(
                    revision=index + 1,
                    committed_at=self._clock(),
                    record_id=requested_id,
                ),
                diagnostics=tuple(
                    _source_diagnostic(diagnostic) for diagnostic in diagnostics
                ),
            )
        return None

    def _tombstone_for(self, key: ConversationKey, path: Path) -> Path:
        if self._tombstone_path is not None:
            return Path(self._tombstone_path(key))
        return _default_tombstone_path(path)


def _exclusive_lock(
    journal: JsonlJournal[HeaderT, RecordT],
) -> AbstractContextManager[None]:
    if journal.lock_factory is not None:
        return journal.lock_factory(journal.path, "exclusive")
    return journal_file_lock(
        journal.path,
        "exclusive",
        lock_suffix=journal.durability.lock_suffix,
    )


def _unlocked_durability(journal: JsonlJournal[HeaderT, RecordT]):
    return replace(journal.durability, locking=False)


def _load_unlocked(journal: JsonlJournal[HeaderT, RecordT]):
    return load_jsonl(
        journal.path,
        record_codec=journal.record_codec,
        header_codec=journal.header_codec,
        format_profile=journal.format_profile,
        durability=_unlocked_durability(journal),
        load_policy=journal.load_policy,
    )


def _append_unlocked(
    journal: JsonlJournal[HeaderT, RecordT],
    record: RecordT,
) -> None:
    append_jsonl_record(
        journal.path,
        record,
        record_codec=journal.record_codec,
        format_profile=journal.format_profile,
        durability=_unlocked_durability(journal),
    )


def _append_many_unlocked(
    journal: JsonlJournal[HeaderT, RecordT],
    records: Sequence[RecordT],
) -> None:
    append_jsonl_records(
        journal.path,
        records,
        record_codec=journal.record_codec,
        format_profile=journal.format_profile,
        durability=_unlocked_durability(journal),
    )


def _source_diagnostic(diagnostic) -> ConversationSourceDiagnostic:
    return ConversationSourceDiagnostic(
        code=diagnostic.code,
        message=diagnostic.message,
        severity=diagnostic.severity,
        source_path=diagnostic.source_path,
        line_number=diagnostic.line_number,
        details=dict(diagnostic.details),
    )


def _write_unlocked(
    journal: JsonlJournal[HeaderT, RecordT],
    *,
    header: HeaderT,
    records: Sequence[RecordT],
) -> None:
    write_jsonl(
        journal.path,
        records,
        record_codec=journal.record_codec,
        header=header,
        header_codec=journal.header_codec,
        format_profile=journal.format_profile,
        durability=_unlocked_durability(journal),
    )


def _operation_filter_segment_shape(index: int) -> tuple[int, int, int]:
    """Return capacity, bit count, and hashes for one scalable Bloom segment.

    Capacity doubles while each segment receives half the remaining global false-
    positive budget. The union of all segments is therefore bounded by
    ``_OPERATION_FILTER_FALSE_POSITIVE_BUDGET`` without exponentially growing a
    fixed-capacity payload.
    """

    if index < 0 or index >= _OPERATION_FILTER_MAX_SEGMENTS:
        raise ValueError("store head operation filter has too many segments")
    capacity = _OPERATION_FILTER_INITIAL_CAPACITY << index
    false_positive_rate = _OPERATION_FILTER_FALSE_POSITIVE_BUDGET / (2 ** (index + 1))
    hashes = max(1, round(-math.log(false_positive_rate) / math.log(2)))
    raw_bits = math.ceil(
        -hashes * capacity / math.log1p(-(false_positive_rate ** (1 / hashes)))
    )
    bits = ((raw_bits + 63) // 64) * 64
    return capacity, bits, hashes


def _operation_filter_positions(
    operation_id: str,
    *,
    bit_count: int,
    hashes: int,
) -> tuple[int, ...]:
    digest = hashlib.sha256(operation_id.encode("utf-8")).digest()
    first = int.from_bytes(digest[:16], "big")
    second = int.from_bytes(digest[16:], "big") | 1
    return tuple((first + index * second) % bit_count for index in range(hashes))


def _record_digest(
    journal: JsonlJournal[HeaderT, RecordT],
    record: RecordT,
) -> str:
    encoded = journal.record_codec.encode_record(record)
    payload = json.dumps(
        encoded,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _journal_identity(path: Path) -> _JournalIdentity:
    stat = path.stat()
    return _JournalIdentity(
        device=stat.st_dev,
        inode=stat.st_ino,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        ctime_ns=stat.st_ctime_ns,
    )


def _build_store_head(
    journal: JsonlJournal[HeaderT, RecordT],
    records: Sequence[RecordT],
    *,
    record_id: RecordId[RecordT] | None,
    compatibility_token: str,
) -> _StoreHead:
    operation_filter = _OperationFilterBuilder(_OperationFilter.empty())
    seen_record_ids: set[str] = set()
    duplicate_record_ids: set[str] = set()
    recent_records: list[tuple[int, str, str]] = []
    recent_start = max(0, len(records) - _RECENT_RECORD_LIMIT)
    if record_id is not None:
        for index, record in enumerate(records):
            projected_id = record_id(record)
            if not isinstance(projected_id, str) or not projected_id.strip():
                continue
            if projected_id in seen_record_ids:
                duplicate_record_ids.add(projected_id)
            else:
                seen_record_ids.add(projected_id)
            operation_filter.add(projected_id)
            if index >= recent_start:
                recent_records.append(
                    (
                        index + 1,
                        projected_id,
                        _record_digest(journal, record),
                    )
                )
    return _StoreHead(
        compatibility_token=compatibility_token,
        revision=len(records),
        identity=_journal_identity(journal.path),
        operation_filter=operation_filter.freeze(),
        recent_records=tuple(
            _RecentRecord(
                revision=revision,
                record_id=projected_id,
                digest=digest,
                unique=projected_id not in duplicate_record_ids,
            )
            for revision, projected_id, digest in recent_records[-_RECENT_RECORD_LIMIT:]
        ),
    )


def _advance_store_head(
    head: _StoreHead,
    records: Sequence[tuple[str | None, str | None]],
) -> _StoreHead:
    operation_filter = _OperationFilterBuilder(head.operation_filter)
    recent_records = list(head.recent_records)
    revision = head.revision
    for projected_id, digest in records:
        revision += 1
        if not isinstance(projected_id, str) or not projected_id.strip():
            continue
        if not isinstance(digest, str):
            raise RuntimeError("record digest is required for a stable record id")
        unique = not operation_filter.might_contain(projected_id)
        operation_filter.add(projected_id)
        recent_records.append(
            _RecentRecord(
                revision=revision,
                record_id=projected_id,
                digest=digest,
                unique=unique,
            )
        )
    return _StoreHead(
        compatibility_token=head.compatibility_token,
        revision=revision,
        identity=head.identity,
        operation_filter=operation_filter.freeze(),
        recent_records=tuple(recent_records[-_RECENT_RECORD_LIMIT:]),
    )


def _metadata_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.store.json")


def _default_tombstone_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.deleted.json")


def _create_operation_id(key: ConversationKey) -> str:
    return f"create:{key.namespace}:{key.conversation_id}"


def _load_create_operation(
    path: Path,
) -> str | None:
    value = _load_store_metadata(path)
    if value is None:
        return None
    if "create_operation_id" not in value:
        return None
    operation_id = value.get("create_operation_id")
    return require_operation_id(operation_id)


def _write_create_operation(
    path: Path,
    operation_id: str,
    *,
    head: _StoreHead | None,
) -> None:
    metadata: dict[str, object] = {"create_operation_id": operation_id}
    if head is not None:
        metadata["head"] = _encode_store_head(head)
    _write_json_sidecar(_metadata_path(path), metadata)


def _load_store_metadata(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(_metadata_path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except OSError:
        raise
    except Exception as exc:
        raise StoreDataError("conversation Store metadata is invalid") from exc
    if not isinstance(value, dict):
        raise StoreDataError("conversation Store metadata is invalid")
    return value


def _try_load_store_head(
    path: Path,
    *,
    compatibility_token: str,
) -> _StoreHead | None:
    try:
        metadata = _load_store_metadata(path)
        if metadata is None:
            return None
        head = _decode_store_head(
            metadata.get("head"),
            compatibility_token=compatibility_token,
        )
        if head.identity != _journal_identity(path):
            return None
        return head
    except (OSError, StoreDataError, TypeError, ValueError):
        return None


def _try_write_store_head(
    path: Path,
    head: _StoreHead,
    *,
    refresh_identity: bool = False,
) -> None:
    """Best-effort cache update that never changes a durable journal outcome."""

    try:
        try:
            metadata = _load_store_metadata(path)
        except StoreDataError:
            metadata = {}
        if metadata is None:
            metadata = {}
        if refresh_identity:
            head = replace(head, identity=_journal_identity(path))
        metadata["head"] = _encode_store_head(head)
        _write_json_sidecar(_metadata_path(path), metadata)
    except Exception:
        return


def _encode_store_head(head: _StoreHead) -> dict[str, object]:
    value: dict[str, object] = {
        "version": _STORE_HEAD_VERSION,
        "compatibility_token": head.compatibility_token,
        "revision": head.revision,
        "journal": {
            "device": head.identity.device,
            "inode": head.identity.inode,
            "size": head.identity.size,
            "mtime_ns": head.identity.mtime_ns,
            "ctime_ns": head.identity.ctime_ns,
        },
        "operation_filter": {
            "segments": [
                {
                    "capacity": _operation_filter_segment_shape(index)[0],
                    "bits": len(segment.payload) * 8,
                    "hashes": segment.hashes,
                    "insertions": segment.insertions,
                    "payload": base64.b64encode(segment.payload).decode("ascii"),
                }
                for index, segment in enumerate(head.operation_filter.segments)
            ],
        },
        "recent_records": [
            {
                "revision": item.revision,
                "record_id": item.record_id,
                "digest": item.digest,
                "unique": item.unique,
            }
            for item in head.recent_records
        ],
    }
    value["checksum"] = _store_head_checksum(value)
    return value


def _decode_store_head(
    value: object,
    *,
    compatibility_token: str,
) -> _StoreHead:
    if not isinstance(value, dict):
        raise ValueError("store head is missing")
    checksum = value.get("checksum")
    checksum_payload = {key: item for key, item in value.items() if key != "checksum"}
    if not isinstance(checksum, str) or not hmac.compare_digest(
        checksum,
        _store_head_checksum(checksum_payload),
    ):
        raise ValueError("store head checksum is invalid")
    if _metadata_int(value, "version") != _STORE_HEAD_VERSION:
        raise ValueError("store head version is unsupported")
    if value.get("compatibility_token") != compatibility_token:
        raise ValueError("store head compatibility token does not match")
    revision = _metadata_int(value, "revision")
    journal = value.get("journal")
    operation_filter = value.get("operation_filter")
    recent = value.get("recent_records")
    if not isinstance(journal, dict) or not isinstance(operation_filter, dict):
        raise ValueError("store head metadata is invalid")
    if not isinstance(recent, list) or len(recent) > _RECENT_RECORD_LIMIT:
        raise ValueError("store head recent records are invalid")
    raw_segments = operation_filter.get("segments")
    if (
        not isinstance(raw_segments, list)
        or len(raw_segments) > _OPERATION_FILTER_MAX_SEGMENTS
    ):
        raise ValueError("store head operation filter segments are invalid")
    decoded_segments: list[_OperationFilterSegment] = []
    for index, raw_segment in enumerate(raw_segments):
        if not isinstance(raw_segment, dict):
            raise ValueError("store head operation filter segment is invalid")
        expected_capacity, expected_bits, expected_hashes = (
            _operation_filter_segment_shape(index)
        )
        capacity = _metadata_int(raw_segment, "capacity")
        bits = _metadata_int(raw_segment, "bits")
        hashes = _metadata_int(raw_segment, "hashes")
        insertions = _metadata_int(raw_segment, "insertions")
        raw_payload = raw_segment.get("payload")
        if (
            capacity != expected_capacity
            or bits != expected_bits
            or hashes != expected_hashes
            or insertions <= 0
            or insertions > expected_capacity
            or (index < len(raw_segments) - 1 and insertions != expected_capacity)
            or not isinstance(raw_payload, str)
        ):
            raise ValueError("store head operation filter segment is invalid")
        try:
            payload = base64.b64decode(raw_payload.encode("ascii"), validate=True)
        except (UnicodeError, binascii.Error) as exc:
            raise ValueError("store head operation filter segment is invalid") from exc
        if len(payload) != bits // 8:
            raise ValueError("store head operation filter segment length is invalid")
        decoded_segments.append(
            _OperationFilterSegment(
                payload=payload,
                insertions=insertions,
                hashes=hashes,
            )
        )
    decoded_filter = _OperationFilter(tuple(decoded_segments))
    decoded_recent: list[_RecentRecord] = []
    prior_revision = 0
    for raw_item in recent:
        if not isinstance(raw_item, dict):
            raise ValueError("store head recent record is invalid")
        item_revision = _metadata_int(raw_item, "revision")
        record_id = require_operation_id(raw_item.get("record_id"))
        digest = raw_item.get("digest")
        unique = raw_item.get("unique")
        if (
            item_revision <= prior_revision
            or item_revision > revision
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not isinstance(unique, bool)
            or not decoded_filter.might_contain(record_id)
        ):
            raise ValueError("store head recent record is invalid")
        decoded_recent.append(
            _RecentRecord(
                revision=item_revision,
                record_id=record_id,
                digest=digest,
                unique=unique,
            )
        )
        prior_revision = item_revision
    return _StoreHead(
        compatibility_token=compatibility_token,
        revision=revision,
        identity=_JournalIdentity(
            device=_metadata_int(journal, "device"),
            inode=_metadata_int(journal, "inode"),
            size=_metadata_int(journal, "size"),
            mtime_ns=_metadata_int(journal, "mtime_ns"),
            ctime_ns=_metadata_int(journal, "ctime_ns"),
        ),
        operation_filter=decoded_filter,
        recent_records=tuple(decoded_recent),
    )


def _metadata_int(value: dict[str, object], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise ValueError(f"store head {key} is invalid")
    return item


def _require_head_compatibility_token(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("head compatibility token must be a string or None")
    token = value.strip()
    if not token:
        raise ValueError("head compatibility token must be non-empty")
    if len(token) > 256:
        raise ValueError("head compatibility token must be at most 256 characters")
    return token


def _store_head_checksum(value: dict[str, object]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_tombstone(target: Path) -> dict[str, object] | None:
    value = _read_tombstone_json(target)
    if value is None:
        return None
    _validated_deletion_receipt(value)
    return value


def load_conversation_deletion_receipt(target: str | Path) -> DeletionReceipt | None:
    """Read and validate one deletion receipt without following filesystem links."""

    value = _read_tombstone_json(Path(target))
    return None if value is None else _validated_deletion_receipt(value)


def _validated_deletion_receipt(value: dict[str, object]) -> DeletionReceipt:
    try:
        return _decode_deletion_receipt(value)
    except StoreDataError:
        raise
    except Exception as exc:
        raise StoreDataError("conversation deletion tombstone is invalid") from exc


def _read_tombstone_json(target: Path) -> dict[str, object] | None:
    try:
        before = target.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StoreDataError("conversation deletion tombstone is unreadable") from exc
    if not _regular_file_status_no_follow(before):
        raise StoreDataError("conversation deletion tombstone is unsafe")
    if before.st_size > _TOMBSTONE_MAX_BYTES:
        raise StoreDataError("conversation deletion tombstone exceeds the read limit")
    descriptor = -1
    parent_descriptor = -1
    try:
        descriptor, parent_descriptor = _open_file_no_follow(target)
        opened = os.fstat(descriptor)
        if not _same_file_status(before, opened):
            raise StoreDataError("conversation deletion tombstone changed before read")
        remaining = opened.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                raise StoreDataError("conversation deletion tombstone was truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        current = target.lstat()
        if not _same_file_status(before, after) or not _same_file_status(
            before, current
        ):
            raise StoreDataError("conversation deletion tombstone changed while read")
        value = json.loads(b"".join(chunks).decode("utf-8"))
    except StoreDataError:
        raise
    except Exception as exc:
        raise StoreDataError("conversation deletion tombstone is invalid") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)
    if not isinstance(value, dict):
        raise StoreDataError("conversation deletion tombstone is invalid")
    return value


def _open_file_no_follow(path: Path) -> tuple[int, int]:
    file_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    file_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    if os.name != "nt" and directory_flag:
        parent_flags = os.O_RDONLY | directory_flag
        parent_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        parent = os.open(path.parent, parent_flags)
        try:
            return os.open(path.name, file_flags, dir_fd=parent), parent
        except BaseException:
            os.close(parent)
            raise
    return os.open(path, file_flags), -1


def _regular_file_status_no_follow(value: os.stat_result) -> bool:
    return stat.S_ISREG(value.st_mode) and not (
        stat.S_ISLNK(value.st_mode)
        or bool(
            getattr(value, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    )


def _same_file_status(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_size,
        right.st_mtime_ns,
        right.st_ctime_ns,
    )


def _write_tombstone(path: Path, receipt: DeletionReceipt) -> None:
    _write_json_sidecar(
        path,
        {
            "revision": receipt.revision,
            "deleted_at": receipt.deleted_at.isoformat(),
            "operation_id": receipt.operation_id,
        },
    )


def _decode_deletion_receipt(value: dict[str, object]) -> DeletionReceipt:
    revision = require_revision(value.get("revision"), name="deleted revision")
    deleted_at = value.get("deleted_at")
    operation_id = value.get("operation_id")
    if not isinstance(deleted_at, str):
        raise StoreDataError("conversation deletion tombstone is invalid")
    try:
        timestamp = datetime.fromisoformat(deleted_at)
    except ValueError as exc:
        raise StoreDataError("conversation deletion tombstone is invalid") from exc
    return DeletionReceipt(
        revision=revision,
        deleted_at=timestamp,
        operation_id=require_operation_id(operation_id),
    )


def _write_json_sidecar(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        temp.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)
    except BaseException:
        with suppress(FileNotFoundError):
            temp.unlink()
        raise


def _data_error(
    action: str,
    key: ConversationKey,
    error: Exception,
) -> StoreDataError:
    detail = error.code if isinstance(error, JournalFileError) else type(error).__name__
    return StoreDataError(f"failed to {action} conversation {key!r}: {detail}")


__all__ = ["FileConversationStore", "load_conversation_deletion_receipt"]
