"""Inert Windows custody for Worker native-release approval decisions.

The Product caller pins the private state-root descriptor and holds its GC
gate. This journal records decisions only; it never identifies backend bytes,
installs a release, or grants launch authority.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import BinaryIO, Literal

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal import journal_file_lock_at
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
    windows_flush_directory,
    windows_flush_file,
    windows_regular_file_stream_names,
    windows_stat_at,
)

from .package_product_worker_native_approval import (
    CodingWorkerNativeApprovalDecisionV1,
    CodingWorkerNativeApprovalError,
    CodingWorkerNativeReleaseApprovalV1,
    _decode_coding_worker_native_approval_history,
)

_NAME = "worker-native-release-approvals.jsonl"
_OPAQUE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:@+-]*[A-Za-z0-9])?\Z")
_MAX_EVENTS = 256
_MAX_BYTES = 4 * 1024 * 1024


class CodingWindowsWorkerNativeApprovalJournal:
    """Strict append-only native approval history under one pinned root."""

    def __init__(self, path: Path, *, scope_id: str) -> None:
        if not isinstance(path, Path) or not path.is_absolute() or path.name != _NAME:
            raise ValueError("Windows Worker native approval path is invalid")
        if (
            not isinstance(scope_id, str)
            or len(scope_id) > 128
            or _OPAQUE.fullmatch(scope_id) is None
        ):
            raise ValueError("Windows Worker native approval scope is invalid")
        self._path = path
        self._scope_id = scope_id

    @property
    def path(self) -> Path:
        return self._path

    def current(
        self, *, directory_fd: int
    ) -> CodingWorkerNativeApprovalDecisionV1 | None:
        self._require_root(directory_fd)
        with WindowsPrivateDirectoryAcl() as acl:
            acl.validate(directory_fd)
            self._assert_visible_root(directory_fd)
            try:
                self._validate_lock(directory_fd, acl)
            except FileNotFoundError:
                try:
                    windows_stat_at(directory_fd, _NAME)
                except FileNotFoundError:
                    self._assert_visible_root(directory_fd)
                    return None
                raise CodingWorkerNativeApprovalError(
                    "coding_worker_native_approval_lock_missing"
                ) from None
            with journal_file_lock_at(directory_fd, _NAME + ".lock", "shared"):
                initialized = self._validate_lock(directory_fd, acl)
                raw = self._read_raw(directory_fd, acl)
                if raw is None:
                    if initialized:
                        raise CodingWorkerNativeApprovalError(
                            "coding_worker_native_approval_orphan_lock"
                        )
                    self._assert_visible_root(directory_fd)
                    return None
                if not initialized:
                    raise CodingWorkerNativeApprovalError(
                        "coding_worker_native_approval_lock_corrupt"
                    )
                events = self._decode(raw)
            self._assert_visible_root(directory_fd)
            return events[-1] if events else None

    def change(
        self,
        *,
        directory_fd: int,
        operation_id: str,
        expected_generation: int,
        action: Literal["approve", "revoke"],
        approval: CodingWorkerNativeReleaseApprovalV1 | None,
    ) -> CodingWorkerNativeApprovalDecisionV1:
        if (
            not isinstance(operation_id, str)
            or len(operation_id) > 128
            or _OPAQUE.fullmatch(operation_id) is None
            or type(expected_generation) is not int
            or expected_generation < 0
            or action not in {"approve", "revoke"}
            or (action == "approve")
            != isinstance(approval, CodingWorkerNativeReleaseApprovalV1)
        ):
            raise ValueError("Windows Worker native approval command is invalid")
        self._require_root(directory_fd)
        with WindowsPrivateDirectoryAcl() as acl:
            acl.validate(directory_fd)
            self._assert_visible_root(directory_fd)
            self._prepare_lock(directory_fd, acl)
            with journal_file_lock_at(
                directory_fd, _NAME + ".lock", "exclusive"
            ) as lock_handle:
                initialized = self._validate_lock(directory_fd, acl)
                raw = self._read_raw(directory_fd, acl)
                if (raw is None and initialized) or (
                    raw is not None and not initialized
                ):
                    raise CodingWorkerNativeApprovalError(
                        "coding_worker_native_approval_lock_corrupt"
                    )
                events = () if raw is None else self._decode(raw)
                replay = next(
                    (item for item in events if item.operation_id == operation_id),
                    None,
                )
                if replay is not None:
                    if (
                        replay.action != action
                        or replay.approval != approval
                        or replay.generation != expected_generation + 1
                    ):
                        raise CodingWorkerNativeApprovalError(
                            "coding_worker_native_approval_operation_conflict"
                        )
                    self._assert_visible_root(directory_fd)
                    return replay
                previous = events[-1] if events else None
                generation = 0 if previous is None else previous.generation
                if generation != expected_generation:
                    raise CodingWorkerNativeApprovalError(
                        "coding_worker_native_approval_stale"
                    )
                if action == "revoke" and (
                    previous is None or previous.action != "approve"
                ):
                    raise CodingWorkerNativeApprovalError(
                        "coding_worker_native_approval_absent"
                    )
                if len(events) >= _MAX_EVENTS:
                    raise CodingWorkerNativeApprovalError(
                        "coding_worker_native_approval_capacity"
                    )
                decision = CodingWorkerNativeApprovalDecisionV1.create(
                    journal_revision=len(events) + 1,
                    scope_id=self._scope_id,
                    operation_id=operation_id,
                    generation=generation + 1,
                    action=action,
                    approval=approval,
                )
                line = canonical_json_bytes(decision.to_dict()) + b"\n"
                if len(raw or b"") + len(line) > _MAX_BYTES:
                    raise CodingWorkerNativeApprovalError(
                        "coding_worker_native_approval_capacity"
                    )
                if not initialized:
                    self._mark_lock_initialized(lock_handle)
                self._append(directory_fd, acl, expected=raw, line=line)
                self._assert_visible_root(directory_fd)
                return decision

    def _prepare_lock(self, directory_fd: int, acl: WindowsPrivateDirectoryAcl) -> None:
        lock_name = _NAME + ".lock"
        try:
            windows_stat_at(directory_fd, lock_name)
        except FileNotFoundError:
            try:
                windows_stat_at(directory_fd, _NAME)
            except FileNotFoundError:
                pass
            else:
                raise CodingWorkerNativeApprovalError(
                    "coding_worker_native_approval_lock_missing"
                ) from None
        try:
            descriptor = open_windows_regular_file_at(
                directory_fd,
                lock_name,
                create_new=True,
                write=True,
                security_descriptor=acl.security_descriptor,
                read_control=True,
            )
        except FileExistsError:
            descriptor = open_windows_regular_file_at(
                directory_fd,
                lock_name,
                create_new=False,
                write=True,
                read_control=True,
            )
            created = False
        else:
            created = True
        try:
            acl.validate(descriptor)
            self._require_plain_stream(descriptor)
            if created:
                if os.write(descriptor, b"\0") != 1:
                    raise OSError("Windows Worker native approval lock write failed")
                windows_flush_file(descriptor)
            elif os.fstat(descriptor).st_size != 1:
                raise CodingWorkerNativeApprovalError(
                    "coding_worker_native_approval_lock_corrupt"
                )
        finally:
            os.close(descriptor)
        if created:
            windows_flush_directory(directory_fd)

    def _validate_lock(
        self, directory_fd: int, acl: WindowsPrivateDirectoryAcl
    ) -> bool:
        descriptor = open_windows_regular_file_at(
            directory_fd,
            _NAME + ".lock",
            create_new=False,
            write=False,
            read_control=True,
        )
        try:
            acl.validate(descriptor)
            self._require_plain_stream(descriptor)
            if os.fstat(descriptor).st_size != 1:
                raise CodingWorkerNativeApprovalError(
                    "coding_worker_native_approval_lock_corrupt"
                )
            state = os.read(descriptor, 1)
            if state not in {b"\0", b"\1"}:
                raise CodingWorkerNativeApprovalError(
                    "coding_worker_native_approval_lock_corrupt"
                )
            return state == b"\1"
        finally:
            os.close(descriptor)

    @staticmethod
    def _mark_lock_initialized(handle: BinaryIO) -> None:
        """Publish history intent before the first append; crashes then fail closed."""

        handle.seek(0)
        if handle.read(1) != b"\0":
            raise CodingWorkerNativeApprovalError(
                "coding_worker_native_approval_lock_corrupt"
            )
        handle.seek(0)
        if handle.write(b"\1") != 1:
            raise OSError("Windows Worker native approval lock commit failed")
        handle.flush()
        windows_flush_file(handle.fileno())

    def _read_raw(
        self, directory_fd: int, acl: WindowsPrivateDirectoryAcl
    ) -> bytes | None:
        try:
            descriptor = open_windows_regular_file_at(
                directory_fd,
                _NAME,
                create_new=False,
                write=False,
                read_control=True,
            )
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as source:
            acl.validate(source.fileno())
            self._require_plain_stream(source.fileno())
            return source.read(_MAX_BYTES + 1)

    def _append(
        self,
        directory_fd: int,
        acl: WindowsPrivateDirectoryAcl,
        *,
        expected: bytes | None,
        line: bytes,
    ) -> None:
        try:
            descriptor = open_windows_regular_file_at(
                directory_fd,
                _NAME,
                create_new=True,
                write=True,
                security_descriptor=acl.security_descriptor,
                read_control=True,
            )
        except FileExistsError:
            descriptor = open_windows_regular_file_at(
                directory_fd,
                _NAME,
                create_new=False,
                write=True,
                read_control=True,
            )
            created = False
        else:
            created = True
        with os.fdopen(descriptor, "r+b") as output:
            acl.validate(output.fileno())
            self._require_plain_stream(output.fileno())
            observed = output.read(_MAX_BYTES + 1)
            if (created and (expected is not None or observed)) or (
                not created and observed != expected
            ):
                raise CodingWorkerNativeApprovalError(
                    "coding_worker_native_approval_changed"
                )
            output.seek(0, os.SEEK_END)
            remaining = memoryview(line)
            while remaining:
                written = output.write(remaining)
                if written is None or written <= 0:
                    raise OSError("Windows Worker native approval append stalled")
                remaining = remaining[written:]
            output.flush()
            windows_flush_file(output.fileno())
        if created:
            windows_flush_directory(directory_fd)

    def _decode(self, raw: bytes) -> tuple[CodingWorkerNativeApprovalDecisionV1, ...]:
        if not raw or len(raw) > _MAX_BYTES or not raw.endswith(b"\n"):
            raise CodingWorkerNativeApprovalError(
                "coding_worker_native_approval_corrupt"
            )
        try:
            events = _decode_coding_worker_native_approval_history(
                raw, path=self._path, scope_id=self._scope_id
            )
            if raw != b"".join(
                canonical_json_bytes(item.to_dict()) + b"\n" for item in events
            ):
                raise ValueError("Windows Worker native approval bytes changed")
            return events
        except (UnicodeError, ValueError) as exc:
            raise CodingWorkerNativeApprovalError(
                "coding_worker_native_approval_corrupt"
            ) from exc

    def _assert_visible_root(self, directory_fd: int) -> None:
        try:
            if not os.path.samestat(os.fstat(directory_fd), self._path.parent.lstat()):
                raise CodingWorkerNativeApprovalError(
                    "coding_worker_native_approval_state_root_changed"
                )
        except OSError as exc:
            raise CodingWorkerNativeApprovalError(
                "coding_worker_native_approval_state_root_changed"
            ) from exc

    @staticmethod
    def _require_root(directory_fd: int) -> None:
        if os.name != "nt" or type(directory_fd) is not int or directory_fd < 0:
            raise OSError("Windows Worker approval requires a pinned Product root")

    @staticmethod
    def _require_plain_stream(descriptor: int) -> None:
        if windows_regular_file_stream_names(descriptor) != ("::$DATA",):
            raise CodingWorkerNativeApprovalError(
                "coding_worker_native_approval_stream_invalid"
            )


__all__ = ["CodingWindowsWorkerNativeApprovalJournal"]
