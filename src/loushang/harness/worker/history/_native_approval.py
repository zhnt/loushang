"""Native approval values, history, and shared replay/CAS selection.

Product admission, GC/currentness and native platform custody remain external.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import ClassVar, Generic, Literal, Protocol, Self, TypeVar, cast

from loushang.harness.journal import (
    SORTED_UNICODE_JSONL_FORMAT,
    JournalDurabilityProfile,
    JournalLoadPolicy,
    JournalRecordCodec,
    append_jsonl_record,
    decode_jsonl,
)
from loushang.harness.journal._rooted_io import RootedFile, bind_private_journal
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from ._opt_in import _DIGEST, _OPAQUE


def _valid_opaque(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 128
        and _OPAQUE.fullmatch(value) is not None
    )


class _NativeApprovalMethods:
    __slots__ = ()
    wheel_sha256: str
    catalog_sha256: str
    launcher_sha256: str
    profile_sha256: str

    def __post_init__(self) -> None:
        if any(
            (
                not isinstance(value, str) or _DIGEST.fullmatch(value) is None
                for value in (
                    self.wheel_sha256,
                    self.catalog_sha256,
                    self.launcher_sha256,
                    self.profile_sha256,
                )
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
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict or set(value) != {
            "catalogSha256",
            "launcherSha256",
            "profileSha256",
            "wheelSha256",
        }:
            raise ValueError("Worker native release approval record is invalid")
        return cast(Callable[..., Self], cls)(
            wheel_sha256=value["wheelSha256"],
            catalog_sha256=value["catalogSha256"],
            launcher_sha256=value["launcherSha256"],
            profile_sha256=value["profileSha256"],
        )


_ApprovalT = TypeVar("_ApprovalT", bound=_NativeApprovalMethods)


class _NativeReviewMethods(Generic[_ApprovalT]):
    __slots__ = ()
    scope_id: str
    product_policy_revision: str
    approval: _ApprovalT
    review_id: str
    review_version: int = 1
    _approval_type: ClassVar[type[_NativeApprovalMethods]]

    def __post_init__(self) -> None:
        if (
            not _valid_opaque(self.scope_id)
            or not _valid_opaque(self.product_policy_revision)
            or (not isinstance(self.approval, self._approval_type))
            or (self.review_version != 1)
            or (self.review_id != self._fingerprint())
        ):
            raise ValueError("Worker native release review is invalid")

    @classmethod
    def create(
        cls,
        *,
        scope_id: str,
        product_policy_revision: str,
        approval: _ApprovalT,
    ) -> Self:
        values = {
            "approval": approval.to_dict(),
            "productPolicyRevision": product_policy_revision,
            "reviewVersion": 1,
            "scopeId": scope_id,
        }
        return cast(Callable[..., Self], cls)(
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


class _NativeDecisionMethods(Generic[_ApprovalT]):
    __slots__ = ()
    journal_revision: int
    scope_id: str
    operation_id: str
    generation: int
    action: Literal["approve", "revoke"]
    approval: _ApprovalT | None
    record_digest: str
    record_version: int = 1
    _approval_type: ClassVar[type[_NativeApprovalMethods]]

    def __post_init__(self) -> None:
        if (
            type(self.journal_revision) is not int
            or self.journal_revision < 1
            or type(self.generation) is not int
            or (self.generation < 1)
            or (not _valid_opaque(self.scope_id))
            or (not _valid_opaque(self.operation_id))
            or (self.action not in {"approve", "revoke"})
            or (
                (self.action == "approve")
                != isinstance(self.approval, self._approval_type)
            )
            or (self.record_version != 1)
            or (not isinstance(self.record_digest, str))
            or (_DIGEST.fullmatch(self.record_digest) is None)
            or (self.record_digest != self._fingerprint())
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
        approval: _ApprovalT | None,
    ) -> Self:
        unsigned = {
            "action": action,
            "approval": None if approval is None else approval.to_dict(),
            "generation": generation,
            "journalRevision": journal_revision,
            "operationId": operation_id,
            "recordVersion": 1,
            "scopeId": scope_id,
        }
        return cast(Callable[..., Self], cls)(
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
    def from_dict(cls, value: object) -> Self:
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
        return cast(Callable[..., Self], cls)(
            journal_revision=value["journalRevision"],
            scope_id=value["scopeId"],
            operation_id=value["operationId"],
            generation=value["generation"],
            action=value["action"],
            approval=None
            if approval is None
            else cls._approval_type.from_dict(approval),
            record_digest=value["recordDigest"],
            record_version=value["recordVersion"],
        )


class _NativeDecision(Protocol):
    @property
    def operation_id(self) -> str: ...
    @property
    def action(self) -> Literal["approve", "revoke"]: ...
    @property
    def approval(self) -> object: ...
    @property
    def generation(self) -> int: ...
    @property
    def scope_id(self) -> str: ...
    @property
    def journal_revision(self) -> int: ...
    def to_dict(self) -> dict[str, object]: ...


_N = TypeVar("_N", bound=_NativeDecision)
_N_co = TypeVar("_N_co", bound=_NativeDecision, covariant=True)
_A = TypeVar("_A")
_A_contra = TypeVar("_A_contra", contravariant=True)


class _NativeFactory(Protocol[_A_contra, _N_co]):
    def __call__(
        self,
        *,
        journal_revision: int,
        scope_id: str,
        operation_id: str,
        generation: int,
        action: Literal["approve", "revoke"],
        approval: _A_contra | None,
    ) -> _N_co: ...


def _next_native_approval_decision(
    events: tuple[_N, ...],
    *,
    operation_id: str,
    expected_generation: int,
    action: Literal["approve", "revoke"],
    approval: _A | None,
    scope_id: str,
    max_events: Callable[[], int],
    create_decision: _NativeFactory[_A, _N],
    failure: Callable[[str], RuntimeError],
) -> tuple[_N, bool]:
    replay = next((item for item in events if item.operation_id == operation_id), None)
    if replay is not None:
        if (
            replay.action != action
            or replay.approval != approval
            or replay.generation != expected_generation + 1
        ):
            raise failure("operation_conflict")
        return replay, True
    previous = events[-1] if events else None
    generation = 0 if previous is None else previous.generation
    if generation != expected_generation:
        raise failure("stale")
    if action == "revoke" and (previous is None or previous.action != "approve"):
        raise failure("absent")
    if len(events) >= max_events():
        raise failure("capacity")
    decision = create_decision(
        journal_revision=len(events) + 1,
        scope_id=scope_id,
        operation_id=operation_id,
        generation=generation + 1,
        action=action,
        approval=approval,
    )
    return decision, False


def decode_native_approval_history(
    raw: bytes,
    *,
    path: Path,
    scope_id: str,
    codec: Callable[[], JournalRecordCodec[_N]],
    max_events: Callable[[], int],
    failure: Callable[[str], RuntimeError],
) -> tuple[_N, ...]:
    """Replay one exact Product scope's native-release approval decisions."""

    if len(raw) > 4 * 1024 * 1024:
        raise failure("capacity")
    events: tuple[_N, ...] = decode_jsonl(
        raw.decode("utf-8"),
        target=path,
        record_codec=codec(),
        load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
    ).records
    if len(events) > max_events():
        raise failure("capacity")
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
            raise failure("corrupt")
        seen_operations.add(event.operation_id)
    return events


