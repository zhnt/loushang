"""Durable, offline payload repair for a Worker registered before effect start.

This is a separate authority from complete-stage repair: there can be no
settled Supervisor fingerprint when the start gate remains an intent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast

from loushang.harness.package_product._linux_worker_recovery import (
    _expected_intent as _core_expected_intent,
)
from loushang.harness.package_product._linux_worker_recovery import (
    _require_same_registered_evidence as _core_require_same_registered_evidence,
)
from loushang.harness.package_product._linux_worker_recovery import (
    read_registered_intent,
    repair_registered_payload,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._retention import (
    registered_repair_matches_no_effect_closure,
)
from loushang.harness.worker.journal import WorkerAttemptRecordV1
from loushang.harness.worker.payload._records import (
    RegisteredPayloadRepairIntentMethods,
)
from loushang.harness.worker.payload._repair import RepairJournal

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_payload import (
    CodingWorkerPayloadDebtPlanV1,
    CodingWorkerPayloadMaterializationError,
)
from .package_product_worker_receipt import (
    CodingWorkerReceiptRecordV1,
)
from .package_product_worker_registered_recovery import (
    CodingWorkerRegisteredOrphanReviewV1,
    _recovery_bindings,
)
from .package_product_worker_start_gate_journal import (
    CodingWorkerStartGateRecordV1,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_PREFIX = "worker-registered-repair-"
_MAX_BYTES = 4096


class CodingWorkerRegisteredPayloadRepairError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerRegisteredPayloadRepairIntentV1(RegisteredPayloadRepairIntentMethods):
    _plan_type = CodingWorkerPayloadDebtPlanV1
    plan: CodingWorkerPayloadDebtPlanV1
    gate_record_digest: str
    receipt_record_digest: str
    policy_fingerprint: str
    lease_id: str
    host_identity: str
    boot_identity: str
    owner_generation: int


def _names(attempt_id: str) -> tuple[str, str]:
    if type(attempt_id) is not str or _ATTEMPT.fullmatch(attempt_id) is None:
        raise ValueError("Registered Worker attempt identity is invalid")
    name = f"{_PREFIX}{attempt_id}.json"
    return name, f".{name}.stage"


def _expected_intent(
    review: CodingWorkerRegisteredOrphanReviewV1,
) -> CodingWorkerRegisteredPayloadRepairIntentV1:
    return cast(
        CodingWorkerRegisteredPayloadRepairIntentV1,
        _core_expected_intent(_recovery_bindings(), review),
    )


def registered_payload_repair_matches_no_effect_closure(
    intent: CodingWorkerRegisteredPayloadRepairIntentV1,
    *,
    gate: CodingWorkerStartGateRecordV1 | None,
    receipt: CodingWorkerReceiptRecordV1 | None,
    activation: CodingProductWorkerRetainedAttemptV1 | None,
    supervisor: WorkerAttemptRecordV1 | None,
) -> bool:
    """Bind a retained repair record to the exact settled C5 no-effect proof."""

    return registered_repair_matches_no_effect_closure(
        intent,
        gate=gate,
        receipt=receipt,
        activation=activation,
        supervisor=supervisor,
        product_id="coding",
    )


def read_coding_product_worker_registered_payload_repair_intent(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerRegisteredPayloadRepairIntentV1 | None:
    """Read the durable record, including during a partial stage deletion."""
    return cast(
        CodingWorkerRegisteredPayloadRepairIntentV1 | None,
        read_registered_intent(_recovery_bindings(), product, attempt_id=attempt_id),
    )


def _require_same_registered_evidence(
    product: PosixLocalWheelProductSessionOwner,
    review: CodingWorkerRegisteredOrphanReviewV1,
) -> None:
    return _core_require_same_registered_evidence(_recovery_bindings(), product, review)


def repair_coding_product_worker_registered_payload_debt(
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWorkerRegisteredOrphanReviewV1,
) -> CodingWorkerRegisteredPayloadRepairIntentV1:
    """Publish exact intent, then remove only the verified original stage."""
    return cast(
        CodingWorkerRegisteredPayloadRepairIntentV1,
        repair_registered_payload(
            _recovery_bindings(), product, expected_review=expected_review
        ),
    )


__all__ = [
    "CodingWorkerRegisteredPayloadRepairError",
    "CodingWorkerRegisteredPayloadRepairIntentV1",
    "read_coding_product_worker_registered_payload_repair_intent",
    "registered_payload_repair_matches_no_effect_closure",
    "repair_coding_product_worker_registered_payload_debt",
]


_decode_repair_record = CodingWorkerRegisteredPayloadRepairIntentV1.from_repair_record


def _repair_journal() -> RepairJournal[CodingWorkerRegisteredPayloadRepairIntentV1]:
    return RepairJournal(
        names=_names,
        decode=_decode_repair_record,
        encode=CodingWorkerRegisteredPayloadRepairIntentV1.to_dict,
        maximum_bytes=_MAX_BYTES,
        error_type=CodingWorkerRegisteredPayloadRepairError,
        raw_error_type=CodingWorkerPayloadMaterializationError,
        error_code="coding_worker_registered_payload_repair_unverified",
        stale_code="coding_worker_registered_payload_repair_stale",
        publication_changed="Registered Worker payload publication changed",
        write_message="Registered Worker repair write made no progress",
        single_link_staging_error="Registered Worker payload staging is unexpected",
    )
