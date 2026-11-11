"""Fixed Windows Worker journals over the original Resource custody owner.

Pure record/error/limit bindings carry Product vocabulary. File handles/locks
remain with WindowsJournalFileIO; these programs confer no Product authority.
"""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Generic, Literal, Protocol, TypeVar

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.resources.packages._windows_journal_file import (
    WindowsJournalFileIO,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)

from ._native_approval import _A, _N, _NativeFactory, _next_native_approval_decision
from ._opt_in import (
    _OPAQUE,
    _OptInDecisionMethods,
    _OptInMutation,
    _OptInValue,
    latest_opt_in_decision,
)
from ._receipts import _ReceiptRecordMethods, latest_receipt_record


class _RecordValue(Protocol):
    def to_dict(self) -> dict[str, object]: ...


_R = TypeVar("_R", bound=_RecordValue)
_R_co = TypeVar("_R_co", bound=_RecordValue, covariant=True)


class _Decoder(Protocol[_R_co]):
    def __call__(
        self, raw: bytes, *, path: Path, scope_id: str
    ) -> tuple[_R_co, ...]: ...


@dataclass(frozen=True, slots=True)
class _BoundRecordAppend(Generic[_R]):
    acl: WindowsPrivateDirectoryAcl
    lock_handle: BinaryIO
    raw: bytes | None
    initialized: bool
    records: tuple[_R, ...]


class _WindowsRecords(Generic[_R]):
    _name: str
    _label: str
    _scope_pattern: re.Pattern[str] | None
    _failure: Callable[[str], RuntimeError]
    _decoder: _Decoder[_R]
    _max_bytes: Callable[[], int]
    _max_events: Callable[[], int]
    _append_error: str
    _root_error: str

    def __init__(self, path: Path, *, scope_id: str) -> None:
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or path.name != self._name
        ):
            raise ValueError(f"{self._label} path is invalid")
        if self._scope_pattern is None:
            invalid = not isinstance(scope_id, str) or not 0 < len(scope_id) <= 128
        else:
            invalid = (
                not isinstance(scope_id, str)
                or len(scope_id) > 128
                or self._scope_pattern.fullmatch(scope_id) is None
            )
        if invalid:
            raise ValueError(f"{self._label} scope is invalid")
        self._path = path
        self._scope_id = scope_id
        failure = self._failure
        self._file_io = WindowsJournalFileIO(
            name=self._name,
            max_bytes=self._max_bytes(),
            lock_error=lambda: failure("lock_corrupt"),
            change_error=lambda: failure("changed"),
            stream_error=lambda: failure("stream_invalid"),
            lock_write_error=f"{self._label} lock write failed",
            lock_commit_error=f"{self._label} lock commit failed",
            append_error=self._append_error,
        )

    def _read_records(self, *, directory_fd: int) -> tuple[_R, ...]:
        self._require_root(directory_fd)
        with self._file_io.read_snapshot(
            directory_fd,
            assert_visible_root=lambda: self._assert_visible_root(directory_fd),
            missing_lock_error=lambda: self._failure("lock_missing"),
            orphan_lock_error=lambda: self._failure("orphan_lock"),
        ) as raw:
            return () if raw is None else self._decode(raw)

    def _prepare_lock(self, directory_fd: int, acl: WindowsPrivateDirectoryAcl) -> None:
        self._file_io.prepare_history_lock(
            directory_fd, acl, missing_lock_error=lambda: self._failure("lock_missing")
        )

    def _decode(self, raw: bytes) -> tuple[_R, ...]:
        if not raw or len(raw) > self._max_bytes() or (not raw.endswith(b"\n")):
            raise self._failure("corrupt")
        try:
            events = self._decoder(raw, path=self._path, scope_id=self._scope_id)
            if raw != b"".join(
                (canonical_json_bytes(event.to_dict()) + b"\n" for event in events)
            ):
                raise ValueError(f"{self._label} bytes changed")
            return events
        except (UnicodeError, ValueError) as exc:
            raise self._failure("corrupt") from exc

    def _assert_visible_root(self, directory_fd: int) -> None:
        self._file_io.assert_visible_parent(
            directory_fd,
            self._path.parent,
            changed_error=lambda: self._failure("state_root_changed"),
        )

    @classmethod
    def _require_root(cls, directory_fd: int) -> None:
        if os.name != "nt" or type(directory_fd) is not int or directory_fd < 0:
            raise OSError(cls._root_error)

    def _bind_record_append(
        self, directory_fd: int, custody: ExitStack
    ) -> _BoundRecordAppend[_R]:
        acl, lock_handle, raw, initialized = self._file_io.bind_append_snapshot(
            directory_fd,
            custody=custody,
            assert_visible_root=lambda: self._assert_visible_root(directory_fd),
            prepare_lock=lambda root, acl: self._prepare_lock(root, acl),
        )
        records = () if raw is None else self._decode(raw)
        return _BoundRecordAppend(acl, lock_handle, raw, initialized, records)

    def _append_bound_record(
        self, directory_fd: int, bound: _BoundRecordAppend[_R], record: _R
    ) -> None:
        line = canonical_json_bytes(record.to_dict()) + b"\n"
        if len(bound.raw or b"") + len(line) > self._max_bytes():
            raise self._failure("capacity")
        if not bound.initialized:
            self._file_io.mark_initialized(bound.lock_handle)
        self._file_io.append(directory_fd, bound.acl, expected=bound.raw, line=line)
        self._assert_visible_root(directory_fd)


