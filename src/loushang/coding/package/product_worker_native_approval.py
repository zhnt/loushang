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
)
from loushang.harness.package_product._linux_worker_native_release import (
    _ProductRootedNativeApprovalRecords,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._native_approval import (
    NATIVE_APPROVAL_JOURNAL_NAME,
    NATIVE_APPROVAL_MAX_EVENTS,
    _NativeApprovalMethods,
    _NativeDecisionMethods,
    _NativeReviewMethods,
    decode_native_approval_history,
)

_MAX_EVENTS = NATIVE_APPROVAL_MAX_EVENTS


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


_CODEC = FunctionalJournalRecordCodec.with_decode_error(
    encoder=CodingWorkerNativeApprovalDecisionV1.to_dict,
    decoder=lambda value: CodingWorkerNativeApprovalDecisionV1.from_dict(value),
    message="Worker native approval decision record is invalid",
    code="coding_worker_native_approval_record_invalid",
)
_decode = _CODEC.decoder


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
    _ProductRootedNativeApprovalRecords[
        CodingWorkerNativeReleaseApprovalV1, CodingWorkerNativeApprovalDecisionV1
    ]
):
    """Exact Product-root approval with CAS, replay, and durable revocation."""

    _approval_type = CodingWorkerNativeReleaseApprovalV1
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
        self._path = product_owner.state_root / NATIVE_APPROVAL_JOURNAL_NAME
        self._scope_id = product_owner.policy.project_scope_id
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)


__all__ = [
    "CodingWorkerNativeApprovalDecisionV1",
    "CodingWorkerNativeApprovalError",
    "CodingWorkerNativeApprovalJournal",
    "CodingWorkerNativeReleaseApprovalV1",
    "CodingWorkerNativeReleaseReviewV1",
]
