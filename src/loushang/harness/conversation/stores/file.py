from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager, suppress
from dataclasses import replace
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
Clock = Callable[[], datetime]
RecordId = Callable[[RecordT], str | None]
TombstonePath = Callable[[ConversationKey], Path]


class FileConversationStore(Generic[HeaderT, RecordT]):
    """File-backed Store whose layout and codecs are Product supplied."""

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
                    _write_create_operation(path, operation)
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
            snapshot = self._journal_factory(path).load()
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
        try:
            with _exclusive_lock(journal):
                if not path.is_file():
                    raise StoreNotFoundError(f"conversation {key!r} was not found")
                snapshot = _load_unlocked(journal)
                if snapshot.header is None:
                    raise StoreDataError(f"conversation {key!r} has no header")
                reconciled = self._reconcile_append(
                    key,
                    snapshot.records,
                    record,
                    operation_id=operation,
                    diagnostics=snapshot.diagnostics,
                )
                if reconciled is not None:
                    return reconciled
                revision = len(snapshot.records)
                if revision != expected:
                    raise StoreConflictError(
                        f"conversation {key!r} is at revision {revision}, "
                        f"not {expected}"
                    )
                receipt = CommitReceipt(
                    revision=revision + 1,
                    committed_at=self._clock(),
                    record_id=(
                        self._record_id(record) if self._record_id is not None else None
                    ),
                )
                try:
                    _append_unlocked(journal, record)
                except Exception as exc:
                    raise StoreCommitOutcomeUnknown(
                        f"append outcome for conversation {key!r} is unknown"
                    ) from exc
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
            diagnostics=tuple(
                _source_diagnostic(diagnostic) for diagnostic in snapshot.diagnostics
            ),
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
        try:
            with _exclusive_lock(journal):
                if not path.is_file():
                    raise StoreNotFoundError(f"conversation {key!r} was not found")
                snapshot = _load_unlocked(journal)
                if snapshot.header is None:
                    raise StoreDataError(f"conversation {key!r} has no header")
                revision = len(snapshot.records)
                if revision < expected:
                    raise StoreConflictError(
                        f"conversation {key!r} is at revision {revision}, "
                        f"not {expected}"
                    )
                by_record_id: dict[str, list[tuple[int, RecordT]]] = {}
                for index, existing in enumerate(snapshot.records):
                    existing_id = self._record_id(existing)
                    if existing_id is not None:
                        by_record_id.setdefault(existing_id, []).append(
                            (index, existing)
                        )
                receipts: list[CommitReceipt] = []
                matched = 0
                for index, (record, operation) in enumerate(
                    zip(durable_records, operations, strict=True)
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
                    if snapshot.records[position] != record:
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
                if matched < len(durable_records) and revision != expected + matched:
                    raise StoreConflictError(
                        f"conversation {key!r} is at revision {revision}, "
                        f"not {expected + matched}"
                    )
                appended = durable_records[matched:]
                for offset, operation in enumerate(
                    operations[matched:],
                    start=matched,
                ):
                    receipts.append(
                        CommitReceipt(
                            revision=expected + offset + 1,
                            committed_at=self._clock(),
                            record_id=operation,
                        )
                    )
                if appended:
                    try:
                        _append_many_unlocked(journal, appended)
                    except Exception as exc:
                        raise StoreCommitOutcomeUnknown(
                            f"append batch outcome for conversation {key!r} is unknown"
                        ) from exc
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
            tuple(_source_diagnostic(item) for item in snapshot.diagnostics),
        )

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


def _metadata_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.store.json")


def _default_tombstone_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.deleted.json")


def _create_operation_id(key: ConversationKey) -> str:
    return f"create:{key.namespace}:{key.conversation_id}"


def _load_create_operation(
    path: Path,
) -> str | None:
    metadata_path = _metadata_path(path)
    try:
        value = json.loads(metadata_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:
        raise StoreDataError("conversation Store metadata is invalid") from exc
    operation_id = value.get("create_operation_id") if isinstance(value, dict) else None
    return require_operation_id(operation_id)


def _write_create_operation(path: Path, operation_id: str) -> None:
    _write_json_sidecar(
        _metadata_path(path),
        {"create_operation_id": operation_id},
    )


def _load_tombstone(target: Path) -> dict[str, object] | None:
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:
        raise StoreDataError("conversation deletion tombstone is invalid") from exc
    if not isinstance(value, dict):
        raise StoreDataError("conversation deletion tombstone is invalid")
    return value


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


__all__ = ["FileConversationStore"]
