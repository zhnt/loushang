"""Durable Product-owned selection control for the explicit AppHost canary."""

from __future__ import annotations

import asyncio
import os
import re
import stat
from collections.abc import AsyncIterator, Iterator
from contextlib import AbstractContextManager, asynccontextmanager, contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast

from loushang.foundation.platform_paths import PlatformPaths, resolve_platform_paths
from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JournalLockUnavailable,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)

CODING_APPHOST_CANARY_CONTROL_VERSION = 1

CanaryControlOperation = Literal["enable", "rollback"]
CanaryControlState = Literal["unconfigured", "enabled", "disabled"]

_OPERATION_ID = re.compile(r"[0-9a-f]{32}\Z")


class CodingAppHostCanaryControlError(RuntimeError):
    """Stable failure from the Product-owned canary selection authority."""

    def __init__(
        self,
        *,
        code: str,
        path: Path,
        selection_generation: int = 0,
    ) -> None:
        if type(selection_generation) is not int or selection_generation < 0:
            raise ValueError("Coding AppHost canary error generation is invalid")
        self.code = code
        self.path = Path(path)
        self.selection_generation = selection_generation
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CodingAppHostCanaryControlRecordV1:
    """One immutable enable/rollback transition in the Product journal."""

    operation: CanaryControlOperation
    state: Literal["enabled", "disabled"]
    selection_generation: int
    record_revision: int
    operation_id: str
    record_version: int = CODING_APPHOST_CANARY_CONTROL_VERSION

    def __post_init__(self) -> None:
        expected_state = "enabled" if self.operation == "enable" else "disabled"
        if self.operation not in {"enable", "rollback"} or self.state != expected_state:
            raise ValueError("Coding AppHost canary control transition is invalid")
        if type(self.selection_generation) is not int or self.selection_generation < 1:
            raise ValueError("Coding AppHost canary selection generation is invalid")
        if type(self.record_revision) is not int or self.record_revision < 1:
            raise ValueError("Coding AppHost canary control revision is invalid")
        if _OPERATION_ID.fullmatch(self.operation_id) is None:
            raise ValueError("Coding AppHost canary control operation is invalid")
        if (
            type(self.record_version) is not int
            or self.record_version != CODING_APPHOST_CANARY_CONTROL_VERSION
        ):
            raise ValueError("Coding AppHost canary control record is unsupported")

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "operationId": self.operation_id,
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
            "selectionGeneration": self.selection_generation,
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingAppHostCanaryControlRecordV1:
        if not isinstance(value, dict) or set(value) != {
            "operation",
            "operationId",
            "recordRevision",
            "recordVersion",
            "selectionGeneration",
            "state",
        }:
            raise ValueError("Coding AppHost canary control record fields are invalid")
        operation = value["operation"]
        state = value["state"]
        operation_id = value["operationId"]
        generation = value["selectionGeneration"]
        revision = value["recordRevision"]
        version = value["recordVersion"]
        if (
            operation not in {"enable", "rollback"}
            or state not in {"enabled", "disabled"}
            or not isinstance(operation_id, str)
            or type(generation) is not int
            or type(revision) is not int
            or type(version) is not int
        ):
            raise ValueError("Coding AppHost canary control record is invalid")
        return cls(
            operation=cast(CanaryControlOperation, operation),
            state=cast(Literal["enabled", "disabled"], state),
            selection_generation=generation,
            record_revision=revision,
            operation_id=operation_id,
            record_version=version,
        )


@dataclass(frozen=True, slots=True)
class CodingAppHostCanaryControlSnapshotV1:
    """Current bounded selection fact; generation zero is fail-closed."""

    state: CanaryControlState
    selection_generation: int
    record_revision: int

    def __post_init__(self) -> None:
        if self.state not in {"unconfigured", "enabled", "disabled"}:
            raise ValueError("Coding AppHost canary control state is invalid")
        if type(self.selection_generation) is not int or self.selection_generation < 0:
            raise ValueError("Coding AppHost canary selection generation is invalid")
        if type(self.record_revision) is not int or self.record_revision < 0:
            raise ValueError("Coding AppHost canary control revision is invalid")
        if self.state == "unconfigured":
            if self.selection_generation != 0 or self.record_revision != 0:
                raise ValueError("Unconfigured canary control must be generation zero")
        elif self.selection_generation < 1 or self.record_revision < 1:
            raise ValueError("Configured canary control must have durable identity")


def default_coding_apphost_canary_control_path(
    *,
    platform_paths: PlatformPaths | None = None,
) -> Path:
    paths = platform_paths or resolve_platform_paths()
    return paths.state / "products" / "coding" / "apphost-explicit-canary-control.jsonl"


