from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Generic, Protocol, TypeVar, runtime_checkable

HeaderT = TypeVar("HeaderT")
RecordT = TypeVar("RecordT")
BatchRecordT = TypeVar("BatchRecordT", contravariant=True)


def _require_text(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def require_revision(value: object, *, name: str = "revision") -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def require_operation_id(value: object) -> str:
    return _require_text(value, name="conversation operation id")


@dataclass(frozen=True, order=True)
class ConversationKey:
    """Backend-neutral identity for a stored conversation."""

    namespace: str
    conversation_id: str

    def __post_init__(self) -> None:
        _require_text(self.namespace, name="conversation namespace")
        _require_text(self.conversation_id, name="conversation id")


@dataclass(frozen=True)
class ConversationSnapshot(Generic[HeaderT, RecordT]):
    """One authoritative conversation snapshot and its concurrency token."""

    header: HeaderT
    records: tuple[RecordT, ...]
    revision: int

    def __init__(
        self,
        *,
        header: HeaderT,
        records: Sequence[RecordT],
        revision: int,
    ) -> None:
        durable_records = tuple(records)
        normalized_revision = require_revision(revision)
        if normalized_revision != len(durable_records):
            raise ValueError("snapshot revision must equal its record count")
        object.__setattr__(self, "header", header)
        object.__setattr__(self, "records", durable_records)
        object.__setattr__(self, "revision", normalized_revision)


@dataclass(frozen=True)
class CommitReceipt:
    """Result of one successful durable append."""

    revision: int
    committed_at: datetime
    record_id: str | None = None

    def __post_init__(self) -> None:
        require_revision(self.revision)
        if self.revision < 1:
            raise ValueError("commit receipt revision must be positive")
        if not isinstance(self.committed_at, datetime):
            raise TypeError("commit timestamp must be a datetime")
        if self.committed_at.tzinfo is None:
            raise ValueError("commit timestamp must be timezone-aware")
        if self.record_id is not None:
            _require_text(self.record_id, name="committed record id")


@dataclass(frozen=True)
class ConversationSourceDiagnostic:
    """A recoverable physical-source fact reported by a Store provider."""

    code: str
    message: str
    severity: str = "warning"
    source_path: Path | None = None
    line_number: int | None = None
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ConversationLoadResult(Generic[HeaderT, RecordT]):
    snapshot: ConversationSnapshot[HeaderT, RecordT]
    diagnostics: tuple[ConversationSourceDiagnostic, ...] = ()


@dataclass(frozen=True)
class ConversationCommitResult:
    receipt: CommitReceipt
    diagnostics: tuple[ConversationSourceDiagnostic, ...] = ()


@dataclass(frozen=True)
class ConversationBatchCommitResult:
    """Receipts for one ordered, revision-contiguous append batch."""

    receipts: tuple[CommitReceipt, ...]
    diagnostics: tuple[ConversationSourceDiagnostic, ...] = ()

    def __init__(
        self,
        receipts: Sequence[CommitReceipt],
        diagnostics: Sequence[ConversationSourceDiagnostic] = (),
    ) -> None:
        durable_receipts = tuple(receipts)
        if not durable_receipts:
            raise ValueError("batch commit result requires at least one receipt")
        revisions = tuple(receipt.revision for receipt in durable_receipts)
        if revisions != tuple(range(revisions[0], revisions[0] + len(revisions))):
            raise ValueError("batch commit receipt revisions must be contiguous")
        object.__setattr__(self, "receipts", durable_receipts)
        object.__setattr__(self, "diagnostics", tuple(diagnostics))


@dataclass(frozen=True)
class DeletionReceipt:
    revision: int
    deleted_at: datetime
    operation_id: str

    def __post_init__(self) -> None:
        require_revision(self.revision, name="deleted revision")
        if not isinstance(self.deleted_at, datetime) or self.deleted_at.tzinfo is None:
            raise ValueError("deletion timestamp must be a timezone-aware datetime")
        _require_text(self.operation_id, name="deletion operation id")


@dataclass(frozen=True)
class ConversationHead:
    """Lightweight authoritative metadata returned during provider discovery."""

    key: ConversationKey
    revision: int
    updated_at: datetime

    def __post_init__(self) -> None:
        require_revision(self.revision)
        if not isinstance(self.updated_at, datetime):
            raise TypeError("conversation update timestamp must be a datetime")
        if self.updated_at.tzinfo is None:
            raise ValueError("conversation update timestamp must be timezone-aware")


@dataclass(frozen=True)
class ConversationPage:
    heads: tuple[ConversationHead, ...]
    next_cursor: str | None = None
    diagnostics: tuple[ConversationSourceDiagnostic, ...] = ()


@dataclass(frozen=True, order=True)
class ConversationLocator:
    """Federated identity: provider identity plus provider-local key."""

    provider_id: str
    key: ConversationKey

    def __post_init__(self) -> None:
        _require_text(self.provider_id, name="conversation provider id")


class ConversationStoreError(RuntimeError):
    """Base error raised by a conversation storage provider."""


class StoreAlreadyExistsError(ConversationStoreError):
    """Raised when creating a conversation whose key already exists."""


class StoreNotFoundError(ConversationStoreError):
    """Raised when a conversation key cannot be resolved."""


class StoreConflictError(ConversationStoreError):
    """Raised when optimistic revision validation fails."""


class StoreDataError(ConversationStoreError):
    """Raised when persisted conversation data cannot be read or written."""


class StoreOperationConflictError(StoreConflictError):
    """Raised when one operation id is reused for a different request."""


class StoreCommitOutcomeUnknown(ConversationStoreError):
    """Raised when a provider cannot prove whether a durable commit completed."""


@runtime_checkable
class ConversationStore(Protocol[HeaderT, RecordT]):
    """Asynchronous persistence port for one conversation record stream."""

    async def create(
        self,
        key: ConversationKey,
        header: HeaderT,
        records: Sequence[RecordT] = (),
        *,
        operation_id: str,
    ) -> ConversationSnapshot[HeaderT, RecordT]: ...

    async def load(
        self,
        key: ConversationKey,
    ) -> ConversationLoadResult[HeaderT, RecordT]: ...

    async def append(
        self,
        key: ConversationKey,
        record: RecordT,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> ConversationCommitResult: ...

    async def delete(
        self,
        key: ConversationKey,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> DeletionReceipt: ...

    async def scan(self, namespace: str) -> tuple[ConversationKey, ...]: ...

    async def scan_page(
        self,
        namespace: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> ConversationPage: ...


@runtime_checkable
class ConversationBatchStore(Protocol[BatchRecordT]):
    """Optional Store extension for one-lock, one-sync contiguous appends."""

    async def append_batch(
        self,
        key: ConversationKey,
        records: Sequence[BatchRecordT],
        *,
        expected_revision: int,
        operation_ids: Sequence[str],
    ) -> ConversationBatchCommitResult: ...


@dataclass(frozen=True)
class ConversationProviderBinding(Generic[HeaderT, RecordT]):
    """One registered Store namespace addressable by a stable provider id."""

    provider_id: str
    namespace: str
    store: ConversationStore[HeaderT, RecordT]

    def __post_init__(self) -> None:
        _require_text(self.provider_id, name="conversation provider id")
        _require_text(self.namespace, name="conversation namespace")


def conversation_content_updated_at(
    header: object,
    records: Sequence[object],
) -> datetime:
    """Infer stable update time from content, never filesystem metadata."""

    source = records[-1] if records else header
    value = getattr(source, "created_at", None)
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return datetime.fromtimestamp(0, UTC)


def require_page_limit(limit: object) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("conversation page limit must be an integer")
    if limit < 1:
        raise ValueError("conversation page limit must be positive")
    return limit


def page_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not isinstance(cursor, str) or not cursor.isdecimal():
        raise ValueError("conversation page cursor is invalid")
    return int(cursor)


__all__ = [
    "CommitReceipt",
    "ConversationBatchCommitResult",
    "ConversationBatchStore",
    "ConversationCommitResult",
    "ConversationHead",
    "ConversationKey",
    "ConversationLoadResult",
    "ConversationLocator",
    "ConversationPage",
    "ConversationProviderBinding",
    "ConversationSourceDiagnostic",
    "ConversationSnapshot",
    "ConversationStore",
    "ConversationStoreError",
    "DeletionReceipt",
    "StoreAlreadyExistsError",
    "StoreConflictError",
    "StoreCommitOutcomeUnknown",
    "StoreDataError",
    "StoreNotFoundError",
    "StoreOperationConflictError",
    "conversation_content_updated_at",
    "page_offset",
    "require_page_limit",
    "require_operation_id",
    "require_revision",
]