_D = TypeVar("_D", bound=_OptInDecisionMethods)
_P = TypeVar("_P", bound=_OptInValue)
_T = TypeVar("_T", bound=_ReceiptRecordMethods)


class WindowsOptInRecords(_WindowsRecords[_D], Generic[_D, _P]):
    _record_type: type[_D]
    _opt_in_type: type[_P]
    _latest = staticmethod(latest_opt_in_decision)

    @staticmethod
    def _require_plugin_id(plugin_id: str) -> None:
        raise NotImplementedError("the original input admission is required")

    def _change(
        self,
        *,
        directory_fd: int,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
        action: Literal["allow", "revoke"],
        opt_in: _P | None,
    ) -> _D:
        self._require_plugin_id(plugin_id)
        mutation = _OptInMutation(
            plugin_id, operation_id, expected_generation, action, opt_in
        )
        if not mutation.is_valid(lambda: self._opt_in_type):
            raise ValueError("Windows Worker opt-in command is invalid")
        self._require_root(directory_fd)
        with ExitStack() as custody:
            bound = self._bind_record_append(directory_fd, custody)
            events = bound.records

            def failure(code: str) -> RuntimeError:
                return self._failure(code)

            replay = mutation.replay(events, failure=failure)
            if replay is not None:
                self._assert_visible_root(directory_fd)
                return replay
            previous = self._latest(events, plugin_id)
            generation, kill = mutation.next_generation(
                previous, failure=failure
            )
            if len(events) >= self._max_events():
                raise self._failure("capacity")
            decision = self._record_type.create(
                journal_revision=len(events) + 1,
                scope_id=self._scope_id,
                plugin_id=plugin_id,
                operation_id=operation_id,
                generation=generation + 1,
                kill_switch_generation=kill,
                action=action,
                opt_in=opt_in,
            )
            self._append_bound_record(directory_fd, bound, decision)
            return decision


class WindowsReceiptRecords(_WindowsRecords[_T], Generic[_T]):
    _record_type: type[_T]

    def _issue(
        self,
        *,
        directory_fd: int,
        policy: ProductWorkerActivationPolicyV1,
        opt_in_decision_digest: str,
    ) -> ProductWorkerActivationReceiptV1:
        if (
            not isinstance(policy, ProductWorkerActivationPolicyV1)
            or type(opt_in_decision_digest) is not str
            or len(opt_in_decision_digest) != 64
            or any((char not in "0123456789abcdef" for char in opt_in_decision_digest))
        ):
            raise ValueError("Windows Worker receipt issue input is invalid")
        self._require_root(directory_fd)
        with ExitStack() as custody:
            bound = self._bind_record_append(directory_fd, custody)
            records = bound.records
            latest = latest_receipt_record(records, policy)
            if (
                latest is not None
                and latest.opt_in_decision_digest == opt_in_decision_digest
                and (latest.receipt.policy.fingerprint == policy.fingerprint)
            ):
                self._assert_visible_root(directory_fd)
                return latest.receipt
            if len(records) >= self._max_events():
                raise self._failure("capacity")
            receipt = ProductWorkerActivationReceiptV1(
                policy=policy,
                issue_sequence=len(records) + 1,
                issue_nonce=secrets.token_hex(16),
            )
            record = self._record_type.create(
                journal_revision=len(records) + 1,
                scope_id=self._scope_id,
                opt_in_decision_digest=opt_in_decision_digest,
                receipt=receipt,
            )
            self._append_bound_record(directory_fd, bound, record)
            return receipt


class WindowsNativeApprovalRecords(_WindowsRecords[_N], Generic[_A, _N]):
    _approval_type: type[_A]
    _create_decision: _NativeFactory[_A, _N]

    def _change(
        self,
        *,
        directory_fd: int,
        operation_id: str,
        expected_generation: int,
        action: Literal["approve", "revoke"],
        approval: _A | None,
    ) -> _N:
        if (
            not isinstance(operation_id, str)
            or len(operation_id) > 128
            or _OPAQUE.fullmatch(operation_id) is None
            or (type(expected_generation) is not int)
            or (expected_generation < 0)
            or (action not in {"approve", "revoke"})
            or ((action == "approve") != isinstance(approval, self._approval_type))
        ):
            raise ValueError("Windows Worker native approval command is invalid")
        self._require_root(directory_fd)
        with ExitStack() as custody:
            bound = self._bind_record_append(directory_fd, custody)
            events = bound.records
            decision, replay = _next_native_approval_decision(
                events,
                operation_id=operation_id,
                expected_generation=expected_generation,
                action=action,
                approval=approval,
                scope_id=self._scope_id,
                max_events=self._max_events,
                create_decision=self._create_decision,
                failure=self._failure,
            )
            if replay:
                self._assert_visible_root(directory_fd)
                return decision
            self._append_bound_record(directory_fd, bound, decision)
            return decision
