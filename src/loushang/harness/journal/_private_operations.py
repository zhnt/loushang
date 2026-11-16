"""Fixed private JSONL operation scopes, without Product selection policy.

The same caller object owns its original path and Journal profiles. Products
project records, choose transitions/admission and construct domain failures.
Sync and async exits intentionally preserve their different exception scopes.
"""

from __future__ import annotations

import asyncio
import os
import stat
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractContextManager, asynccontextmanager, contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Generic, Literal, TypeVar

from .codec import JournalCodecError, JournalRecordCodec
from .jsonl import (
    JournalFileError,
    JournalLockUnavailable,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from .types import (
    DURABLE_LOCKED_JOURNAL,
    JournalFormatProfile,
    JournalLoadPolicy,
    JsonlSnapshot,
)

RecordT = TypeVar("RecordT")
SnapshotT = TypeVar("SnapshotT")
_JournalFailure = Literal["busy", "corrupt", "unsafe", "write_failed"]
_PreparedMutation = tuple[RecordT | None, Callable[[], SnapshotT], Callable[[], int]]


class _PrivateJournalOperations(Generic[RecordT, SnapshotT]):
    """One same-object mechanical Journal profile; no state interpretation."""

    _storage_label: str
    _timeout_message: str
    _format_profile: JournalFormatProfile

    def __init__(self, path: str | Path) -> None:
        self._path = Path(os.path.abspath(Path(path).expanduser()))
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="raise")

    @property
    def _record_codec(self) -> JournalRecordCodec[RecordT]:
        raise NotImplementedError

    @property
    def _domain_error_type(self) -> type[Exception]:
        raise NotImplementedError

    def _journal_error(self, kind: _JournalFailure, *, context: int = 0) -> Exception:
        raise NotImplementedError

    def _validate_records(self, records: tuple[RecordT, ...]) -> None:
        raise NotImplementedError

    def _project_snapshot(self, records: tuple[RecordT, ...]) -> SnapshotT:
        raise NotImplementedError

    def _require_admitted(self, snapshot: SnapshotT) -> None:
        raise NotImplementedError

    def _read_snapshot(self) -> SnapshotT:
        if not self._path.exists():
            return self._project_snapshot(())
        try:
            with self._private_lock(create=False, mode="shared"):
                return self._snapshot_unlocked()
        except FileNotFoundError:
            return self._project_snapshot(())

    async def _read_snapshot_async(self, *, timeout_seconds: float) -> SnapshotT:
        if not self._path.exists():
            return self._project_snapshot(())
        context = await self._acquire_private_lock_async(
            create=False, mode="shared", timeout_seconds=timeout_seconds
        )
        try:
            return self._snapshot_unlocked()
        finally:
            context.__exit__(None, None, None)

    def _admitted_run_iterator(self) -> Iterator[SnapshotT]:
        with self._private_lock(create=True, mode="exclusive"):
            snapshot = self._snapshot_unlocked()
            self._require_admitted(snapshot)
            yield snapshot

    @asynccontextmanager
    async def _admitted_run_context_async(
        self, *, timeout_seconds: float
    ) -> AsyncIterator[SnapshotT]:
        context = await self._acquire_private_lock_async(
            create=True, mode="exclusive", timeout_seconds=timeout_seconds
        )
        try:
            snapshot = self._snapshot_unlocked()
            self._require_admitted(snapshot)
            yield snapshot
        finally:
            context.__exit__(None, None, None)

    def _mutate_locked(
        self,
        prepare: Callable[[tuple[RecordT, ...]], _PreparedMutation[RecordT, SnapshotT]],
    ) -> SnapshotT:
        with self._private_lock(create=True, mode="exclusive"):
            return self._mutate_unlocked(prepare)

    async def _mutate_locked_async(
        self,
        prepare: Callable[[tuple[RecordT, ...]], _PreparedMutation[RecordT, SnapshotT]],
        *,
        timeout_seconds: float,
    ) -> SnapshotT:
        context = await self._acquire_private_lock_async(
            create=True, mode="exclusive", timeout_seconds=timeout_seconds
        )
        try:
            return self._mutate_unlocked(prepare)
        finally:
            context.__exit__(None, None, None)

    def _mutate_unlocked(
        self,
        prepare: Callable[[tuple[RecordT, ...]], _PreparedMutation[RecordT, SnapshotT]],
    ) -> SnapshotT:
        record, result, error_context = prepare(self._load_unlocked())
        if record is not None:
            try:
                append_jsonl_record(
                    self._path,
                    record,
                    record_codec=self._record_codec,
                    format_profile=self._format_profile,
                    durability=self._unlocked_durability,
                )
            except (JournalCodecError, JournalFileError, OSError) as error:
                raise self._journal_error(
                    "write_failed", context=error_context()
                ) from error
        return result()

    async def _acquire_private_lock_async(
        self,
        *,
        create: bool,
        mode: Literal["exclusive", "shared"],
        timeout_seconds: float,
    ) -> AbstractContextManager[None]:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise ValueError(self._timeout_message)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(timeout_seconds)
        while True:
            candidate = self._private_lock(create=create, mode=mode, blocking=False)
            try:
                candidate.__enter__()
            except JournalLockUnavailable:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise self._journal_error("busy") from None
                await asyncio.sleep(min(0.01, remaining))
            else:
                return candidate

    def _snapshot_unlocked(self) -> SnapshotT:
        return self._project_snapshot(self._load_unlocked())

    def _load_unlocked(self) -> tuple[RecordT, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, RecordT] = load_jsonl(
                self._path,
                record_codec=self._record_codec,
                format_profile=self._format_profile,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            records = snapshot.records
            self._validate_records(records)
            return records
        except (JournalCodecError, JournalFileError, OSError, ValueError) as error:
            raise self._journal_error("corrupt") from error

    def _private_lock(
        self,
        *,
        create: bool,
        mode: Literal["exclusive", "shared"],
        blocking: bool = True,
    ) -> AbstractContextManager[None]:
        return self._private_lock_context(create=create, mode=mode, blocking=blocking)

    @contextmanager
    def _private_lock_context(
        self,
        *,
        create: bool,
        mode: Literal["exclusive", "shared"],
        blocking: bool,
    ) -> Iterator[None]:
        try:
            if create:
                self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _assert_private_storage(
                self._path, require_parent=create, label=self._storage_label
            )
            with journal_file_lock(
                self._path,
                mode,
                lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
                blocking=blocking,
                create=create,
            ):
                _assert_private_storage(
                    self._path, require_parent=True, label=self._storage_label
                )
                yield
        except self._domain_error_type:
            raise
        except JournalLockUnavailable:
            raise
        except OSError as error:
            raise self._journal_error("unsafe") from error


def _assert_private_storage(path: Path, *, require_parent: bool, label: str) -> None:
    parent = path.parent
    try:
        parent_metadata = parent.lstat()
    except FileNotFoundError:
        if require_parent:
            raise
        return
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or parent.is_symlink()
        or (os.name == "posix" and parent_metadata.st_mode & 0o077)
        or not _owned_by_current_user(parent_metadata)
    ):
        raise OSError(f"{label} parent is not private")
    _assert_private_regular_file(path, required=False, label=label)
    _assert_private_regular_file(
        path.with_name(f"{path.name}{DURABLE_LOCKED_JOURNAL.lock_suffix}"),
        required=False,
        label=label,
    )


def _assert_private_regular_file(path: Path, *, required: bool, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if required:
            raise
        return
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_nlink != 1
        or (os.name == "posix" and metadata.st_mode & 0o077)
        or not _owned_by_current_user(metadata)
    ):
        raise OSError(f"{label} file is not private")


def _owned_by_current_user(metadata: os.stat_result) -> bool:
    getuid = getattr(os, "geteuid", None)
    return not callable(getuid) or metadata.st_uid == getuid()
