"""Product-owned admission-to-lease evidence for staging adoption proposals.

Write the proposal before the Package decision. A proposal without a durable
Package decision is inert; only the Package journal selects a decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import FunctionalJournalRecordCodec, JournalCodecError
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeAdmissionReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleStagingAdoptionRequestV1,
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_binding_journal import (
    _ProductDecisionBindingJournal,
)

PACKAGE_PRODUCT_STAGING_ADOPTION_BINDING_VERSION = 1


class PackageProductStagingAdoptionBindingError(RuntimeError):
    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PackageProductStagingAdoptionBindingV1:
    record_revision: int
    decision: PackageLifecycleStagingAdoptionRequestV1
    admission: PackageEpochRuntimeAdmissionReceiptV1
    record_version: int = PACKAGE_PRODUCT_STAGING_ADOPTION_BINDING_VERSION
    binding_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.record_revision) is not int or self.record_revision < 1:
            raise ValueError("Product staging adoption binding revision is invalid")
        if not isinstance(self.decision, PackageLifecycleStagingAdoptionRequestV1):
            raise TypeError("Package staging adoption decision is required")
        if not isinstance(self.admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Product staging adoption receipt is required")
        if (
            self.decision.new_runtime_admission_request_id
            != self.admission.request.admission_request_id
            or self.decision.lease_snapshot_id != self.admission.lease_snapshot_id
        ):
            raise ValueError("Product staging adoption changed decision")
        if self.record_version != PACKAGE_PRODUCT_STAGING_ADOPTION_BINDING_VERSION:
            raise ValueError("Unsupported Product staging adoption binding")
        object.__setattr__(
            self,
            "binding_id",
            sha256(canonical_json_bytes(self._identity_dict())).hexdigest(),
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "admission": self.admission.to_dict(),
            "decision": self.decision.to_dict(),
            "recordVersion": self.record_version,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "bindingId": self.binding_id,
            "recordRevision": self.record_revision,
            **self._identity_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageProductStagingAdoptionBindingV1:
        if not isinstance(value, dict) or set(value) != {
            "admission",
            "bindingId",
            "decision",
            "recordRevision",
            "recordVersion",
        }:
            raise ValueError("Product staging adoption binding schema changed")
        result = cls(
            record_revision=value["recordRevision"],
            decision=PackageLifecycleStagingAdoptionRequestV1.from_dict(
                value["decision"]
            ),
            admission=PackageEpochRuntimeAdmissionReceiptV1.from_dict(
                value["admission"]
            ),
            record_version=value["recordVersion"],
        )
        if value["bindingId"] != result.binding_id:
            raise ValueError("Product staging adoption binding identity changed")
        return result


def _encode(record: PackageProductStagingAdoptionBindingV1) -> dict[str, object]:
    if not isinstance(record, PackageProductStagingAdoptionBindingV1):
        raise TypeError("Product staging adoption binding is required")
    return record.to_dict()


def _decode(value: object) -> PackageProductStagingAdoptionBindingV1:
    try:
        return PackageProductStagingAdoptionBindingV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Product staging adoption binding is invalid",
            code="invalid_package_product_staging_adoption_binding",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(encoder=_encode, decoder=_decode)


class PackageProductStagingAdoptionBindingJournal(
    _ProductDecisionBindingJournal[
        PackageProductStagingAdoptionBindingV1, PackageLifecycleStagingAdoptionRequestV1
    ]
):
    """Append-once Product evidence for each proposed staging adoption decision."""

    _codec = _CODEC
    _label = "Product staging adoption"
    _query_label = "Product staging adoption"
    _corrupt_code = "package_product_staging_adoption_binding_corrupt"
    _invalid_code = "package_product_staging_adoption_binding_invalid"
    _conflict_code = "package_product_staging_adoption_binding_conflict"
    _decision_type = PackageLifecycleStagingAdoptionRequestV1
    _record_type = PackageProductStagingAdoptionBindingV1
    _match_full_receipt = True

    def bind(
        self,
        decision: PackageLifecycleStagingAdoptionRequestV1,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageProductStagingAdoptionBindingV1:
        return self._bind_decision(decision, admission)

    def read_decision(
        self, decision_id: str
    ) -> PackageProductStagingAdoptionBindingV1 | None:
        """Read a proposal without creating locks or repairing a damaged tail."""
        return self._read_decision(decision_id)

    def read_operation(
        self, operation_id: str
    ) -> tuple[PackageProductStagingAdoptionBindingV1, ...]:
        return self._read_operation(operation_id)

    def _error(
        self, message: str, *, code: str
    ) -> PackageProductStagingAdoptionBindingError:
        return PackageProductStagingAdoptionBindingError(
            message, code=code, path=self._path
        )