class RootedNativeApprovalRecords(Generic[_A, _N]):
    """Original Rooted IO, with Product admission/GC scopes retained by its caller."""

    _path: Path
    _scope_id: str
    _durability: JournalDurabilityProfile
    _error_type: Callable[[], type[RuntimeError]]
    _root_label: str
    _failure: Callable[[str], RuntimeError]
    _max_events: Callable[[], int]
    _codec: Callable[[], JournalRecordCodec[_N]]
    _create_decision: _NativeFactory[_A, _N]

    @contextmanager
    def _bound_journal(self, *, read_only: bool = False) -> Iterator[RootedFile]:
        with bind_private_journal(
            self._path,
            error_type=self._error_type(),
            label=self._root_label,
            durable=not read_only,
        ) as rooted:
            if not read_only:
                rooted.acquire_lock(exclusive=True, suffix=".lock")
            yield rooted

    def _load(self, rooted: RootedFile) -> tuple[_N, ...]:
        try:
            raw = rooted.read_bytes(max_bytes=4 * 1024 * 1024)
        except FileNotFoundError:
            return ()
        return decode_native_approval_history(
            raw,
            path=self._path,
            scope_id=self._scope_id,
            codec=self._codec,
            max_events=self._max_events,
            failure=self._failure,
        )

    def _change(
        self,
        rooted: RootedFile,
        *,
        operation_id: str,
        expected_generation: int,
        action: Literal["approve", "revoke"],
        approval: _A | None,
    ) -> _N:
        events = self._load(rooted)
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
            return decision
        append_jsonl_record(
            self._path,
            decision,
            record_codec=self._codec(),
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._durability,
            bound_file=rooted,
        )
        return decision
