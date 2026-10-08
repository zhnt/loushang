"""Product-owned, default-dark approval of one exact Linux Worker release.

The approval journal is separate from both the Worker Wheel and its native
release Wheel. Its decisions are inert until an explicit Product install or
repair checks the current decision under the shared selection/GC gate.
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

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_OPAQUE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:@+-]*[A-Za-z0-9])?\Z")
_MAX_EVENTS = 256
_JOURNAL_NAME = "worker-native-release-approvals.jsonl"


class CodingWorkerNativeApprovalError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerNativeReleaseApprovalV1:
    """Exact release bytes accepted independently of the Worker package."""

    wheel_sha256: str
    catalog_sha256: str
    launcher_sha256: str
    profile_sha256: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or _DIGEST.fullmatch(value) is None
            for value in (
                self.wheel_sha256,
                self.catalog_sha256,
                self.launcher_sha256,
                self.profile_sha256,
            )
        ):
            raise ValueError("Worker native release approval is invalid")

    def to_dict(self) -> dict[str, str]:
        return {
            "catalogSha256": self.catalog_sha256,
            "launcherSha256": self.launcher_sha256,
            "profileSha256": self.profile_sha256,
            "wheelSha256": self.wheel_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingWorkerNativeReleaseApprovalV1:
        if type(value) is not dict or set(value) != {
            "catalogSha256",
            "launcherSha256",
            "profileSha256",
            "wheelSha256",
        }:
            raise ValueError("Worker native release approval record is invalid")
        return cls(
            wheel_sha256=value["wheelSha256"],
            catalog_sha256=value["catalogSha256"],
            launcher_sha256=value["launcherSha256"],
            profile_sha256=value["profileSha256"],
        )


@dataclass(frozen=True, slots=True)
class CodingWorkerNativeReleaseReviewV1:
    """Exact operator review of one Wheel under one Product source policy."""

    scope_id: str
    product_policy_revision: str
    approval: CodingWorkerNativeReleaseApprovalV1
    review_id: str
    review_version: int = 1

    def __post_init__(self) -> None:
        if (
            not _valid_opaque(self.scope_id)
            or not _valid_opaque(self.product_policy_revision)
            or not isinstance(self.approval, CodingWorkerNativeReleaseApprovalV1)
            or self.review_version != 1
            or self.review_id != self._fingerprint()
        ):
            raise ValueError("Worker native release review is invalid")

    @classmethod
    def create(
        cls,
        *,
        scope_id: str,
        product_policy_revision: str,
        approval: CodingWorkerNativeReleaseApprovalV1,
    ) -> CodingWorkerNativeReleaseReviewV1:
        values = {
            "approval": approval.to_dict(),
            "productPolicyRevision": product_policy_revision,
            "reviewVersion": 1,
            "scopeId": scope_id,
        }
        return cls(
            scope_id=scope_id,
            product_policy_revision=product_policy_revision,
            approval=approval,
            review_id=sha256(canonical_json_bytes(values)).hexdigest(),
        )

    def _fingerprint(self) -> str:
        return sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "approval": self.approval.to_dict(),
            "productPolicyRevision": self.product_policy_revision,
            "reviewVersion": self.review_version,
            "scopeId": self.scope_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "reviewId": self.review_id}


@dataclass(frozen=True, slots=True)
class CodingWorkerNativeApprovalDecisionV1:
    journal_revision: int
    scope_id: str
    operation_id: str
    generation: int
    action: Literal["approve", "revoke"]
    approval: CodingWorkerNativeReleaseApprovalV1 | None
    record_digest: str
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.journal_revision) is not int
            or self.journal_revision < 1
            or type(self.generation) is not int
            or self.generation < 1
            or not _valid_opaque(self.scope_id)
            or not _valid_opaque(self.operation_id)
            or self.action not in {"approve", "revoke"}
            or (self.action == "approve")
            != isinstance(self.approval, CodingWorkerNativeReleaseApprovalV1)
            or self.record_version != 1
            or not isinstance(self.record_digest, str)
            or _DIGEST.fullmatch(self.record_digest) is None
            or self.record_digest != self._fingerprint()
        ):
            raise ValueError("Worker native approval decision is invalid")

    @classmethod
    def create(
        cls,
        *,
        journal_revision: int,
        scope_id: str,
        operation_id: str,
        generation: int,
        action: Literal["approve", "revoke"],
        approval: CodingWorkerNativeReleaseApprovalV1 | None,
    ) -> CodingWorkerNativeApprovalDecisionV1:
        unsigned = {
            "action": action,
            "approval": None if approval is None else approval.to_dict(),
            "generation": generation,
            "journalRevision": journal_revision,
            "operationId": operation_id,
            "recordVersion": 1,
            "scopeId": scope_id,
        }
        return cls(
            journal_revision=journal_revision,
            scope_id=scope_id,
            operation_id=operation_id,
            generation=generation,
            action=action,
            approval=approval,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "approval": None if self.approval is None else self.approval.to_dict(),
            "generation": self.generation,
            "journalRevision": self.journal_revision,
            "operationId": self.operation_id,
            "recordVersion": self.record_version,
            "scopeId": self.scope_id,
        }

    def _fingerprint(self) -> str:
        return sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "recordDigest": self.record_digest}

    @classmethod
    def from_dict(cls, value: object) -> CodingWorkerNativeApprovalDecisionV1:
        if type(value) is not dict or set(value) != {
            "action",
            "approval",
            "generation",
            "journalRevision",
            "operationId",
            "recordDigest",
            "recordVersion",
            "scopeId",
        }:
            raise ValueError("Worker native approval decision shape is invalid")
        approval = value["approval"]
        return cls(
            journal_revision=value["journalRevision"],
            scope_id=value["scopeId"],
            operation_id=value["operationId"],
            generation=value["generation"],
            action=value["action"],
            approval=(
                None
                if approval is None
                else CodingWorkerNativeReleaseApprovalV1.from_dict(approval)
            ),
            record_digest=value["recordDigest"],
            record_version=value["recordVersion"],
        )


def _decode(value: object) -> CodingWorkerNativeApprovalDecisionV1:
    try:
        return CodingWorkerNativeApprovalDecisionV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Worker native approval decision record is invalid",
            code="coding_worker_native_approval_record_invalid",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingWorkerNativeApprovalDecisionV1.to_dict,
    decoder=_decode,
)


def _decode_coding_worker_native_approval_history(
    raw: bytes, *, path: Path, scope_id: str
) -> tuple[CodingWorkerNativeApprovalDecisionV1, ...]:
    """Replay one exact Product scope's native-release approval decisions."""

    if len(raw) > 4 * 1024 * 1024:
        raise CodingWorkerNativeApprovalError("coding_worker_native_approval_capacity")
    events: tuple[CodingWorkerNativeApprovalDecisionV1, ...] = decode_jsonl(
        raw.decode("utf-8"),
        target=path,
        record_codec=_CODEC,
        load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
    ).records
    if len(events) > _MAX_EVENTS:
        raise CodingWorkerNativeApprovalError("coding_worker_native_approval_capacity")
    seen_operations: set[str] = set()
    for revision, event in enumerate(events, 1):
        if (
            event.scope_id != scope_id
            or event.journal_revision != revision
            or event.generation != revision
            or event.operation_id in seen_operations
            or (
                event.action == "revoke"
                and (revision == 1 or events[revision - 2].action != "approve")
            )
        ):
            raise CodingWorkerNativeApprovalError(
                "coding_worker_native_approval_corrupt"
            )
        seen_operations.add(event.operation_id)
    return events


