"""Read-only cross-ledger review before a Windows Worker history checkpoint.

The Product source reader has already proved runtime quiescence, GC guard, and
settlement. This review binds each independently typed base to that same read.
It is not a cutover owner, a writer switch, or deletion authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_windows_c5_base import (
    CodingWindowsWorkerC5SemanticBaseV1,
)
from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
)
from .package_product_worker_windows_launch_intent_base import (
    CodingWindowsWorkerLaunchIntentSemanticBaseV1,
)
from .package_product_worker_windows_opt_in_base import (
    CodingWindowsWorkerOptInSemanticBaseV1,
)
from .package_product_worker_windows_provisioning_base import (
    CodingWindowsWorkerNativeProvisioningSemanticBaseV1,
)
from .package_product_worker_windows_receipt_base import (
    CodingWindowsWorkerReceiptSemanticBaseV1,
)
from .package_product_worker_windows_supervisor_base import (
    CodingWindowsWorkerSupervisorSemanticBaseV1,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistorySemanticJoinV1:
    """One source-bound, no-effect agreement of the six retained ledgers."""

    scope_id: str
    store_id: str
    source_snapshot_digest: str
    opt_in: CodingWindowsWorkerOptInSemanticBaseV1
    receipt: CodingWindowsWorkerReceiptSemanticBaseV1
    supervisor: CodingWindowsWorkerSupervisorSemanticBaseV1
    c5: CodingWindowsWorkerC5SemanticBaseV1
    launch_intent: CodingWindowsWorkerLaunchIntentSemanticBaseV1
    native_provisioning: CodingWindowsWorkerNativeProvisioningSemanticBaseV1
    observed_attempt_ids: tuple[str, ...]
    effect_attempt_ids: tuple[str, ...]
    launched_attempt_ids: tuple[str, ...]
    review_digest: str

    def __post_init__(self) -> None:
        bases = (
            (self.opt_in, CodingWindowsWorkerOptInSemanticBaseV1),
            (self.receipt, CodingWindowsWorkerReceiptSemanticBaseV1),
            (self.supervisor, CodingWindowsWorkerSupervisorSemanticBaseV1),
            (self.c5, CodingWindowsWorkerC5SemanticBaseV1),
            (self.launch_intent, CodingWindowsWorkerLaunchIntentSemanticBaseV1),
            (
                self.native_provisioning,
                CodingWindowsWorkerNativeProvisioningSemanticBaseV1,
            ),
        )
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.source_snapshot_digest) is not str
            or _DIGEST.fullmatch(self.source_snapshot_digest) is None
            or any(
                type(base) is not expected
                or base.scope_id != self.scope_id
                or base.store_id != self.store_id
                or base.source_snapshot_digest != self.source_snapshot_digest
                for base, expected in bases
            )
            or type(self.observed_attempt_ids) is not tuple
            or any(
                type(item) is not str or _ATTEMPT.fullmatch(item) is None
                for item in self.observed_attempt_ids
            )
            or self.observed_attempt_ids
            != tuple(sorted(set(self.observed_attempt_ids)))
            or type(self.effect_attempt_ids) is not tuple
            or any(
                type(item) is not str or _ATTEMPT.fullmatch(item) is None
                for item in self.effect_attempt_ids
            )
            or self.effect_attempt_ids != tuple(sorted(set(self.effect_attempt_ids)))
            or type(self.launched_attempt_ids) is not tuple
            or any(
                type(item) is not str or _ATTEMPT.fullmatch(item) is None
                for item in self.launched_attempt_ids
            )
            or self.launched_attempt_ids
            != tuple(sorted(set(self.launched_attempt_ids)))
            or not set(self.effect_attempt_ids).issubset(self.observed_attempt_ids)
            or not set(self.launched_attempt_ids).issubset(self.effect_attempt_ids)
            or self.launched_attempt_ids != self.supervisor.retired_attempt_ids
            or not set(self.launched_attempt_ids).issubset(
                self.launch_intent.intent_attempt_ids
            )
            or self.effect_attempt_ids != self.native_provisioning.attempt_ids
            or not set(self.effect_attempt_ids).issubset(self.c5.known_attempt_ids)
            or type(self.review_digest) is not str
            or self.review_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker history semantic join is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "c5": self.c5.record_digest,
            "effectAttemptIds": list(self.effect_attempt_ids),
            "launchIntent": self.launch_intent.record_digest,
            "launchedAttemptIds": list(self.launched_attempt_ids),
            "nativeProvisioning": self.native_provisioning.record_digest,
            "observedAttemptIds": list(self.observed_attempt_ids),
            "optIn": self.opt_in.record_digest,
            "receipt": self.receipt.record_digest,
            "scopeId": self.scope_id,
            "sourceSnapshotDigest": self.source_snapshot_digest,
            "storeId": self.store_id,
            "supervisor": self.supervisor.record_digest,
            "version": 1,
        }

    @classmethod
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerHistorySemanticJoinV1:
        if type(prepared) is not CodingWindowsWorkerHistoryPreparationV1:
            raise ValueError("Windows Worker history join preparation is invalid")
        prepared.require_semantic_read(semantic)
        source = semantic.source_snapshot
        recovery = semantic.offline_recovery
        observed = tuple(item.attempt_id for item in recovery.attempts)
        if any(
            type(attempt_id) is not str or _ATTEMPT.fullmatch(attempt_id) is None
            for attempt_id in observed
        ) or len(set(observed)) != len(observed):
            raise ValueError("Windows Worker history attempt inventory is invalid")
        opt_in = CodingWindowsWorkerOptInSemanticBaseV1.from_semantic_read(
            prepared, semantic
        )
        receipt = CodingWindowsWorkerReceiptSemanticBaseV1.from_semantic_read(
            prepared, semantic
        )
        supervisor = CodingWindowsWorkerSupervisorSemanticBaseV1.from_semantic_read(
            prepared, semantic
        )
        c5 = CodingWindowsWorkerC5SemanticBaseV1.from_semantic_read(prepared, semantic)
        launch = CodingWindowsWorkerLaunchIntentSemanticBaseV1.from_semantic_read(
            prepared, semantic
        )
        native = CodingWindowsWorkerNativeProvisioningSemanticBaseV1.from_semantic_read(
            prepared, semantic
        )
        effects = tuple(
            sorted(
                item.attempt_id
                for item in recovery.attempts
                if item.launch_request_fingerprint is not None
                or item.native_phase is not None
                or item.supervisor_phase is not None
            )
        )
        # A durable launch intent can retire before Supervisor starts. Only a
        # retained Supervisor attempt proves that the Worker was launched.
        launched = supervisor.retired_attempt_ids
        receipts = {item.receipt.fingerprint: item for item in recovery.receipt_records}
        if len(receipts) != len(recovery.receipt_records):
            raise ValueError("Windows Worker history receipt inventory is invalid")
        intents = {item.attempt_id: item for item in launch.retained_intents}
        native_attempts = {item.attempt_id: item for item in native.retained_attempts}
        c5_attempts = {
            item.attempt_id: item for item in recovery.retained_activation_attempts
        }
        supervisor_attempts = {
            item.attempt_id: item for item in supervisor.latest_attempts
        }
        native_job_absence = dict(recovery.native_job_absence)
        if len(c5_attempts) != len(recovery.retained_activation_attempts) or len(
            native_job_absence
        ) != len(recovery.native_job_absence):
            raise ValueError("Windows Worker history attempt inventory is invalid")
        for item in recovery.attempts:
            if item.attempt_id not in effects:
                continue
            intent = intents.get(item.attempt_id)
            provisioned = native_attempts.get(item.attempt_id)
            c5_attempt = c5_attempts.get(item.attempt_id)
            supervised = supervisor_attempts.get(item.attempt_id)
            if provisioned is None:
                raise ValueError("Windows Worker history attempt join is incomplete")
            native_receipt = provisioned.identity["receiptFingerprint"]
            if type(native_receipt) is not str:
                raise ValueError("Windows Worker history attempt join is incomplete")
            receipt_record = receipts.get(native_receipt)
            if (
                c5_attempt is None
                or receipt_record is None
                or c5_attempt.receipt_fingerprint != native_receipt
                or c5_attempt.policy_fingerprint
                != receipt_record.receipt.policy.fingerprint
                or c5_attempt.owner_generation
                != receipt_record.receipt.policy.owner_selection_generation
                or native_job_absence.get(item.attempt_id) is not True
                or item.native_phase != "settled"
            ):
                raise ValueError("Windows Worker history attempt join is incomplete")
            if intent is None:
                if (
                    supervised is not None
                    or item.launch_request_fingerprint is not None
                ):
                    raise ValueError(
                        "Windows Worker history unlaunched join is incomplete"
                    )
            else:
                if (
                    native_receipt != intent.receipt_fingerprint
                    or provisioned.identity["workerRequestFingerprint"]
                    != intent.request_fingerprint
                ):
                    raise ValueError("Windows Worker history launch join is incomplete")
                if supervised is None:
                    if (
                        item.supervisor_phase is not None
                        or item.supervisor_process_settled is not None
                        or item.supervisor_identity_fingerprint is not None
                    ):
                        raise ValueError(
                            "Windows Worker history unlaunched join is incomplete"
                        )
                elif (
                    supervised.identity_fingerprint != intent.identity_fingerprint
                    or item.supervisor_phase not in ("stopped", "process_settled")
                    or item.supervisor_process_settled is not True
                ):
                    raise ValueError(
                        "Windows Worker history launched join is incomplete"
                    )
        unsigned = {
            "c5": c5.record_digest,
            "effectAttemptIds": list(effects),
            "launchIntent": launch.record_digest,
            "launchedAttemptIds": list(launched),
            "nativeProvisioning": native.record_digest,
            "observedAttemptIds": list(sorted(observed)),
            "optIn": opt_in.record_digest,
            "receipt": receipt.record_digest,
            "scopeId": source.scope_id,
            "sourceSnapshotDigest": source.snapshot_digest,
            "storeId": source.store_id,
            "supervisor": supervisor.record_digest,
            "version": 1,
        }
        return cls(
            scope_id=source.scope_id,
            store_id=source.store_id,
            source_snapshot_digest=source.snapshot_digest,
            opt_in=opt_in,
            receipt=receipt,
            supervisor=supervisor,
            c5=c5,
            launch_intent=launch,
            native_provisioning=native,
            observed_attempt_ids=tuple(sorted(observed)),
            effect_attempt_ids=effects,
            launched_attempt_ids=launched,
            review_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )


__all__ = ["CodingWindowsWorkerHistorySemanticJoinV1"]
