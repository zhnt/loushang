"""Read-only no-effect joins and value proofs, separate from native cleanup."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import ClassVar, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)

from ..journal import WorkerAttemptRecordV1
from ._activation import _RetainedAttemptFields
from ._base_codec import _BASE_ERRORS, _BaseWireMethods, _unchanged
from ._opt_in import _OptInDecisionMethods
from ._receipts import _ReceiptRecordMethods
from ._start_gate import _StartGateRecordMethods

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def is_no_effect_closure(
    *,
    product_id: str,
    gate: _StartGateRecordMethods,
    activation: _RetainedAttemptFields | None,
    supervisor: WorkerAttemptRecordV1 | None,
    receipt: _ReceiptRecordMethods | None,
) -> bool:
    """Recognize only the C5 proof minted by the no-effect transition.

    Product C5 history replay rejects a no-effect marker after effect start.
    The unreleased gate and absent Supervisor record independently prove that
    native launch did not begin. This projection never settles an attempt.
    """

    if activation is None or receipt is None:
        return False
    policy = receipt.receipt.policy
    return bool(
        activation.phase == "settled"
        and activation.no_effect
        and activation.cleanup_contract_version == 1
        and activation.attempt_id == gate.attempt_id
        and activation.receipt_fingerprint == gate.receipt_fingerprint
        and activation.policy_fingerprint == gate.policy_fingerprint
        and activation.owner_generation == policy.owner_selection_generation
        and gate.phase == "intent"
        and gate.identity is None
        and supervisor is None
        and receipt.receipt.fingerprint == gate.receipt_fingerprint
        and policy.product_id == product_id
        and policy.product_scope_id == gate.scope_id
        and policy.fingerprint == gate.policy_fingerprint
    )


class _NoEffectProofMethods:
    __slots__ = ()

    gate: _StartGateRecordMethods
    receipt: _ReceiptRecordMethods
    activation: _RetainedAttemptFields
    historical_allow: _OptInDecisionMethods
    repair_intent_digest: str

    _retained_type: ClassVar[type[_RetainedAttemptFields]]
    _decision_type: ClassVar[type[_OptInDecisionMethods]]
    _receipt_record_type: ClassVar[type[_ReceiptRecordMethods]]
    _gate_record_type: ClassVar[type[_StartGateRecordMethods]]
    _product_id: ClassVar[str]
    # This projection's auxiliary fields must not silently change archive V2.
    _retained_schema: ClassVar[RecordSchema] = RecordSchema(
        _unchanged,
        tuple(
            RecordField(name)
            for name in (
                "attempt_id",
                "receipt_fingerprint",
                "policy_fingerprint",
                "owner_generation",
                "cleanup_contract_version",
                "host_identity",
                "boot_identity",
                "phase",
                "last_seen_revision",
                "current",
                "no_effect",
            )
        ),
    )

    def __post_init__(self) -> None:
        if (
            type(self.gate) is not self._gate_record_type
            or type(self.receipt) is not self._receipt_record_type
            or type(self.activation) is not self._retained_type
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
            or type(self.historical_allow) is not self._decision_type
            or type(self.repair_intent_digest) is not str
            or _DIGEST.fullmatch(self.repair_intent_digest) is None
            or not is_no_effect_closure(
                gate=self.gate,
                receipt=self.receipt,
                activation=self.activation,
                supervisor=None,
                product_id=self._product_id,
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
            "activation": self._retained_schema.encode(attempt, sort_keys=True),
            "gate": self.gate.to_dict(),
            "historicalAllow": self.historical_allow.to_dict(),
            "receipt": self.receipt.to_dict(),
            "repairIntentDigest": self.repair_intent_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict or set(value) != {
            "activation",
            "gate",
            "historicalAllow",
            "receipt",
            "repairIntentDigest",
        }:
            raise ValueError("Coding Worker no-effect V2 proof fields changed")
        attempt = value["activation"]
        if type(attempt) is not dict or set(attempt) != cls._retained_schema.keys:
            raise ValueError("Coding Worker no-effect V2 C5 fields changed")
        return cast(Callable[..., Self], cls)(
            gate=cls._gate_record_type.from_dict(value["gate"]),
            receipt=cls._receipt_record_type.from_dict(value["receipt"]),
            activation=cls._retained_schema.decode(
                cast(Callable[..., _RetainedAttemptFields], cls._retained_type), attempt
            ),
            historical_allow=cls._decision_type.from_dict(value["historicalAllow"]),
            repair_intent_digest=value["repairIntentDigest"],
        )


class _NoEffectArchiveMethods(_BaseWireMethods):
    __slots__ = ()

    scope_id: str
    store_id: str
    checkpoint_digest: str
    proofs: tuple[_NoEffectProofMethods, ...]
    version: int = 2

    _proof_type: ClassVar[type[_NoEffectProofMethods]]

    _wire_label = "Coding Worker no-effect V2 archive"
    _wire_lists = ("proofs",)
    _wire_errors = (*_BASE_ERRORS, RecursionError)

    @classmethod
    def _make_wire_schema(cls) -> RecordSchema:
        return RecordSchema.for_dataclass(
            cls,
            _unchanged,
            RecordField(
                "proofs",
                encoder=lambda xs: [x.to_dict() for x in xs],
                decoder=lambda xs: tuple(cls._proof_type.from_dict(x) for x in xs),
            ),
        )

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
            or any(type(item) is not self._proof_type for item in self.proofs)
            or any(item.receipt.scope_id != self.scope_id for item in self.proofs)
            or tuple(item.attempt_id for item in self.proofs)
            != tuple(sorted({item.attempt_id for item in self.proofs}))
            or type(self.version) is not int
            or self.version != 2
        ):
            raise ValueError("Coding Worker no-effect V2 archive is invalid")
