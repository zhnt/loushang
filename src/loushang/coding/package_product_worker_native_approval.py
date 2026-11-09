"""Product-owned, default-dark approval of one exact Linux Worker release.

The approval journal is separate from both the Worker Wheel and its native
release Wheel. Its decisions are inert until an explicit Product install or
repair checks the current decision under the shared selection/GC gate.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    FunctionalJournalRecordCodec,
    JournalCodecError,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._native_approval import (
    RootedNativeApprovalRecords,
    _NativeApprovalMethods,
    _NativeDecisionMethods,
    _NativeReviewMethods,
    _valid_opaque,
    decode_native_approval_history,
)

_MAX_EVENTS = 256
_JOURNAL_NAME = "worker-native-release-approvals.jsonl"


class CodingWorkerNativeApprovalError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerNativeReleaseApprovalV1(_NativeApprovalMethods):
    """Exact release bytes accepted independently of the Worker package."""

    wheel_sha256: str
    catalog_sha256: str
    launcher_sha256: str
    profile_sha256: str

    @classmethod
    def from_dict(cls, value: object) -> CodingWorkerNativeReleaseApprovalV1:
        return super(CodingWorkerNativeReleaseApprovalV1, cls).from_dict(value)


@dataclass(frozen=True, slots=True)
class CodingWorkerNativeReleaseReviewV1(
    _NativeReviewMethods[CodingWorkerNativeReleaseApprovalV1]
):
    """Exact operator review of one Wheel under one Product source policy."""

    scope_id: str
    product_policy_revision: str
    approval: CodingWorkerNativeReleaseApprovalV1
    review_id: str
    review_version: int = 1

    _approval_type = CodingWorkerNativeReleaseApprovalV1

    @classmethod
    def create(
        cls,
        *,
        scope_id: str,
        product_policy_revision: str,
        approval: CodingWorkerNativeReleaseApprovalV1,
    ) -> CodingWorkerNativeReleaseReviewV1:
        return super(CodingWorkerNativeReleaseReviewV1, cls).create(
            scope_id=scope_id,
            product_policy_revision=product_policy_revision,
            approval=approval,
        )


@dataclass(frozen=True, slots=True)
class CodingWorkerNativeApprovalDecisionV1(
    _NativeDecisionMethods[CodingWorkerNativeReleaseApprovalV1]
):
    journal_revision: int
    scope_id: str
    operation_id: str
    generation: int
    action: Literal["approve", "revoke"]
    approval: CodingWorkerNativeReleaseApprovalV1 | None
    record_digest: str
    record_version: int = 1

    _approval_type = CodingWorkerNativeReleaseApprovalV1

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
        return super(CodingWorkerNativeApprovalDecisionV1, cls).create(
            journal_revision=journal_revision,
            scope_id=scope_id,
            operation_id=operation_id,
            generation=generation,
            action=action,
            approval=approval,
        )

    @classmethod
    def from_dict(cls, value: object) -> CodingWorkerNativeApprovalDecisionV1:
        return super(CodingWorkerNativeApprovalDecisionV1, cls).from_dict(value)


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
    return decode_native_approval_history(
        raw,
        path=path,
        scope_id=scope_id,
        codec=lambda: _CODEC,
        max_events=lambda: _MAX_EVENTS,
        failure=_native_approval_failure,
    )


def _native_approval_failure(code: str) -> CodingWorkerNativeApprovalError:
    return CodingWorkerNativeApprovalError("coding_worker_native_approval_" + code)


class CodingWorkerNativeApprovalJournal(
    RootedNativeApprovalRecords[
        CodingWorkerNativeReleaseApprovalV1, CodingWorkerNativeApprovalDecisionV1
    ]
):
    """Exact Product-root approval with CAS, replay, and durable revocation."""

    _error_type = staticmethod(lambda: CodingWorkerNativeApprovalError)
    _root_label = "coding_worker_native_approval_state_root"
    _failure = staticmethod(_native_approval_failure)
    _max_events = staticmethod(lambda: _MAX_EVENTS)
    _codec = staticmethod(lambda: _CODEC)
    _create_decision = staticmethod(
        lambda **values: CodingWorkerNativeApprovalDecisionV1.create(**values)
    )

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
        with (
            self._product_owner.gc_gate.guard(),
            self._bound_journal(read_only=True) as rooted,
        ):
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
        with (
            self._product_owner.gc_gate.guard(require_write=True),
            self._bound_journal() as rooted,
        ):
            self._product_owner.assert_root_gc_authority_current()
            return self._change(
                rooted,
                operation_id=operation_id,
                expected_generation=expected_generation,
                action=action,
                approval=approval,
            )


__all__ = [
    "CodingWorkerNativeApprovalDecisionV1",
    "CodingWorkerNativeApprovalError",
    "CodingWorkerNativeApprovalJournal",
    "CodingWorkerNativeReleaseApprovalV1",
    "CodingWorkerNativeReleaseReviewV1",
]
