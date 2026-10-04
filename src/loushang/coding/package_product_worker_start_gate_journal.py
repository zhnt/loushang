"""Product-fixed intent and native-identity history for gated Linux Workers.

An intent proves only that the Product reserved one attempt before spawning.
A bound record precedes release and identifies the exact Hosting child. Neither
record alone authorizes recovery cleanup or third-party Worker admission.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalLoadPolicy,
    append_jsonl_record,
    decode_jsonl,
)
from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.gated_start import WorkerNativeProcessIdentityV1

from .package_product_worker_history_segments import (
    CodingWorkerHistorySegmentError,
    CodingWorkerSegmentedHistoryV1,
    read_coding_worker_segmented_history,
    seal_coding_worker_active_segment,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_FILE_NAME = "worker-start-gates.jsonl"
_MAX_EVENTS = 4096
_MAX_BYTES = 32 * 1024 * 1024
_FORMAT = replace(SORTED_UNICODE_JSONL_FORMAT, separators=(",", ":"))
_IDENTITY_FIELDS = {
    "bootId",
    "pid",
    "pidNamespaceDevice",
    "pidNamespaceInode",
    "startTicks",
    "userId",
}


class CodingWorkerStartGateJournalError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _identity_dict(identity: WorkerNativeProcessIdentityV1) -> dict[str, object]:
    return {
        "bootId": identity.boot_id,
        "pid": identity.pid,
        "pidNamespaceDevice": identity.pid_namespace_device,
        "pidNamespaceInode": identity.pid_namespace_inode,
        "startTicks": identity.start_ticks,
        "userId": identity.user_id,
    }


def _identity_from_dict(value: object) -> WorkerNativeProcessIdentityV1:
    if type(value) is not dict or set(value) != _IDENTITY_FIELDS:
        raise ValueError("Worker gate native identity fields are invalid")
    return WorkerNativeProcessIdentityV1(
        pid=value["pid"],
        start_ticks=value["startTicks"],
        boot_id=value["bootId"],
        user_id=value["userId"],
        pid_namespace_device=value["pidNamespaceDevice"],
        pid_namespace_inode=value["pidNamespaceInode"],
    )


@dataclass(frozen=True, slots=True)
class CodingWorkerStartGateRecordV1:
    journal_revision: int
    phase: Literal["intent", "bound"]
    attempt_id: str
    worker_identity_fingerprint: str
    receipt_fingerprint: str
    policy_fingerprint: str
    scope_id: str
    native_closure_digest: str
    identity: WorkerNativeProcessIdentityV1 | None
    record_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.journal_revision) is not int
            or self.journal_revision < 1
            or self.phase not in {"intent", "bound"}
            or type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (
                    self.worker_identity_fingerprint,
                    self.receipt_fingerprint,
                    self.policy_fingerprint,
                    self.native_closure_digest,
                )
            )
            or type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or (self.phase == "intent") != (self.identity is None)
            or (
                self.identity is not None
                and type(self.identity) is not WorkerNativeProcessIdentityV1
            )
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Worker start gate record is invalid")

    @classmethod
    def create(
        cls,
        *,
        journal_revision: int,
        phase: Literal["intent", "bound"],
        attempt_id: str,
        worker_identity_fingerprint: str,
        receipt_fingerprint: str,
        policy_fingerprint: str,
        scope_id: str,
        native_closure_digest: str,
        identity: WorkerNativeProcessIdentityV1 | None,
    ) -> CodingWorkerStartGateRecordV1:
        unsigned = {
            "attemptId": attempt_id,
            "workerIdentityFingerprint": worker_identity_fingerprint,
            "identity": None if identity is None else _identity_dict(identity),
            "journalRevision": journal_revision,
            "nativeClosureDigest": native_closure_digest,
            "phase": phase,
            "policyFingerprint": policy_fingerprint,
            "receiptFingerprint": receipt_fingerprint,
            "recordVersion": 1,
            "scopeId": scope_id,
        }
        return cls(
            journal_revision=journal_revision,
            phase=phase,
            attempt_id=attempt_id,
            worker_identity_fingerprint=worker_identity_fingerprint,
            receipt_fingerprint=receipt_fingerprint,
            policy_fingerprint=policy_fingerprint,
            scope_id=scope_id,
            native_closure_digest=native_closure_digest,
            identity=identity,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "workerIdentityFingerprint": self.worker_identity_fingerprint,
            "identity": None
            if self.identity is None
            else _identity_dict(self.identity),
            "journalRevision": self.journal_revision,
            "nativeClosureDigest": self.native_closure_digest,
            "phase": self.phase,
            "policyFingerprint": self.policy_fingerprint,
            "receiptFingerprint": self.receipt_fingerprint,
            "recordVersion": 1,
            "scopeId": self.scope_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "recordDigest": self.record_digest}

    @classmethod
    def from_dict(cls, value: object) -> CodingWorkerStartGateRecordV1:
        if (
            type(value) is not dict
            or set(value)
            != {
                "attemptId",
                "workerIdentityFingerprint",
                "identity",
                "journalRevision",
                "nativeClosureDigest",
                "phase",
                "policyFingerprint",
                "receiptFingerprint",
                "recordDigest",
                "recordVersion",
                "scopeId",
            }
            or value["recordVersion"] != 1
        ):
            raise ValueError("Worker start gate record fields are invalid")
        identity = value["identity"]
        return cls(
            journal_revision=value["journalRevision"],
            phase=value["phase"],
            attempt_id=value["attemptId"],
            worker_identity_fingerprint=value["workerIdentityFingerprint"],
            receipt_fingerprint=value["receiptFingerprint"],
            policy_fingerprint=value["policyFingerprint"],
            scope_id=value["scopeId"],
            native_closure_digest=value["nativeClosureDigest"],
            identity=None if identity is None else _identity_from_dict(identity),
            record_digest=value["recordDigest"],
        )


def _decode(value: object) -> CodingWorkerStartGateRecordV1:
    try:
        return CodingWorkerStartGateRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Worker start gate record is invalid",
            code="coding_worker_start_gate_record_invalid",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingWorkerStartGateRecordV1.to_dict,
    decoder=_decode,
)


class CodingWorkerStartGateJournal:
    """One Product-private intent/bound history; reads grant no recovery power."""

    def __init__(self, product: PosixLocalWheelProductSessionOwner) -> None:
        if (
            not isinstance(product, PosixLocalWheelProductSessionOwner)
            or product.policy.product_id != "coding"
            or not any(
                binding.source_trust_class == "local-worker-candidate"
                for binding in product.policy.bindings
            )
        ):
            raise ValueError("Coding Worker candidate Product owner is required")
        self._product = product
        self._path = product.state_root / _FILE_NAME
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="raise", create_lock=False)

    @property
    def path(self) -> Path:
        return self._path

    def current(self, attempt_id: str) -> CodingWorkerStartGateRecordV1 | None:
        if type(attempt_id) is not str or _ATTEMPT.fullmatch(attempt_id) is None:
            raise ValueError("Worker gate attempt ID is invalid")
        with self._product.gc_gate.guard():
            self._product.assert_root_gc_authority_current()
            with self._bound_journal(create_lock=False) as rooted:
                records = self._load(rooted)
                return next(
                    (
                        record
                        for record in reversed(records)
                        if record.attempt_id == attempt_id
                    ),
                    None,
                )

    def attempts(self) -> tuple[CodingWorkerStartGateRecordV1, ...]:
        """Inventory every retained attempt without granting recovery authority."""

        with self._product.gc_gate.guard():
            self._product.assert_root_gc_authority_current()
            with self._bound_journal(create_lock=False) as rooted:
                latest: dict[str, CodingWorkerStartGateRecordV1] = {}
                for record in self._load(rooted):
                    latest[record.attempt_id] = record
                self._product.assert_root_gc_authority_current()
                return tuple(
                    sorted(latest.values(), key=lambda record: record.journal_revision)
                )

    def append(
        self,
        *,
        phase: Literal["intent", "bound"],
        attempt_id: str,
        worker_identity_fingerprint: str,
        receipt_fingerprint: str,
        policy_fingerprint: str,
        scope_id: str,
        native_closure_digest: str,
        identity: WorkerNativeProcessIdentityV1 | None = None,
    ) -> CodingWorkerStartGateRecordV1:
        with self._product.gc_gate.guard():
            self._product.assert_root_gc_authority_current()
            with self._bound_journal() as rooted:
                records, history = self._load_history(rooted)
                previous = next(
                    (
                        record
                        for record in reversed(records)
                        if record.attempt_id == attempt_id
                    ),
                    None,
                )
                if (phase == "intent" and previous is not None) or (
                    phase == "bound"
                    and (previous is None or previous.phase != "intent")
                ):
                    raise CodingWorkerStartGateJournalError(
                        "coding_worker_start_gate_attempt_conflict"
                    )
                if previous is not None and (
                    previous.receipt_fingerprint != receipt_fingerprint
                    or previous.worker_identity_fingerprint
                    != worker_identity_fingerprint
                    or previous.policy_fingerprint != policy_fingerprint
                    or previous.scope_id != scope_id
                    or previous.native_closure_digest != native_closure_digest
                ):
                    raise CodingWorkerStartGateJournalError(
                        "coding_worker_start_gate_binding_changed"
                    )
                record = CodingWorkerStartGateRecordV1.create(
                    journal_revision=len(records) + 1,
                    phase=phase,
                    attempt_id=attempt_id,
                    worker_identity_fingerprint=worker_identity_fingerprint,
                    receipt_fingerprint=receipt_fingerprint,
                    policy_fingerprint=policy_fingerprint,
                    scope_id=scope_id,
                    native_closure_digest=native_closure_digest,
                    identity=identity,
                )
                active_records = len(records) - history.last_sealed_revision
                record_bytes = canonical_json_bytes(record.to_dict()) + b"\n"
                if len(record_bytes) > _MAX_BYTES:
                    raise CodingWorkerStartGateJournalError(
                        "coding_worker_start_gate_capacity"
                    )
                if (
                    active_records >= _MAX_EVENTS
                    or len(history.active_raw) + len(record_bytes) > _MAX_BYTES
                ):
                    try:
                        seal_coding_worker_active_segment(
                            rooted,
                            stem="worker-start-gates",
                            stream_id="worker-start-gates",
                            history=history,
                            last_revision=len(records),
                        )
                    except CodingWorkerHistorySegmentError as exc:
                        raise CodingWorkerStartGateJournalError(exc.code) from exc
                    target = rooted.sibling(
                        f"worker-start-gates.g{history.active_generation + 1:08d}.jsonl"
                    )
                else:
                    target = rooted.sibling(
                        self._path.name
                        if history.active_generation == 0
                        else f"worker-start-gates.g{history.active_generation:08d}.jsonl"
                    )
                append_jsonl_record(
                    self._path,
                    record,
                    record_codec=_CODEC,
                    format_profile=_FORMAT,
                    durability=self._durability,
                    bound_file=target,
                )
                return record

    @contextmanager
    def _bound_journal(self, *, create_lock: bool = True) -> Iterator[RootedFile]:
        try:
            root_fd = os.open(
                self._path.parent,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        except OSError as exc:
            raise CodingWorkerStartGateJournalError(
                "coding_worker_start_gate_root_unsafe"
            ) from exc
        try:
            opened = os.fstat(root_fd)
            visible = self._path.parent.lstat()
            if (
                not stat.S_ISDIR(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) & 0o077
                or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
            ):
                raise CodingWorkerStartGateJournalError(
                    "coding_worker_start_gate_root_unsafe"
                )
            io = RootedFileIO(self._path.parent, root_fd)
            try:
                with io.bind(self._path, durable=True) as rooted:
                    if create_lock:
                        rooted.acquire_lock(exclusive=True, suffix=".lock")
                    else:
                        try:
                            rooted.stat()
                        except FileNotFoundError:
                            try:
                                rooted.sibling(self._path.name + ".lock").stat()
                            except FileNotFoundError:
                                pass
                            else:
                                raise CodingWorkerStartGateJournalError(
                                    "coding_worker_start_gate_orphan_lock"
                                ) from None
                        else:
                            try:
                                rooted.acquire_lock(
                                    exclusive=False, suffix=".lock", create=False
                                )
                            except FileNotFoundError as exc:
                                raise CodingWorkerStartGateJournalError(
                                    "coding_worker_start_gate_lock_missing"
                                ) from exc
                    yield rooted
            finally:
                io.cleanup()
            after = self._path.parent.lstat()
            if (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino):
                raise CodingWorkerStartGateJournalError(
                    "coding_worker_start_gate_root_changed"
                )
        finally:
            os.close(root_fd)

    def _load(self, rooted: RootedFile) -> tuple[CodingWorkerStartGateRecordV1, ...]:
        records, _history = self._load_history(rooted)
        return records

    def _load_history(
        self, rooted: RootedFile
    ) -> tuple[
        tuple[CodingWorkerStartGateRecordV1, ...], CodingWorkerSegmentedHistoryV1
    ]:
        try:
            history = read_coding_worker_segmented_history(
                rooted,
                stem="worker-start-gates",
                stream_id="worker-start-gates",
                max_segment_bytes=_MAX_BYTES,
            )
        except CodingWorkerHistorySegmentError as exc:
            raise CodingWorkerStartGateJournalError(exc.code) from exc
        try:
            all_records: list[CodingWorkerStartGateRecordV1] = []
            for generation, raw in enumerate(history.segments):
                segment_records: tuple[CodingWorkerStartGateRecordV1, ...] = (
                    decode_jsonl(
                        raw.decode("utf-8"),
                        target=self._path,
                        record_codec=_CODEC,
                        load_policy=self._load_policy,
                    ).records
                )
                lines = raw.splitlines(keepends=True)
                first_revision = len(all_records) + 1
                if (
                    len(segment_records) > _MAX_EVENTS
                    or len(lines) != len(segment_records)
                    or any(
                        record.journal_revision != index
                        or line != canonical_json_bytes(record.to_dict()) + b"\n"
                        for index, (record, line) in enumerate(
                            zip(segment_records, lines, strict=True), first_revision
                        )
                    )
                ):
                    raise ValueError("Worker gate history changed")
                all_records.extend(segment_records)
                if (
                    history.manifest is not None
                    and generation < history.active_generation
                    and len(all_records)
                    != history.manifest.sealed[generation].last_revision
                ):
                    raise ValueError("Worker gate sealed revision changed")
            records = tuple(all_records)
            latest: dict[str, CodingWorkerStartGateRecordV1] = {}
            for record in records:
                previous = latest.get(record.attempt_id)
                if record.phase == "intent":
                    if previous is not None:
                        raise ValueError("Worker gate attempt repeated")
                elif (
                    previous is None
                    or previous.phase != "intent"
                    or previous.receipt_fingerprint != record.receipt_fingerprint
                    or previous.worker_identity_fingerprint
                    != record.worker_identity_fingerprint
                    or previous.policy_fingerprint != record.policy_fingerprint
                    or previous.scope_id != record.scope_id
                    or previous.native_closure_digest != record.native_closure_digest
                ):
                    raise ValueError("Worker gate binding changed")
                latest[record.attempt_id] = record
            return records, history
        except (JournalCodecError, UnicodeError, ValueError) as exc:
            raise CodingWorkerStartGateJournalError(
                "coding_worker_start_gate_corrupt"
            ) from exc


__all__ = [
    "CodingWorkerStartGateJournal",
    "CodingWorkerStartGateJournalError",
    "CodingWorkerStartGateRecordV1",
]
