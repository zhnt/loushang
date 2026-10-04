"""Durable revision CAS for one Windows LPAC Worker provisioning attempt.

The Product fixes the path under its pinned private state root.  This journal
only stores the pathless bridge document; it never provisions a profile,
starts a process, or decides whether an attempt may resume.
"""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO, cast

from loushang.foundation.json import dump_json_value
from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    decode_jsonl,
    journal_file_lock,
    journal_file_lock_at,
    journal_file_read_lock,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
    windows_flush_directory,
    windows_flush_file,
    windows_listdir_at,
    windows_regular_file_stream_names,
    windows_stat_at,
)
from loushang.harness.resources.plugins.locators import canonical_plugin_relative_path
from loushang.harness.worker._native_profile_bridge import (
    _WINDOWS_LPAC_PROFILE_ID,
    _require_opaque,
    _validate_windows_journal,
)
from loushang.harness.worker.contracts import WorkerBindingError

_NAME = re.compile(r"worker-native-provisioning-([0-9a-f]{32})\.jsonl\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_IDENTITY_FIELDS = frozenset(
    {
        "attemptId",
        "executableRelativePath",
        "jobObjectName",
        "journalVersion",
        "lifecycleFingerprint",
        "nativeProfileCatalogRevision",
        "nativeProfileId",
        "operationNonce",
        "ownerGeneration",
        "receiptFingerprint",
        "specFingerprint",
        "workerRequestFingerprint",
    }
)
_MAX_ATTEMPTS = 1024
_MAX_BYTES = 4 * 1024 * 1024
_MAX_REVISIONS = 256
_FORMAT = replace(SORTED_UNICODE_JSONL_FORMAT, separators=(",", ":"))
_UNLOCKED = replace(DURABLE_LOCKED_JOURNAL, locking=False)
_STRICT_LOAD = JournalLoadPolicy(partial_tail="raise", create_lock=False)


class WindowsWorkerProvisioningStateJournalError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class WindowsWorkerProvisioningAttemptV1:
    """Read-only recovery inventory; it grants no native cleanup authority."""

    attempt_id: str
    phase: str
    state_revision: int
    identity: dict[str, object]
    phase_history: tuple[str, ...]
    witness_present_history: tuple[bool, ...]
    last_witness_state: str | None

    @property
    def unsettled(self) -> bool:
        return self.phase != "settled"


