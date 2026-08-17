from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
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
    DeletionReceipt,
    StoreAlreadyExistsError,
    StoreConflictError,
    StoreNotFoundError,
    StoreOperationConflictError,
    conversation_content_updated_at,
    page_offset,
    require_operation_id,
    require_page_limit,
    require_revision,
)

HeaderT = TypeVar("HeaderT")
RecordT = TypeVar("RecordT")
Clock = Callable[[], datetime]
RecordId = Callable[[RecordT], str | None]


class MemoryConversationStore(Generic[HeaderT, RecordT]):
    """Deterministic in-memory implementation of ``ConversationStore``."""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        record_id: RecordId[RecordT] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._record_id = record_id
        self._snapshots: dict[
            ConversationKey,
            ConversationSnapshot[HeaderT, RecordT],
        ] = {}
        self._create_operations: dict[
            str,
            tuple[ConversationKey, ConversationSnapshot[HeaderT, RecordT]],
        ] = {}
        self._append_operations: dict[
            str,
            tuple[ConversationKey, RecordT, ConversationCommitResult],
        ] = {}
        self._delete_operations: dict[str, tuple[ConversationKey, DeletionReceipt]] = {}
        self._tombstones: set[ConversationKey] = set()

    async def create(
        self,
        key: ConversationKey,
        header: HeaderT,
        records: Sequence[RecordT] = (),
        *,
        operation_id: str,
    ) -> ConversationSnapshot[HeaderT, RecordT]:
        operation = require_operation_id(operation_id)
        requested = ConversationSnapshot(
            header=header,
            records=records,
            revision=len(records),
        )
        previous = self._create_operations.get(operation)
        if previous is not None:
            previous_key, previous_snapshot = previous
            if previous_key == key and previous_snapshot == requested:
                return previous_snapshot
            raise StoreOperationConflictError(
                f"operation {operation!r} was reused for a different create"
            )
        if key in self._snapshots or key in self._tombstones:
            raise StoreAlreadyExistsError(f"conversation {key!r} already exists")
        self._snapshots[key] = requested
        self._create_operations[operation] = (key, requested)
        return requested

    async def load(
        self,
        key: ConversationKey,
    ) -> ConversationLoadResult[HeaderT, RecordT]:
        try:
            return ConversationLoadResult(self._snapshots[key])
        except KeyError as exc:
            raise StoreNotFoundError(f"conversation {key!r} was not found") from exc

    async def append(
        self,
        key: ConversationKey,
        record: RecordT,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> ConversationCommitResult:
        operation = require_operation_id(operation_id)
        previous = self._append_operations.get(operation)
        if previous is not None:
            previous_key, previous_record, previous_result = previous
            if previous_key == key and previous_record == record:
                return previous_result
            raise StoreOperationConflictError(
                f"operation {operation!r} was reused for a different append"
            )
        expected = require_revision(expected_revision, name="expected revision")
        snapshot = (await self.load(key)).snapshot
        if snapshot.revision != expected:
            raise StoreConflictError(
                f"conversation {key!r} is at revision {snapshot.revision}, "
                f"not {expected}"
            )
        revision = snapshot.revision + 1
        receipt = CommitReceipt(
            revision=revision,
            committed_at=self._clock(),
            record_id=self._record_id(record) if self._record_id is not None else None,
        )
        self._snapshots[key] = ConversationSnapshot(
            header=snapshot.header,
            records=(*snapshot.records, record),
            revision=revision,
        )
        result = ConversationCommitResult(receipt)
        self._append_operations[operation] = (key, record, result)
        return result

    async def append_batch(
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
        snapshot = (await self.load(key)).snapshot
        if snapshot.revision < expected:
            raise StoreConflictError(
                f"conversation {key!r} is at revision {snapshot.revision}, "
                f"not {expected}"
            )

        previous_results: list[ConversationCommitResult | None] = []
        for index, (record, operation) in enumerate(
            zip(durable_records, operations, strict=True)
        ):
            previous = self._append_operations.get(operation)
            if previous is None:
                previous_results.append(None)
                continue
            previous_key, previous_record, previous_result = previous
            if previous_key != key or previous_record != record:
                raise StoreOperationConflictError(
                    f"operation {operation!r} was reused for a different append"
                )
            if previous_result.receipt.revision != expected + index + 1:
                raise StoreOperationConflictError(
                    f"operation {operation!r} has a different revision"
                )
            previous_results.append(previous_result)

        receipts: list[CommitReceipt] = []
        matched = 0
        for index, (record, operation) in enumerate(
            zip(durable_records, operations, strict=True)
        ):
            position = expected + index
            if position >= snapshot.revision:
                break
            if snapshot.records[position] != record:
                raise StoreConflictError(
                    f"conversation {key!r} diverged inside append batch"
                )
            selected_previous = previous_results[index]
            receipt = (
                selected_previous.receipt
                if selected_previous is not None
                else CommitReceipt(
                    revision=position + 1,
                    committed_at=self._clock(),
                    record_id=operation,
                )
            )
            receipts.append(receipt)
            matched += 1

        if matched < len(durable_records) and snapshot.revision != expected + matched:
            raise StoreConflictError(
                f"conversation {key!r} is at revision {snapshot.revision}, "
                f"not {expected + matched}"
            )

        appended = durable_records[matched:]
        for offset, (record, operation) in enumerate(
            zip(appended, operations[matched:], strict=True),
            start=matched,
        ):
            receipt = CommitReceipt(
                revision=expected + offset + 1,
                committed_at=self._clock(),
                record_id=operation,
            )
            receipts.append(receipt)
            self._append_operations[operation] = (
                key,
                record,
                ConversationCommitResult(receipt),
            )
        if appended:
            self._snapshots[key] = ConversationSnapshot(
                header=snapshot.header,
                records=(*snapshot.records, *appended),
                revision=snapshot.revision + len(appended),
            )
        return ConversationBatchCommitResult(receipts)

    async def delete(
        self,
        key: ConversationKey,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> DeletionReceipt:
        operation = require_operation_id(operation_id)
        previous = self._delete_operations.get(operation)
        if previous is not None:
            previous_key, previous_receipt = previous
            if previous_key == key:
                return previous_receipt
            raise StoreOperationConflictError(
                f"operation {operation!r} was reused for a different delete"
            )
        try:
            snapshot = self._snapshots[key]
        except KeyError as exc:
            raise StoreNotFoundError(f"conversation {key!r} was not found") from exc
        expected = require_revision(expected_revision, name="expected revision")
        if snapshot.revision != expected:
            raise StoreConflictError(
                f"conversation {key!r} is at revision {snapshot.revision}, "
                f"not {expected}"
            )
        receipt = DeletionReceipt(
            revision=snapshot.revision,
            deleted_at=self._clock(),
            operation_id=operation,
        )
        del self._snapshots[key]
        self._tombstones.add(key)
        self._delete_operations[operation] = (key, receipt)
        return receipt

    async def scan(self, namespace: str) -> tuple[ConversationKey, ...]:
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("conversation namespace must be a non-empty string")
        return tuple(
            sorted(key for key in self._snapshots if key.namespace == namespace)
        )

    async def scan_page(
        self,
        namespace: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> ConversationPage:
        keys = await self.scan(namespace)
        offset = page_offset(cursor)
        page_limit = require_page_limit(limit)
        selected = keys[offset : offset + page_limit]
        heads = tuple(
            ConversationHead(
                key=key,
                revision=self._snapshots[key].revision,
                updated_at=conversation_content_updated_at(
                    self._snapshots[key].header,
                    self._snapshots[key].records,
                ),
            )
            for key in selected
        )
        next_offset = offset + len(selected)
        return ConversationPage(
            heads=heads,
            next_cursor=str(next_offset) if next_offset < len(keys) else None,
        )


__all__ = ["MemoryConversationStore"]
