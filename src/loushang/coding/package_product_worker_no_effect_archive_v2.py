"""Typed Product proof for a Worker settled before native effect.

The Product cutover must bind this archive to its owner index before retiring
V1 segments. It carries the cross-stream records which the individual stream
bases otherwise discard. Construction alone never authorizes a cutover.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_no_effect_closure import (
    is_coding_worker_no_effect_closure,
)
from .package_product_worker_opt_in import CodingWorkerOptInDecisionV1
from .package_product_worker_receipt import CodingWorkerReceiptRecordV1
from .package_product_worker_start_gate_journal import (
    CodingWorkerStartGateRecordV1,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWorkerNoEffectProofV2:
    gate: CodingWorkerStartGateRecordV1
    receipt: CodingWorkerReceiptRecordV1
    activation: CodingProductWorkerRetainedAttemptV1
    historical_allow: CodingWorkerOptInDecisionV1
    repair_intent_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.gate) is not CodingWorkerStartGateRecordV1
            or type(self.receipt) is not CodingWorkerReceiptRecordV1
            or type(self.activation) is not CodingProductWorkerRetainedAttemptV1
            or type(self.activation.last_seen_revision) is not int
            or self.activation.last_seen_revision < 1
            or type(self.activation.owner_generation) is not int
            or self.activation.owner_generation < 0
            or type(self.activation.cleanup_contract_version) is not int
            or type(self.activation.host_identity) is not str
            or not self.activation.host_identity
            or type(self.activation.boot_identity) is not str
            or not self.activation.boot_identity
            or type(self.activation.current) is not bool
            or type(self.activation.no_effect) is not bool
            or type(self.historical_allow) is not CodingWorkerOptInDecisionV1
            or type(self.repair_intent_digest) is not str
            or _DIGEST.fullmatch(self.repair_intent_digest) is None
            or not is_coding_worker_no_effect_closure(
                gate=self.gate,
                receipt=self.receipt,
                activation=self.activation,
                supervisor=None,
            )
            or self.historical_allow.action != "allow"
            or self.historical_allow.decision_digest
            != self.receipt.opt_in_decision_digest
            or self.historical_allow.plugin_id != self.receipt.receipt.policy.plugin_id
            or self.historical_allow.scope_id != self.receipt.scope_id
            or self.historical_allow.generation
            != self.receipt.receipt.policy.owner_selection_generation
            or self.historical_allow.kill_switch_generation
            != self.receipt.receipt.policy.kill_switch_generation
        ):
            raise ValueError("Coding Worker no-effect V2 proof is invalid")

    @property
    def attempt_id(self) -> str:
        return self.gate.attempt_id

    def to_dict(self) -> dict[str, object]:
        attempt = self.activation
        return {
            "activation": {
                "attemptId": attempt.attempt_id,
                "bootIdentity": attempt.boot_identity,
                "cleanupContractVersion": attempt.cleanup_contract_version,
                "current": attempt.current,
                "hostIdentity": attempt.host_identity,
                "lastSeenRevision": attempt.last_seen_revision,
                "noEffect": attempt.no_effect,
                "ownerGeneration": attempt.owner_generation,
                "phase": attempt.phase,
                "policyFingerprint": attempt.policy_fingerprint,
                "receiptFingerprint": attempt.receipt_fingerprint,
            },
            "gate": self.gate.to_dict(),
            "historicalAllow": self.historical_allow.to_dict(),
            "receipt": self.receipt.to_dict(),
            "repairIntentDigest": self.repair_intent_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingWorkerNoEffectProofV2:
        if type(value) is not dict or set(value) != {
            "activation",
            "gate",
            "historicalAllow",
            "receipt",
            "repairIntentDigest",
        }:
            raise ValueError("Coding Worker no-effect V2 proof fields changed")
        attempt = value["activation"]
        if type(attempt) is not dict or set(attempt) != {
            "attemptId",
            "bootIdentity",
            "cleanupContractVersion",
            "current",
            "hostIdentity",
            "lastSeenRevision",
            "noEffect",
            "ownerGeneration",
            "phase",
            "policyFingerprint",
            "receiptFingerprint",
        }:
            raise ValueError("Coding Worker no-effect V2 C5 fields changed")
        return cls(
            gate=CodingWorkerStartGateRecordV1.from_dict(value["gate"]),
            receipt=CodingWorkerReceiptRecordV1.from_dict(value["receipt"]),
            activation=CodingProductWorkerRetainedAttemptV1(
                attempt_id=attempt["attemptId"],
                receipt_fingerprint=attempt["receiptFingerprint"],
                policy_fingerprint=attempt["policyFingerprint"],
                owner_generation=attempt["ownerGeneration"],
                cleanup_contract_version=attempt["cleanupContractVersion"],
                host_identity=attempt["hostIdentity"],
                boot_identity=attempt["bootIdentity"],
                phase=attempt["phase"],
                last_seen_revision=attempt["lastSeenRevision"],
                current=attempt["current"],
                no_effect=attempt["noEffect"],
            ),
            historical_allow=CodingWorkerOptInDecisionV1.from_dict(
                value["historicalAllow"]
            ),
            repair_intent_digest=value["repairIntentDigest"],
        )


@dataclass(frozen=True, slots=True)
class CodingWorkerNoEffectArchiveV2:
    scope_id: str
    store_id: str
    checkpoint_digest: str
    proofs: tuple[CodingWorkerNoEffectProofV2, ...]
    version: int = 2

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.checkpoint_digest) is not str
            or _DIGEST.fullmatch(self.checkpoint_digest) is None
            or type(self.proofs) is not tuple
            or any(
                type(item) is not CodingWorkerNoEffectProofV2 for item in self.proofs
            )
            or any(item.receipt.scope_id != self.scope_id for item in self.proofs)
            or tuple(item.attempt_id for item in self.proofs)
            != tuple(sorted({item.attempt_id for item in self.proofs}))
            or type(self.version) is not int
            or self.version != 2
        ):
            raise ValueError("Coding Worker no-effect V2 archive is invalid")

    def to_bytes(self) -> bytes:
        raw = canonical_json_bytes(
            {
                "checkpointDigest": self.checkpoint_digest,
                "proofs": [item.to_dict() for item in self.proofs],
                "scopeId": self.scope_id,
                "storeId": self.store_id,
                "version": self.version,
            }
        )
        if len(raw) > _MAX_BYTES:
            raise ValueError("Coding Worker no-effect V2 archive exceeds capacity")
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWorkerNoEffectArchiveV2:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BYTES:
            raise ValueError("Coding Worker no-effect V2 archive bytes are invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "checkpointDigest",
                    "proofs",
                    "scopeId",
                    "storeId",
                    "version",
                }
                or type(value["proofs"]) is not list
            ):
                raise ValueError("Coding Worker no-effect V2 archive fields changed")
            archive = cls(
                scope_id=value["scopeId"],
                store_id=value["storeId"],
                checkpoint_digest=value["checkpointDigest"],
                proofs=tuple(
                    CodingWorkerNoEffectProofV2.from_dict(item)
                    for item in value["proofs"]
                ),
                version=value["version"],
            )
            if archive.to_bytes() != raw:
                raise ValueError("Coding Worker no-effect V2 archive encoding changed")
            return archive
        except (KeyError, RecursionError, TypeError, ValueError, UnicodeError) as exc:
            raise ValueError(
                "Coding Worker no-effect V2 archive bytes are invalid"
            ) from exc


def read_bound_coding_worker_no_effect_archive_v2(
    rooted: RootedFile,
) -> CodingWorkerNoEffectArchiveV2 | None:
    """Read only the archive selected by the committed Product owner index."""

    from .package_product_worker_history_cutover_v2 import (
        CodingWorkerProductCutoverIndexV2,
    )
    from .package_product_worker_history_stage_v2 import (
        read_coding_worker_v2_preparation,
    )
    from .package_product_worker_history_v2_names import PRODUCT_OWNER_INDEX_NAME

    owner = CodingWorkerProductCutoverIndexV2.from_bytes(
        rooted.sibling(PRODUCT_OWNER_INDEX_NAME).read_bytes(max_bytes=4096)
    )
    prepared = read_coding_worker_v2_preparation(rooted)
    if prepared is None or prepared.index != owner:
        raise ValueError("Coding Worker no-effect V2 archive owner differs")
    return prepared.no_effect_archive


__all__ = [
    "CodingWorkerNoEffectArchiveV2",
    "CodingWorkerNoEffectProofV2",
    "read_bound_coding_worker_no_effect_archive_v2",
]