def _canonical(value: object) -> bytes:
    return dump_json_value(
        value,
        name="worker_native_provisioning_state",
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _inventory_identity(name: str, raw: bytes) -> dict[str, object]:
    """Seed strict replay from the first record without trusting its identity."""

    match = _NAME.fullmatch(name)
    if match is None or not raw or len(raw) > _MAX_BYTES:
        raise WindowsWorkerProvisioningStateJournalError(
            "worker_native_provisioning_inventory_invalid"
        )
    try:
        first = json.loads(raw.split(b"\n", 1)[0])
        document = first["document"]
        if type(first) is not dict or type(document) is not dict:
            raise ValueError("Worker provisioning inventory record is invalid")
        identity = {key: document[key] for key in _IDENTITY_FIELDS}
        if (
            type(identity["attemptId"]) is not str
            or identity["attemptId"] != match.group(1)
            or type(identity["journalVersion"]) is not int
            or identity["journalVersion"] != 3
            or identity["nativeProfileId"] != _WINDOWS_LPAC_PROFILE_ID
            or type(identity["ownerGeneration"]) is not int
            or identity["ownerGeneration"] < 1
            or type(identity["nativeProfileCatalogRevision"]) is not str
            or any(
                type(identity[key]) is not str
                or _DIGEST.fullmatch(identity[key]) is None
                for key in (
                    "lifecycleFingerprint",
                    "operationNonce",
                    "receiptFingerprint",
                    "specFingerprint",
                    "workerRequestFingerprint",
                )
            )
        ):
            raise ValueError("Worker provisioning inventory identity is invalid")
        if identity["jobObjectName"] != (
            "Global\\LoushangWorker-" + cast(str, identity["operationNonce"])
        ):
            raise ValueError("Worker provisioning inventory Job identity is invalid")
        relative = identity["executableRelativePath"]
        if (
            type(relative) is not str
            or len(relative.encode("utf-8")) > 1024
            or canonical_plugin_relative_path(relative).as_posix() != relative
        ):
            raise ValueError("Worker provisioning executable path is invalid")
        _require_opaque(
            identity["nativeProfileCatalogRevision"],
            name="profile catalog revision",
        )
        return identity
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise WindowsWorkerProvisioningStateJournalError(
            "worker_native_provisioning_inventory_invalid"
        ) from exc


def inspect_windows_worker_provisioning_attempts(
    state_root: Path, *, directory_fd: int
) -> tuple[WindowsWorkerProvisioningAttemptV1, ...]:
    """Enumerate every retained attempt through a Product-pinned Windows root.

    A corrupt or orphaned entry closes recovery admission. The caller must hold
    the Product GC gate; this is a read-only inventory, not debt settlement.
    """

    if os.name != "nt" or not state_root.is_absolute():
        raise OSError("Windows Worker provisioning inventory requires a native root")
    if type(directory_fd) is not int or directory_fd < 0:
        raise ValueError("Windows Worker provisioning root handle is invalid")
    with WindowsPrivateDirectoryAcl() as acl:
        acl.validate(directory_fd)
        try:
            if not os.path.samestat(os.fstat(directory_fd), state_root.lstat()):
                raise WindowsWorkerProvisioningStateJournalError(
                    "worker_native_provisioning_root_changed"
                )
        except OSError as exc:
            raise WindowsWorkerProvisioningStateJournalError(
                "worker_native_provisioning_root_changed"
            ) from exc
        names = windows_listdir_at(directory_fd)
        prefixed = {
            name
            for name in names
            if name.casefold().startswith("worker-native-provisioning-")
        }
        histories = {name for name in prefixed if _NAME.fullmatch(name)}
        expected = histories | {name + ".lock" for name in histories}
        if prefixed != expected or len(histories) > _MAX_ATTEMPTS:
            raise WindowsWorkerProvisioningStateJournalError(
                "worker_native_provisioning_inventory_invalid"
            )
        results = []
        for name in sorted(histories):
            lock_name = name + ".lock"
            lock_fd = open_windows_regular_file_at(
                directory_fd,
                lock_name,
                create_new=False,
                write=False,
                read_control=True,
            )
            try:
                acl.validate(lock_fd)
                if os.fstat(lock_fd).st_size != 1 or windows_regular_file_stream_names(
                    lock_fd
                ) != ("::$DATA",):
                    raise WindowsWorkerProvisioningStateJournalError(
                        "worker_native_provisioning_lock_corrupt"
                    )
            finally:
                os.close(lock_fd)
            with journal_file_lock_at(directory_fd, lock_name, "shared") as lock_handle:
                lock_handle.seek(0)
                if (
                    os.fstat(lock_handle.fileno()).st_size != 1
                    or windows_regular_file_stream_names(lock_handle.fileno())
                    != ("::$DATA",)
                    or lock_handle.read(1) != b"\1"
                ):
                    raise WindowsWorkerProvisioningStateJournalError(
                        "worker_native_provisioning_lock_corrupt"
                    )
                descriptor = open_windows_regular_file_at(
                    directory_fd,
                    name,
                    create_new=False,
                    write=False,
                    read_control=True,
                )
                with os.fdopen(descriptor, "rb") as source:
                    acl.validate(source.fileno())
                    if windows_regular_file_stream_names(source.fileno()) != (
                        "::$DATA",
                    ):
                        raise WindowsWorkerProvisioningStateJournalError(
                            "worker_native_provisioning_state_unsafe"
                        )
                    raw = source.read(_MAX_BYTES + 1)
                identity = _inventory_identity(name, raw)
                journal = WindowsWorkerProvisioningStateJournal(
                    state_root / name, identity=identity
                )
                records, _ = journal._decode_raw(raw)
                current = records[-1]
                results.append(
                    WindowsWorkerProvisioningAttemptV1(
                        attempt_id=cast(str, identity["attemptId"]),
                        phase=cast(str, current.document["phase"]),
                        state_revision=current.revision,
                        identity=identity,
                        phase_history=tuple(
                            cast(str, record.document["phase"]) for record in records
                        ),
                        witness_present_history=tuple(
                            record.document["witness"] is not None for record in records
                        ),
                        last_witness_state=(
                            None
                            if current.document["witness"] is None
                            else cast(
                                str,
                                cast(dict[str, object], current.document["witness"])[
                                    "state"
                                ],
                            )
                        ),
                    )
                )
        if set(windows_listdir_at(directory_fd)) != set(names):
            raise WindowsWorkerProvisioningStateJournalError(
                "worker_native_provisioning_inventory_changed"
            )
        return tuple(results)


@dataclass(frozen=True, slots=True)
class _Record:
    revision: int
    document: dict[str, object]
    digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "document": self.document,
            "documentDigest": self.digest,
            "journalRevision": self.revision,
            "recordVersion": 1,
        }


