"""Durable Product-owned selection control for the explicit AppHost canary."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Literal, cast

from loushang.foundation.platform_paths import PlatformPaths, resolve_platform_paths
from loushang.harness.journal import (
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalRecordCodec,
)
from loushang.harness.journal._private_operations import (
    _JournalFailure,
    _PreparedMutation,
    _PrivateJournalOperations,
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


class CodingAppHostCanaryControlJournal(
    _PrivateJournalOperations[
        CodingAppHostCanaryControlRecordV1, CodingAppHostCanaryControlSnapshotV1
    ]
):
    """Strict append-only authority serializing canary runs and transitions."""

    _storage_label = "Coding AppHost canary control"
    _timeout_message = "Coding AppHost canary lock timeout is invalid"
    _format_profile = SORTED_UNICODE_JSONL_FORMAT

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)

    @property
    def path(self) -> Path:
        return self._path

    def snapshot(self) -> CodingAppHostCanaryControlSnapshotV1:
        return self._read_snapshot()

    def enable(self, *, operation_id: str) -> CodingAppHostCanaryControlSnapshotV1:
        return self._transition("enable", operation_id=operation_id)

    def rollback(self, *, operation_id: str) -> CodingAppHostCanaryControlSnapshotV1:
        return self._transition("rollback", operation_id=operation_id)

    async def snapshot_async(
        self,
        *,
        timeout_seconds: float,
    ) -> CodingAppHostCanaryControlSnapshotV1:
        return await self._read_snapshot_async(timeout_seconds=timeout_seconds)

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

        yield from self._admitted_run_iterator()

    @asynccontextmanager
    async def admitted_run_async(
        self,
        *,
        timeout_seconds: float,
    ) -> AsyncIterator[CodingAppHostCanaryControlSnapshotV1]:
        """Acquire without blocking an event loop, then retain until settlement."""

        async with self._admitted_run_context_async(
            timeout_seconds=timeout_seconds
        ) as snapshot:
            yield snapshot

    def _transition(
        self,
        operation: CanaryControlOperation,
        *,
        operation_id: str,
    ) -> CodingAppHostCanaryControlSnapshotV1:
        return self._mutate_locked(self._bind_transition(operation, operation_id))

    async def _transition_async(
        self,
        operation: CanaryControlOperation,
        *,
        operation_id: str,
        timeout_seconds: float,
    ) -> CodingAppHostCanaryControlSnapshotV1:
        return await self._mutate_locked_async(
            self._bind_transition(operation, operation_id),
            timeout_seconds=timeout_seconds,
        )

    def _bind_transition(
        self, operation: CanaryControlOperation, operation_id: str
    ) -> Callable[
        [tuple[CodingAppHostCanaryControlRecordV1, ...]],
        _PreparedMutation[CodingAppHostCanaryControlRecordV1, CodingAppHostCanaryControlSnapshotV1],
    ]:
        if _OPERATION_ID.fullmatch(operation_id) is None:
            raise ValueError("Coding AppHost canary operation id is invalid")
        return partial(
            self._prepare_transition, operation=operation, operation_id=operation_id
        )

    def _prepare_transition(
        self,
        records: tuple[CodingAppHostCanaryControlRecordV1, ...],
        operation: CanaryControlOperation,
        *,
        operation_id: str,
    ) -> _PreparedMutation[
        CodingAppHostCanaryControlRecordV1, CodingAppHostCanaryControlSnapshotV1
    ]:
        target_state: Literal["enabled", "disabled"] = (
            "enabled" if operation == "enable" else "disabled"
        )
        current = _snapshot_from_records(records)
        if current.state == target_state:
            return None, lambda: current, lambda: current.selection_generation
        revision = current.record_revision + 1
        record = CodingAppHostCanaryControlRecordV1(
            operation=operation,
            state=target_state,
            selection_generation=current.selection_generation + 1,
            record_revision=revision,
            operation_id=operation_id,
        )
        return (
            record,
            lambda: _snapshot_from_records((record,)),
            lambda: current.selection_generation,
        )

    @property
    def _record_codec(self) -> JournalRecordCodec[CodingAppHostCanaryControlRecordV1]:
        return CODING_APPHOST_CANARY_CONTROL_CODEC

    @property
    def _domain_error_type(self) -> type[Exception]:
        return CodingAppHostCanaryControlError

    def _validate_records(
        self, records: tuple[CodingAppHostCanaryControlRecordV1, ...]
    ) -> None:
        _validate_history(records)

    def _project_snapshot(
        self, records: tuple[CodingAppHostCanaryControlRecordV1, ...]
    ) -> CodingAppHostCanaryControlSnapshotV1:
        return _snapshot_from_records(records)

    def _require_admitted(self, snapshot: CodingAppHostCanaryControlSnapshotV1) -> None:
        if snapshot.state != "enabled":
            raise self._error(
                "coding_apphost_canary_disabled",
                selection_generation=snapshot.selection_generation,
            )

    def _journal_error(self, kind: _JournalFailure, *, context: int = 0) -> Exception:
        code = {
            "busy": "coding_apphost_canary_control_busy",
            "corrupt": "coding_apphost_canary_control_corrupt",
            "unsafe": "coding_apphost_canary_control_storage_unsafe",
            "write_failed": "coding_apphost_canary_control_write_failed",
        }[kind]
        return self._error(code, selection_generation=context)

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


__all__ = [
    "CODING_APPHOST_CANARY_CONTROL_CODEC",
    "CODING_APPHOST_CANARY_CONTROL_VERSION",
    "CodingAppHostCanaryControlError",
    "CodingAppHostCanaryControlJournal",
    "CodingAppHostCanaryControlRecordV1",
    "CodingAppHostCanaryControlSnapshotV1",
    "default_coding_apphost_canary_control_path",
]
