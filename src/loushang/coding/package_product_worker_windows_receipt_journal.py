"""Windows-private append-only custody for Product Worker receipts."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import BinaryIO

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal import JournalLoadPolicy, journal_file_lock_at
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
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)

from .package_product_worker_receipt import (
    CodingWorkerReceiptError,
    CodingWorkerReceiptRecordV1,
    _decode_coding_worker_receipt_history,
)

_NAME = "worker-activation-receipts.jsonl"
_MAX_RECEIPTS = 4096
_MAX_BYTES = 32 * 1024 * 1024


class CodingWindowsWorkerReceiptJournal:
    """Keep one Product scope's issued receipts under a pinned Windows root."""

    def __init__(self, path: Path, *, scope_id: str) -> None:
        if not isinstance(path, Path) or not path.is_absolute() or path.name != _NAME:
            raise ValueError("Windows Worker receipt path is invalid")
        if not isinstance(scope_id, str) or not 0 < len(scope_id) <= 128:
            raise ValueError("Windows Worker receipt scope is invalid")
        self._path = path
        self._scope_id = scope_id

    def records(self, *, directory_fd: int) -> tuple[CodingWorkerReceiptRecordV1, ...]:
        """Read without creating any journal or lock state."""

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
                    return ()
                raise CodingWorkerReceiptError(
                    "coding_worker_receipt_lock_missing"
                ) from None
            with journal_file_lock_at(directory_fd, _NAME + ".lock", "shared"):
                initialized = self._validate_lock(directory_fd, acl)
                raw = self._read_raw(directory_fd, acl)
                if raw is None:
                    if initialized:
                        raise CodingWorkerReceiptError(
                            "coding_worker_receipt_orphan_lock"
                        )
                    self._assert_visible_root(directory_fd)
                    return ()
                if not initialized:
                    raise CodingWorkerReceiptError("coding_worker_receipt_lock_corrupt")
                records = self._decode(raw)
            self._assert_visible_root(directory_fd)
            return records

    def issue(
        self,
        *,
        directory_fd: int,
        policy: ProductWorkerActivationPolicyV1,
        opt_in_decision_digest: str,
    ) -> ProductWorkerActivationReceiptV1:
        """Append or return an exact current policy receipt under one lock."""

        if (
            not isinstance(policy, ProductWorkerActivationPolicyV1)
            or type(opt_in_decision_digest) is not str
            or len(opt_in_decision_digest) != 64
            or any(char not in "0123456789abcdef" for char in opt_in_decision_digest)
        ):
            raise ValueError("Windows Worker receipt issue input is invalid")
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
                    raise CodingWorkerReceiptError("coding_worker_receipt_lock_corrupt")
                records = () if raw is None else self._decode(raw)
                latest = next(
                    (
                        record
                        for record in reversed(records)
                        if record.receipt.policy.session_id == policy.session_id
                        and record.receipt.policy.plugin_id == policy.plugin_id
                    ),
                    None,
                )
                if (
                    latest is not None
                    and latest.opt_in_decision_digest == opt_in_decision_digest
                    and latest.receipt.policy.fingerprint == policy.fingerprint
                ):
                    self._assert_visible_root(directory_fd)
                    return latest.receipt
                if len(records) >= _MAX_RECEIPTS:
                    raise CodingWorkerReceiptError("coding_worker_receipt_capacity")
                receipt = ProductWorkerActivationReceiptV1(
                    policy=policy,
                    issue_sequence=len(records) + 1,
                    issue_nonce=secrets.token_hex(16),
                )
                record = CodingWorkerReceiptRecordV1.create(
                    journal_revision=len(records) + 1,
                    scope_id=self._scope_id,
                    opt_in_decision_digest=opt_in_decision_digest,
                    receipt=receipt,
                )
                line = canonical_json_bytes(record.to_dict()) + b"\n"
                if len(raw or b"") + len(line) > _MAX_BYTES:
                    raise CodingWorkerReceiptError("coding_worker_receipt_capacity")
                if not initialized:
                    self._mark_lock_initialized(lock_handle)
                self._append(directory_fd, acl, expected=raw, line=line)
                self._assert_visible_root(directory_fd)
                return receipt

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
                raise CodingWorkerReceiptError(
                    "coding_worker_receipt_lock_missing"
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
                    raise OSError("Windows Worker receipt lock write failed")
                windows_flush_file(descriptor)
            elif os.fstat(descriptor).st_size != 1:
                raise CodingWorkerReceiptError("coding_worker_receipt_lock_corrupt")
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
                raise CodingWorkerReceiptError("coding_worker_receipt_lock_corrupt")
            state = os.read(descriptor, 1)
            if state not in {b"\0", b"\1"}:
                raise CodingWorkerReceiptError("coding_worker_receipt_lock_corrupt")
            return state == b"\1"
        finally:
            os.close(descriptor)

    @staticmethod
    def _mark_lock_initialized(handle: BinaryIO) -> None:
        handle.seek(0)
        if handle.read(1) != b"\0":
            raise CodingWorkerReceiptError("coding_worker_receipt_lock_corrupt")
        handle.seek(0)
        if handle.write(b"\1") != 1:
            raise OSError("Windows Worker receipt lock commit failed")
        handle.flush()
        windows_flush_file(handle.fileno())

    def _read_raw(
        self, directory_fd: int, acl: WindowsPrivateDirectoryAcl
    ) -> bytes | None:
        try:
            descriptor = open_windows_regular_file_at(
                directory_fd, _NAME, create_new=False, write=False, read_control=True
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
                raise CodingWorkerReceiptError("coding_worker_receipt_changed")
            output.seek(0, os.SEEK_END)
            remaining = memoryview(line)
            while remaining:
                written = output.write(remaining)
                if written is None or written <= 0:
                    raise OSError("Windows Worker receipt append made no progress")
                remaining = remaining[written:]
            output.flush()
            windows_flush_file(output.fileno())
        if created:
            windows_flush_directory(directory_fd)

    def _decode(self, raw: bytes) -> tuple[CodingWorkerReceiptRecordV1, ...]:
        if not raw or len(raw) > _MAX_BYTES or not raw.endswith(b"\n"):
            raise CodingWorkerReceiptError("coding_worker_receipt_corrupt")
        try:
            records = _decode_coding_worker_receipt_history(
                raw,
                path=self._path,
                scope_id=self._scope_id,
                load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
            )
            if raw != b"".join(
                canonical_json_bytes(record.to_dict()) + b"\n" for record in records
            ):
                raise ValueError("Windows Worker receipt bytes changed")
            return records
        except (UnicodeError, ValueError) as exc:
            raise CodingWorkerReceiptError("coding_worker_receipt_corrupt") from exc

    def _assert_visible_root(self, directory_fd: int) -> None:
        try:
            if not os.path.samestat(os.fstat(directory_fd), self._path.parent.lstat()):
                raise CodingWorkerReceiptError(
                    "coding_worker_receipt_state_root_changed"
                )
        except OSError as exc:
            raise CodingWorkerReceiptError(
                "coding_worker_receipt_state_root_changed"
            ) from exc

    @staticmethod
    def _require_root(directory_fd: int) -> None:
        if os.name != "nt" or type(directory_fd) is not int or directory_fd < 0:
            raise OSError("Windows Worker receipt requires a pinned Product root")

    @staticmethod
    def _require_plain_stream(descriptor: int) -> None:
        if windows_regular_file_stream_names(descriptor) != ("::$DATA",):
            raise CodingWorkerReceiptError("coding_worker_receipt_stream_invalid")


__all__ = ["CodingWindowsWorkerReceiptJournal"]