class WindowsWorkerProvisioningStateJournal:
    """One strict append-only CAS history under a Product-pinned state root."""

    def __init__(self, path: Path, *, identity: Mapping[str, object]) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("Worker provisioning state path is invalid")
        if type(identity) is not dict:
            raise TypeError("Worker provisioning identity must be a fixed mapping")
        match = _NAME.fullmatch(path.name)
        if match is None or identity.get("attemptId") != match.group(1):
            raise ValueError("Worker provisioning state attempt is invalid")
        self._path = path
        self._identity = dict(identity)
        self._native_commit_uncertain = False
        self._codec = FunctionalJournalRecordCodec(
            encoder=_Record.to_dict,
            decoder=self._decode,
        )

    @property
    def path(self) -> Path:
        return self._path

    def load(self, *, directory_fd: int | None = None) -> Mapping[str, object] | None:
        if self._native_commit_uncertain:
            raise WindowsWorkerProvisioningStateJournalError(
                "worker_native_provisioning_commit_uncertain"
            )
        if directory_fd is not None:
            records, _ = self._read_windows_locked(directory_fd)
            return None if not records else dict(records[-1].document)
        with journal_file_read_lock(self._path, "shared", create_lock=False):
            records, _ = self._read_unlocked()
            return None if not records else dict(records[-1].document)

    def compare_and_swap(
        self,
        *,
        expected_revision: int,
        document: Mapping[str, object],
        directory_fd: int | None = None,
    ) -> bool:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Worker provisioning expected revision is invalid")
        if self._native_commit_uncertain:
            raise WindowsWorkerProvisioningStateJournalError(
                "worker_native_provisioning_commit_uncertain"
            )
        validated = _validate_windows_journal(document, self._identity)
        revision = validated["stateRevision"]
        if revision != expected_revision + 1:
            raise ValueError("Worker provisioning revision must advance by one")
        record = _Record(
            revision=expected_revision + 1,
            document=validated,
            digest=sha256(_canonical(validated)).hexdigest(),
        )
        line = _canonical(record.to_dict()) + b"\n"
        if directory_fd is not None:
            try:
                return self._compare_and_swap_windows(
                    directory_fd,
                    expected_revision=expected_revision,
                    line=line,
                )
            except BaseException:
                # The bridge must not accept a readback after an unproven
                # flush as authority to begin the next native effect.
                self._native_commit_uncertain = True
                raise
        with journal_file_lock(self._path, "exclusive"):
            records, byte_count = self._read_unlocked()
            current = 0 if not records else records[-1].revision
            if current != expected_revision:
                return False
            if len(records) >= _MAX_REVISIONS or byte_count + len(line) > _MAX_BYTES:
                raise WindowsWorkerProvisioningStateJournalError(
                    "worker_native_provisioning_state_capacity"
                )
            append_jsonl_record(
                self._path,
                record,
                record_codec=self._codec,
                format_profile=_FORMAT,
                durability=_UNLOCKED,
            )
            return True

    def _decode(self, value: object) -> _Record:
        try:
            if (
                type(value) is not dict
                or set(value)
                != {
                    "document",
                    "documentDigest",
                    "journalRevision",
                    "recordVersion",
                }
                or type(value["recordVersion"]) is not int
                or value["recordVersion"] != 1
            ):
                raise ValueError("Worker provisioning record fields are invalid")
            document = _validate_windows_journal(value["document"], self._identity)
            revision = value["journalRevision"]
            digest = value["documentDigest"]
            if (
                type(revision) is not int
                or revision < 1
                or document["stateRevision"] != revision
                or type(digest) is not str
                or digest != sha256(_canonical(document)).hexdigest()
            ):
                raise ValueError("Worker provisioning record changed")
            return _Record(revision=revision, document=document, digest=digest)
        except (TypeError, ValueError, WorkerBindingError) as exc:
            raise JournalCodecError(
                "Worker provisioning record is invalid",
                code="invalid_worker_native_provisioning_record",
            ) from exc

    def _read_windows_locked(
        self, directory_fd: int
    ) -> tuple[tuple[_Record, ...], int]:
        self._require_windows_descriptor(directory_fd)
        lock_name = self._path.name + ".lock"
        try:
            windows_stat_at(directory_fd, lock_name)
        except FileNotFoundError:
            try:
                windows_stat_at(directory_fd, self._path.name)
            except FileNotFoundError:
                return (), 0
            raise WindowsWorkerProvisioningStateJournalError(
                "worker_native_provisioning_lock_missing"
            ) from None
        with WindowsPrivateDirectoryAcl() as acl:
            self._validate_windows_lock(directory_fd, acl)
            with journal_file_lock_at(directory_fd, lock_name, "shared"):
                initialized = self._validate_windows_lock(directory_fd, acl)
                records, byte_count = self._read_windows_unlocked(directory_fd, acl)
                if initialized != bool(records):
                    raise WindowsWorkerProvisioningStateJournalError(
                        "worker_native_provisioning_lock_corrupt"
                    )
                return records, byte_count

    def _compare_and_swap_windows(
        self,
        directory_fd: int,
        *,
        expected_revision: int,
        line: bytes,
    ) -> bool:
        self._require_windows_descriptor(directory_fd)
        lock_name = self._path.name + ".lock"
        try:
            windows_stat_at(directory_fd, lock_name)
        except FileNotFoundError:
            try:
                windows_stat_at(directory_fd, self._path.name)
            except FileNotFoundError:
                pass
            else:
                # The writer must never manufacture a new lock around an
                # existing history whose original lock disappeared.
                raise WindowsWorkerProvisioningStateJournalError(
                    "worker_native_provisioning_lock_missing"
                ) from None
        with WindowsPrivateDirectoryAcl() as acl:
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
                created_lock = False
            else:
                created_lock = True
            try:
                acl.validate(descriptor)
                if created_lock:
                    if os.write(descriptor, b"\0") != 1:
                        raise OSError("Worker provisioning lock byte was not written")
                    windows_flush_file(descriptor)
                else:
                    self._validate_windows_lock(directory_fd, acl)
            finally:
                os.close(descriptor)
            if created_lock:
                windows_flush_directory(directory_fd)
            with journal_file_lock_at(
                directory_fd, lock_name, "exclusive"
            ) as lock_handle:
                initialized = self._validate_windows_lock(directory_fd, acl)
                records, byte_count = self._read_windows_unlocked(directory_fd, acl)
                if initialized != bool(records):
                    raise WindowsWorkerProvisioningStateJournalError(
                        "worker_native_provisioning_lock_corrupt"
                    )
                current = 0 if not records else records[-1].revision
                if current != expected_revision:
                    return False
                if (
                    len(records) >= _MAX_REVISIONS
                    or byte_count + len(line) > _MAX_BYTES
                ):
                    raise WindowsWorkerProvisioningStateJournalError(
                        "worker_native_provisioning_state_capacity"
                    )
                if not initialized:
                    self._mark_windows_lock_initialized(lock_handle)
                try:
                    journal_fd = open_windows_regular_file_at(
                        directory_fd,
                        self._path.name,
                        create_new=True,
                        write=True,
                        security_descriptor=acl.security_descriptor,
                        read_control=True,
                    )
                except FileExistsError:
                    journal_fd = open_windows_regular_file_at(
                        directory_fd,
                        self._path.name,
                        create_new=False,
                        write=True,
                        read_control=True,
                    )
                    created_journal = False
                else:
                    created_journal = True
                with os.fdopen(journal_fd, "r+b") as output:
                    acl.validate(output.fileno())
                    if windows_regular_file_stream_names(output.fileno()) != (
                        "::$DATA",
                    ):
                        raise WindowsWorkerProvisioningStateJournalError(
                            "worker_native_provisioning_state_unsafe"
                        )
                    observed = output.read(_MAX_BYTES + 1)
                    if created_journal:
                        same_history = byte_count == 0 and observed == b""
                    else:
                        current_records, current_bytes = self._decode_raw(observed)
                        same_history = (
                            current_bytes == byte_count and current_records == records
                        )
                    if not same_history:
                        raise WindowsWorkerProvisioningStateJournalError(
                            "worker_native_provisioning_state_changed"
                        )
                    output.seek(0, os.SEEK_END)
                    output.write(line)
                    output.flush()
                    windows_flush_file(output.fileno())
                if created_journal:
                    windows_flush_directory(directory_fd)
                return True

    def _validate_windows_lock(
        self, directory_fd: int, acl: WindowsPrivateDirectoryAcl
    ) -> bool:
        descriptor = open_windows_regular_file_at(
            directory_fd,
            self._path.name + ".lock",
            create_new=False,
            write=False,
            read_control=True,
        )
        try:
            acl.validate(descriptor)
            if os.fstat(descriptor).st_size != 1 or windows_regular_file_stream_names(
                descriptor
            ) != ("::$DATA",):
                raise WindowsWorkerProvisioningStateJournalError(
                    "worker_native_provisioning_lock_corrupt"
                )
            state = os.read(descriptor, 1)
            if state not in {b"\0", b"\1"}:
                raise WindowsWorkerProvisioningStateJournalError(
                    "worker_native_provisioning_lock_corrupt"
                )
            return state == b"\1"
        finally:
            os.close(descriptor)

    @staticmethod
    def _mark_windows_lock_initialized(handle: BinaryIO) -> None:
        handle.seek(0)
        if handle.read(1) != b"\0":
            raise WindowsWorkerProvisioningStateJournalError(
                "worker_native_provisioning_lock_corrupt"
            )
        handle.seek(0)
        if handle.write(b"\1") != 1:
            raise OSError("Worker provisioning lock commit failed")
        handle.flush()
        windows_flush_file(handle.fileno())

    def _read_windows_unlocked(
        self, directory_fd: int, acl: WindowsPrivateDirectoryAcl
    ) -> tuple[tuple[_Record, ...], int]:
        try:
            descriptor = open_windows_regular_file_at(
                directory_fd,
                self._path.name,
                create_new=False,
                write=False,
                read_control=True,
            )
        except FileNotFoundError:
            return (), 0
        with os.fdopen(descriptor, "rb") as source:
            acl.validate(source.fileno())
            if windows_regular_file_stream_names(source.fileno()) != ("::$DATA",):
                raise WindowsWorkerProvisioningStateJournalError(
                    "worker_native_provisioning_state_unsafe"
                )
            raw = source.read(_MAX_BYTES + 1)
        return self._decode_raw(raw)

    @staticmethod
    def _require_windows_descriptor(directory_fd: int) -> None:
        if os.name != "nt" or type(directory_fd) is not int or directory_fd < 0:
            raise OSError("Windows Worker provisioning requires a pinned root")

    def _read_unlocked(self) -> tuple[tuple[_Record, ...], int]:
        try:
            visible = self._path.lstat()
        except FileNotFoundError:
            return (), 0
        reparse = bool(
            os.name == "nt"
            and getattr(visible, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
        if not stat.S_ISREG(visible.st_mode) or visible.st_size > _MAX_BYTES or reparse:
            raise WindowsWorkerProvisioningStateJournalError(
                "worker_native_provisioning_state_unsafe"
            )
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        if os.name == "posix":
            flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self._path, flags)
        with os.fdopen(descriptor, "rb") as source:
            opened = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or not os.path.samestat(visible, opened)
                or (
                    os.name == "nt"
                    and getattr(opened, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                )
            ):
                raise WindowsWorkerProvisioningStateJournalError(
                    "worker_native_provisioning_state_unsafe"
                )
            raw = source.read(_MAX_BYTES + 1)
        return self._decode_raw(raw)

    def _decode_raw(self, raw: bytes) -> tuple[tuple[_Record, ...], int]:
        if len(raw) > _MAX_BYTES or not raw or not raw.endswith(b"\n"):
            raise WindowsWorkerProvisioningStateJournalError(
                "worker_native_provisioning_state_corrupt"
            )
        try:
            snapshot: JsonlSnapshot[None, _Record] = decode_jsonl(
                raw.decode("utf-8"),
                target=self._path,
                record_codec=self._codec,
                load_policy=_STRICT_LOAD,
            )
            records = snapshot.records
            if (
                not records
                or len(records) > _MAX_REVISIONS
                or any(
                    record.revision != index
                    for index, record in enumerate(records, start=1)
                )
                or raw
                != b"".join(_canonical(record.to_dict()) + b"\n" for record in records)
            ):
                raise ValueError("Worker provisioning history changed")
            return records, len(raw)
        except (JournalCodecError, JournalFileError, UnicodeError, ValueError) as exc:
            raise WindowsWorkerProvisioningStateJournalError(
                "worker_native_provisioning_state_corrupt"
            ) from exc


__all__ = [
    "WindowsWorkerProvisioningAttemptV1",
    "WindowsWorkerProvisioningStateJournal",
    "WindowsWorkerProvisioningStateJournalError",
    "inspect_windows_worker_provisioning_attempts",
]