class CodingWorkerNativeApprovalJournal:
    """Exact Product-root approval with CAS, replay, and durable revocation."""

    def __init__(self, product_owner: PosixLocalWheelProductSessionOwner) -> None:
        if (
            not isinstance(product_owner, PosixLocalWheelProductSessionOwner)
            or product_owner.policy.product_id != "coding"
            or not any(
                binding.source_trust_class == "local-worker-candidate"
                for binding in product_owner.policy.bindings
            )
        ):
            raise ValueError("Coding Product Worker candidate owner is required")
        self._product_owner = product_owner
        self._path = product_owner.state_root / _JOURNAL_NAME
        self._scope_id = product_owner.policy.project_scope_id
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)

    @property
    def product_owner(self) -> PosixLocalWheelProductSessionOwner:
        return self._product_owner

    @property
    def path(self) -> Path:
        return self._path

    def current(self) -> CodingWorkerNativeApprovalDecisionV1 | None:
        with self._product_owner.gc_gate.guard(), self._bound_journal() as rooted:
            self._product_owner.assert_root_gc_authority_current()
            events = self._load(rooted)
            return events[-1] if events else None

    def change(
        self,
        *,
        operation_id: str,
        expected_generation: int,
        action: Literal["approve", "revoke"],
        approval: CodingWorkerNativeReleaseApprovalV1 | None,
    ) -> CodingWorkerNativeApprovalDecisionV1:
        if (
            not _valid_opaque(operation_id)
            or type(expected_generation) is not int
            or expected_generation < 0
            or action not in {"approve", "revoke"}
            or (action == "approve")
            != isinstance(approval, CodingWorkerNativeReleaseApprovalV1)
        ):
            raise ValueError("Worker native approval command is invalid")
        with self._product_owner.gc_gate.guard(), self._bound_journal() as rooted:
            self._product_owner.assert_root_gc_authority_current()
            events = self._load(rooted)
            replay = next(
                (item for item in events if item.operation_id == operation_id), None
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
            append_jsonl_record(
                self._path,
                decision,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._durability,
                bound_file=rooted,
            )
            return decision

    @contextmanager
    def _bound_journal(self) -> Iterator[RootedFile]:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        parent_fd = os.open(self._path.parent, flags)
        try:
            opened = os.fstat(parent_fd)
            visible = self._path.parent.lstat()
            if (
                not stat.S_ISDIR(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) & 0o077
                or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
            ):
                raise CodingWorkerNativeApprovalError(
                    "coding_worker_native_approval_state_root_unsafe"
                )
            file_io = RootedFileIO(self._path.parent, parent_fd)
            try:
                with file_io.bind(self._path, durable=True) as rooted:
                    rooted.acquire_lock(exclusive=True, suffix=".lock")
                    yield rooted
            finally:
                file_io.cleanup()
            visible_after = self._path.parent.lstat()
            if (opened.st_dev, opened.st_ino) != (
                visible_after.st_dev,
                visible_after.st_ino,
            ):
                raise CodingWorkerNativeApprovalError(
                    "coding_worker_native_approval_state_root_changed"
                )
        finally:
            os.close(parent_fd)

    def _load(
        self, rooted: RootedFile
    ) -> tuple[CodingWorkerNativeApprovalDecisionV1, ...]:
        try:
            raw = rooted.read_bytes(max_bytes=4 * 1024 * 1024)
        except FileNotFoundError:
            return ()
        return _decode_coding_worker_native_approval_history(
            raw, path=self._path, scope_id=self._scope_id
        )


def _valid_opaque(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 128
        and _OPAQUE.fullmatch(value) is not None
    )


__all__ = [
    "CodingWorkerNativeApprovalDecisionV1",
    "CodingWorkerNativeApprovalError",
    "CodingWorkerNativeApprovalJournal",
    "CodingWorkerNativeReleaseApprovalV1",
    "CodingWorkerNativeReleaseReviewV1",
]