class CodingAppHostCanaryControlJournal:
    """Strict append-only authority serializing canary runs and transitions."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(os.path.abspath(Path(path).expanduser()))
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="raise")

    @property
    def path(self) -> Path:
        return self._path

    def snapshot(self) -> CodingAppHostCanaryControlSnapshotV1:
        if not self._path.exists():
            return _unconfigured_snapshot()
        try:
            with self._private_lock(create=False, mode="shared"):
                return self._snapshot_unlocked()
        except FileNotFoundError:
            return _unconfigured_snapshot()

    def enable(self, *, operation_id: str) -> CodingAppHostCanaryControlSnapshotV1:
        return self._transition("enable", operation_id=operation_id)

    def rollback(self, *, operation_id: str) -> CodingAppHostCanaryControlSnapshotV1:
        return self._transition("rollback", operation_id=operation_id)

    async def snapshot_async(
        self,
        *,
        timeout_seconds: float,
    ) -> CodingAppHostCanaryControlSnapshotV1:
        if not self._path.exists():
            return _unconfigured_snapshot()
        context = await self._acquire_private_lock_async(
            create=False,
            mode="shared",
            timeout_seconds=timeout_seconds,
        )
        try:
            return self._snapshot_unlocked()
        finally:
            context.__exit__(None, None, None)

    async def enable_async(
        self,
        *,
        operation_id: str,
        timeout_seconds: float,
    ) -> CodingAppHostCanaryControlSnapshotV1:
        return await self._transition_async(
            "enable",
            operation_id=operation_id,
            timeout_seconds=timeout_seconds,
        )

    async def rollback_async(
        self,
        *,
        operation_id: str,
        timeout_seconds: float,
    ) -> CodingAppHostCanaryControlSnapshotV1:
        return await self._transition_async(
            "rollback",
            operation_id=operation_id,
            timeout_seconds=timeout_seconds,
        )

    @contextmanager
    def admitted_run(self) -> Iterator[CodingAppHostCanaryControlSnapshotV1]:
        """Hold the final enabled decision until the exact run has settled."""

        with self._private_lock(create=True, mode="exclusive"):
            snapshot = self._snapshot_unlocked()
            if snapshot.state != "enabled":
                raise self._error(
                    "coding_apphost_canary_disabled",
                    selection_generation=snapshot.selection_generation,
                )
            yield snapshot

    @asynccontextmanager
    async def admitted_run_async(
        self,
        *,
        timeout_seconds: float,
    ) -> AsyncIterator[CodingAppHostCanaryControlSnapshotV1]:
        """Acquire without blocking an event loop, then retain until settlement."""

        context = await self._acquire_private_lock_async(
            create=True,
            mode="exclusive",
            timeout_seconds=timeout_seconds,
        )
        try:
            snapshot = self._snapshot_unlocked()
            if snapshot.state != "enabled":
                raise self._error(
                    "coding_apphost_canary_disabled",
                    selection_generation=snapshot.selection_generation,
                )
            yield snapshot
        finally:
            context.__exit__(None, None, None)

    def _transition(
        self,
        operation: CanaryControlOperation,
        *,
        operation_id: str,
    ) -> CodingAppHostCanaryControlSnapshotV1:
        if _OPERATION_ID.fullmatch(operation_id) is None:
            raise ValueError("Coding AppHost canary operation id is invalid")
        target_state: Literal["enabled", "disabled"] = (
            "enabled" if operation == "enable" else "disabled"
        )
        with self._private_lock(create=True, mode="exclusive"):
            return self._transition_unlocked(
                operation,
                target_state=target_state,
                operation_id=operation_id,
            )

    async def _transition_async(
        self,
        operation: CanaryControlOperation,
        *,
        operation_id: str,
        timeout_seconds: float,
    ) -> CodingAppHostCanaryControlSnapshotV1:
        if _OPERATION_ID.fullmatch(operation_id) is None:
            raise ValueError("Coding AppHost canary operation id is invalid")
        target_state: Literal["enabled", "disabled"] = (
            "enabled" if operation == "enable" else "disabled"
        )
        context = await self._acquire_private_lock_async(
            create=True,
            mode="exclusive",
            timeout_seconds=timeout_seconds,
        )
        try:
            return self._transition_unlocked(
                operation,
                target_state=target_state,
                operation_id=operation_id,
            )
        finally:
            context.__exit__(None, None, None)

    def _transition_unlocked(
        self,
        operation: CanaryControlOperation,
        *,
        target_state: Literal["enabled", "disabled"],
        operation_id: str,
    ) -> CodingAppHostCanaryControlSnapshotV1:
        records = self._load_unlocked()
        current = _snapshot_from_records(records)
        if current.state == target_state:
            return current
        revision = current.record_revision + 1
        record = CodingAppHostCanaryControlRecordV1(
            operation=operation,
            state=target_state,
            selection_generation=current.selection_generation + 1,
            record_revision=revision,
            operation_id=operation_id,
        )
        try:
            append_jsonl_record(
                self._path,
                record,
                record_codec=CODING_APPHOST_CANARY_CONTROL_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
        except (JournalCodecError, JournalFileError, OSError) as error:
            raise self._error(
                "coding_apphost_canary_control_write_failed",
                selection_generation=current.selection_generation,
            ) from error
        return CodingAppHostCanaryControlSnapshotV1(
            state=target_state,
            selection_generation=record.selection_generation,
            record_revision=record.record_revision,
        )

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
            raise ValueError("Coding AppHost canary lock timeout is invalid")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(timeout_seconds)
        while True:
            candidate = self._private_lock(
                create=create,
                mode=mode,
                blocking=False,
            )
            try:
                candidate.__enter__()
            except JournalLockUnavailable:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise self._error("coding_apphost_canary_control_busy") from None
                await asyncio.sleep(min(0.01, remaining))
            else:
                return candidate

    def _snapshot_unlocked(self) -> CodingAppHostCanaryControlSnapshotV1:
        return _snapshot_from_records(self._load_unlocked())

    def _load_unlocked(self) -> tuple[CodingAppHostCanaryControlRecordV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, CodingAppHostCanaryControlRecordV1] = (
                load_jsonl(
                    self._path,
                    record_codec=CODING_APPHOST_CANARY_CONTROL_CODEC,
                    format_profile=SORTED_UNICODE_JSONL_FORMAT,
                    durability=self._unlocked_durability,
                    load_policy=self._load_policy,
                )
            )
            records = snapshot.records
            _validate_history(records)
            return records
        except (JournalCodecError, JournalFileError, OSError, ValueError) as error:
            raise self._error("coding_apphost_canary_control_corrupt") from error

    def _private_lock(
        self,
        *,
        create: bool,
        mode: Literal["exclusive", "shared"],
        blocking: bool = True,
    ) -> AbstractContextManager[None]:
        return self._private_lock_context(
            create=create,
            mode=mode,
            blocking=blocking,
        )

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
            _assert_private_storage(self._path, require_parent=create)
            with journal_file_lock(
                self._path,
                mode,
                lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
                blocking=blocking,
                create=create,
            ):
                _assert_private_storage(self._path, require_parent=True)
                yield
        except CodingAppHostCanaryControlError:
            raise
        except JournalLockUnavailable:
            raise
        except OSError as error:
            raise self._error("coding_apphost_canary_control_storage_unsafe") from error

    def _error(
        self,
        code: str,
        *,
        selection_generation: int = 0,
    ) -> CodingAppHostCanaryControlError:
        return CodingAppHostCanaryControlError(
            code=code,
            path=self._path,
            selection_generation=selection_generation,
        )


def _encode_record(
    record: CodingAppHostCanaryControlRecordV1,
) -> dict[str, object]:
    if type(record) is not CodingAppHostCanaryControlRecordV1:
        raise TypeError("Coding AppHost canary control requires typed records")
    return record.to_dict()


def _decode_record(value: object) -> CodingAppHostCanaryControlRecordV1:
    try:
        return CodingAppHostCanaryControlRecordV1.from_dict(value)
    except (TypeError, ValueError) as error:
        raise JournalCodecError(
            "Coding AppHost canary control record is invalid",
            code="invalid_coding_apphost_canary_control_record",
        ) from error


CODING_APPHOST_CANARY_CONTROL_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_record,
    decoder=_decode_record,
)


def _unconfigured_snapshot() -> CodingAppHostCanaryControlSnapshotV1:
    return CodingAppHostCanaryControlSnapshotV1(
        state="unconfigured",
        selection_generation=0,
        record_revision=0,
    )


def _snapshot_from_records(
    records: tuple[CodingAppHostCanaryControlRecordV1, ...],
) -> CodingAppHostCanaryControlSnapshotV1:
    if not records:
        return _unconfigured_snapshot()
    current = records[-1]
    return CodingAppHostCanaryControlSnapshotV1(
        state=current.state,
        selection_generation=current.selection_generation,
        record_revision=current.record_revision,
    )


def _validate_history(
    records: tuple[CodingAppHostCanaryControlRecordV1, ...],
) -> None:
    prior_state: str | None = None
    operation_ids: set[str] = set()
    for expected, record in enumerate(records, start=1):
        if (
            record.record_revision != expected
            or record.selection_generation != expected
            or record.state == prior_state
            or record.operation_id in operation_ids
        ):
            raise ValueError("Coding AppHost canary control history is invalid")
        prior_state = record.state
        operation_ids.add(record.operation_id)


def _assert_private_storage(path: Path, *, require_parent: bool) -> None:
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
        raise OSError("Coding AppHost canary control parent is not private")
    _assert_private_regular_file(path, required=False)
    _assert_private_regular_file(
        path.with_name(f"{path.name}{DURABLE_LOCKED_JOURNAL.lock_suffix}"),
        required=False,
    )


def _assert_private_regular_file(path: Path, *, required: bool) -> None:
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
        raise OSError("Coding AppHost canary control file is not private")


def _owned_by_current_user(metadata: os.stat_result) -> bool:
    getuid = getattr(os, "geteuid", None)
    return not callable(getuid) or metadata.st_uid == getuid()


__all__ = [
    "CODING_APPHOST_CANARY_CONTROL_CODEC",
    "CODING_APPHOST_CANARY_CONTROL_VERSION",
    "CodingAppHostCanaryControlError",
    "CodingAppHostCanaryControlJournal",
    "CodingAppHostCanaryControlRecordV1",
    "CodingAppHostCanaryControlSnapshotV1",
    "default_coding_apphost_canary_control_path",
]
