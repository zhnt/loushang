"""Durable, offline payload repair for a Worker registered before effect start.

This is a separate authority from complete-stage repair: there can be no
settled Supervisor fingerprint when the start gate remains an intent.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.history._retention import (
    registered_repair_matches_no_effect_closure,
)
from loushang.harness.worker.journal import WorkerAttemptRecordV1
from loushang.harness.worker.payload._repair import RepairJournal

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_activation_state_journal import (
    CodingProductWorkerActivationStateJournal,
)
from .package_product_worker_cleanup_evidence import (
    CodingPosixWorkerCleanupEvidenceAuthority,
)
from .package_product_worker_history_retention import _known_worker_state_name
from .package_product_worker_payload import (
    _DIR_FLAGS,
    CodingWorkerPayloadDebtPlanV1,
    CodingWorkerPayloadMaterializationError,
    _plan_fields,
    _remove_partial_stage,
    _remove_verified_stage,
    _require_private_visible_root,
    _stage_exists,
    _verify_complete_repair_remainder,
    _verify_debt,
    open_coding_product_worker_supervisor_journal,
)
from .package_product_worker_receipt import (
    CodingWorkerReceiptRecordV1,
    read_coding_product_worker_receipt_record,
)
from .package_product_worker_registered_recovery import (
    CodingWorkerRegisteredOrphanReviewV1,
)
from .package_product_worker_start_gate_journal import (
    CodingWorkerStartGateJournal,
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
class CodingWorkerRegisteredPayloadRepairIntentV1:
    plan: CodingWorkerPayloadDebtPlanV1
    gate_record_digest: str
    receipt_record_digest: str
    policy_fingerprint: str
    lease_id: str
    host_identity: str
    boot_identity: str
    owner_generation: int

    def __post_init__(self) -> None:
        if (
            type(self.plan) is not CodingWorkerPayloadDebtPlanV1
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (
                    self.gate_record_digest,
                    self.receipt_record_digest,
                    self.policy_fingerprint,
                    self.lease_id,
                )
            )
            or type(self.host_identity) is not str
            or not self.host_identity
            or type(self.boot_identity) is not str
            or not self.boot_identity
            or type(self.owner_generation) is not int
            or self.owner_generation < 0
        ):
            raise ValueError("Registered Worker payload repair intent is invalid")

    @property
    def attempt_id(self) -> str:
        return self.plan.attempt_id

    def to_dict(self) -> dict[str, object]:
        return {
            "bootIdentity": self.boot_identity,
            "gateRecordDigest": self.gate_record_digest,
            "hostIdentity": self.host_identity,
            "leaseId": self.lease_id,
            "ownerGeneration": self.owner_generation,
            "plan": _plan_fields(self.plan),
            "policyFingerprint": self.policy_fingerprint,
            "receiptRecordDigest": self.receipt_record_digest,
            "version": 1,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingWorkerRegisteredPayloadRepairIntentV1:
        if (
            type(value) is not dict
            or set(value)
            != {
                "bootIdentity",
                "gateRecordDigest",
                "hostIdentity",
                "leaseId",
                "ownerGeneration",
                "plan",
                "policyFingerprint",
                "receiptRecordDigest",
                "version",
            }
            or value["version"] != 1
        ):
            raise ValueError("Registered Worker payload repair fields are invalid")
        raw_plan = value["plan"]
        if (
            type(raw_plan) is not dict
            or set(raw_plan)
            != {
                "attemptId",
                "entrypoint",
                "payloadDigest",
                "payloadSize",
                "receiptFingerprint",
                "stageDevice",
                "stageInode",
                "version",
            }
            or raw_plan["version"] != 1
        ):
            raise ValueError("Registered Worker payload repair plan is invalid")
        return cls(
            plan=CodingWorkerPayloadDebtPlanV1(
                attempt_id=raw_plan["attemptId"],
                entrypoint=raw_plan["entrypoint"],
                payload_digest=raw_plan["payloadDigest"],
                payload_size=raw_plan["payloadSize"],
                receipt_fingerprint=raw_plan["receiptFingerprint"],
                stage_device=raw_plan["stageDevice"],
                stage_inode=raw_plan["stageInode"],
            ),
            gate_record_digest=value["gateRecordDigest"],
            receipt_record_digest=value["receiptRecordDigest"],
            policy_fingerprint=value["policyFingerprint"],
            lease_id=value["leaseId"],
            host_identity=value["hostIdentity"],
            boot_identity=value["bootIdentity"],
            owner_generation=value["ownerGeneration"],
        )


def _names(attempt_id: str) -> tuple[str, str]:
    if type(attempt_id) is not str or _ATTEMPT.fullmatch(attempt_id) is None:
        raise ValueError("Registered Worker attempt identity is invalid")
    name = f"{_PREFIX}{attempt_id}.json"
    return name, f".{name}.stage"


def _read_intent(
    root_fd: int, attempt_id: str
) -> CodingWorkerRegisteredPayloadRepairIntentV1 | None:
    return _repair_journal().read(root_fd, attempt_id)


def _publish_intent(
    root_fd: int, intent: CodingWorkerRegisteredPayloadRepairIntentV1
) -> None:
    return _repair_journal().publish(root_fd, intent.attempt_id, intent)


def _settle_intent_stage(
    root_fd: int, intent: CodingWorkerRegisteredPayloadRepairIntentV1
) -> None:
    return _repair_journal().settle(root_fd, intent.attempt_id, intent)


def _expected_intent(
    review: CodingWorkerRegisteredOrphanReviewV1,
) -> CodingWorkerRegisteredPayloadRepairIntentV1:
    if (
        not review.payload_repair_candidate
        or review.payload_plan is None
        or review.gate_record is None
        or review.receipt_record is None
        or review.activation_attempt is None
        or review.repaired_orphan_lease is None
    ):
        raise CodingWorkerRegisteredPayloadRepairError(
            "coding_worker_registered_payload_repair_unproven"
        )
    c5 = review.activation_attempt
    return CodingWorkerRegisteredPayloadRepairIntentV1(
        plan=review.payload_plan,
        gate_record_digest=review.gate_record.record_digest,
        receipt_record_digest=review.receipt_record.record_digest,
        policy_fingerprint=c5.policy_fingerprint,
        lease_id=review.repaired_orphan_lease.lease_id,
        host_identity=c5.host_identity,
        boot_identity=c5.boot_identity,
        owner_generation=c5.owner_generation,
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

    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        with product.pinned_state_root_gc_read() as root_fd:
            _require_private_visible_root(product.state_root, root_fd)
            return _read_intent(root_fd, attempt_id)


def _require_same_registered_evidence(
    product: PosixLocalWheelProductSessionOwner,
    review: CodingWorkerRegisteredOrphanReviewV1,
) -> None:
    gate = CodingWorkerStartGateJournal(product).current(review.attempt_id)
    supervisor = open_coding_product_worker_supervisor_journal(product).status(
        review.attempt_id
    )
    journal = CodingProductWorkerActivationStateJournal(
        product.state_root / "worker-activation-state.jsonl",
        scope_id=product.policy.project_scope_id,
        store_id=product.epoch_runtime.registry.store_id,
    )
    matching = tuple(
        item
        for item in journal.retained_attempts_read_only()
        if item.attempt_id == review.attempt_id
    )
    receipt = (
        None
        if gate is None
        else read_coding_product_worker_receipt_record(
            product, receipt_fingerprint=gate.receipt_fingerprint
        )
    )
    evidence = CodingPosixWorkerCleanupEvidenceAuthority(product)
    if (
        gate != review.gate_record
        or supervisor is not None
        or len(matching) != 1
        or matching[0] != review.activation_attempt
        or receipt != review.receipt_record
        or evidence.host_identity != review.host_identity
        or evidence.boot_identity != review.current_boot_identity
    ):
        raise CodingWorkerRegisteredPayloadRepairError(
            "coding_worker_registered_payload_repair_stale"
        )


def repair_coding_product_worker_registered_payload_debt(
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWorkerRegisteredOrphanReviewV1,
) -> CodingWorkerRegisteredPayloadRepairIntentV1:
    """Publish exact intent, then remove only the verified original stage."""

    if type(expected_review) is not CodingWorkerRegisteredOrphanReviewV1:
        raise TypeError("Registered Worker payload review must be exact")
    intent = _expected_intent(expected_review)
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(store_id=registry.store_id) as quiet:
        if (
            quiet.active_runtime_lease_ids
            or quiet.owner_revision != expected_review.repaired_owner_revision
        ):
            raise CodingWorkerRegisteredPayloadRepairError(
                "coding_worker_registered_payload_runtime_changed"
            )
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard(require_write=True):
            _require_same_registered_evidence(product, expected_review)
            with product.pinned_state_root_gc_read() as root_fd:
                _require_private_visible_root(product.state_root, root_fd)
                if any(
                    name.casefold().startswith(("worker-", ".worker-"))
                    and not _known_worker_state_name(name)
                    for name in os.listdir(root_fd)
                ):
                    raise CodingWorkerRegisteredPayloadRepairError(
                        "coding_worker_registered_payload_inventory_changed"
                    )
                prior = _read_intent(root_fd, intent.attempt_id)
                if prior is not None and prior != intent:
                    raise CodingWorkerRegisteredPayloadRepairError(
                        "coding_worker_registered_payload_repair_stale"
                    )
                if not _stage_exists(root_fd, intent.attempt_id):
                    if prior is None:
                        raise CodingWorkerRegisteredPayloadRepairError(
                            "coding_worker_registered_payload_stage_absent"
                        )
                    _settle_intent_stage(root_fd, intent)
                    return intent
                if (
                    prior is None
                    and _verify_debt(root_fd, intent.attempt_id) != intent.plan
                ):
                    raise CodingWorkerRegisteredPayloadRepairError(
                        "coding_worker_registered_payload_plan_stale"
                    )
                stage_name = f"worker-payload-{intent.attempt_id}"
                stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
                try:
                    _verify_complete_repair_remainder(
                        root_fd, stage_fd, stage_name, intent.plan
                    )
                    _publish_intent(root_fd, intent)
                    _require_same_registered_evidence(product, expected_review)
                    _verify_complete_repair_remainder(
                        root_fd, stage_fd, stage_name, intent.plan
                    )
                    if prior is None:
                        _remove_verified_stage(
                            root_fd, stage_fd, stage_name, intent.plan
                        )
                    else:
                        _remove_partial_stage(
                            root_fd, stage_fd, stage_name, intent.plan.entrypoint
                        )
                finally:
                    os.close(stage_fd)
        product.assert_root_gc_authority_current()
    return intent


__all__ = [
    "CodingWorkerRegisteredPayloadRepairError",
    "CodingWorkerRegisteredPayloadRepairIntentV1",
    "read_coding_product_worker_registered_payload_repair_intent",
    "registered_payload_repair_matches_no_effect_closure",
    "repair_coding_product_worker_registered_payload_debt",
]


def _decode_repair_record(
    body: bytes, attempt_id: str
) -> CodingWorkerRegisteredPayloadRepairIntentV1:
    intent = CodingWorkerRegisteredPayloadRepairIntentV1.from_dict(json.loads(body))
    if (
        intent.attempt_id != attempt_id
        or body != canonical_json_bytes(intent.to_dict()) + b"\n"
    ):
        raise ValueError("Registered Worker payload repair changed")
    return intent


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
