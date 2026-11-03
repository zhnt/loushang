"""Product-owned admission-to-lease evidence for proposed A2 rebinds.

Write the proposal before the Package decision. A proposal without a durable
Package decision is inert; only the Package journal selects a pending decision.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    journal_file_read_lock,
    load_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeAdmissionReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRebindRequestV1,
    canonical_json_bytes,
)

PACKAGE_PRODUCT_REBIND_ADMISSION_BINDING_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_READ_ONLY_LOAD_POLICY = JournalLoadPolicy(partial_tail="raise", create_lock=False)


class PackageProductRebindAdmissionBindingError(RuntimeError):
    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PackageProductRebindAdmissionBindingV1:
    record_revision: int
    decision: PackageLifecycleRebindRequestV1
    admission: PackageEpochRuntimeAdmissionReceiptV1
    record_version: int = PACKAGE_PRODUCT_REBIND_ADMISSION_BINDING_VERSION
    binding_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.record_revision) is not int or self.record_revision < 1:
            raise ValueError("Product rebind binding revision is invalid")
        if not isinstance(self.decision, PackageLifecycleRebindRequestV1):
            raise TypeError("Package rebind decision is required")
        if not isinstance(self.admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Product rebind admission receipt is required")
        if (
            self.decision.new_runtime_admission_request_id
            != self.admission.request.admission_request_id
        ):
            raise ValueError("Product rebind admission changed decision")
        if self.record_version != PACKAGE_PRODUCT_REBIND_ADMISSION_BINDING_VERSION:
            raise ValueError("Unsupported Product rebind admission binding")
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
    def from_dict(cls, value: object) -> PackageProductRebindAdmissionBindingV1:
        if not isinstance(value, dict) or set(value) != {
            "admission",
            "bindingId",
            "decision",
            "recordRevision",
            "recordVersion",
        }:
            raise ValueError("Product rebind admission binding schema changed")
        result = cls(
            record_revision=value["recordRevision"],
            decision=PackageLifecycleRebindRequestV1.from_dict(value["decision"]),
            admission=PackageEpochRuntimeAdmissionReceiptV1.from_dict(
                value["admission"]
            ),
            record_version=value["recordVersion"],
        )
        if value["bindingId"] != result.binding_id:
            raise ValueError("Product rebind admission binding identity changed")
        return result


def _encode(record: PackageProductRebindAdmissionBindingV1) -> dict[str, object]:
    if not isinstance(record, PackageProductRebindAdmissionBindingV1):
        raise TypeError("Product rebind admission binding is required")
    return record.to_dict()


def _decode(value: object) -> PackageProductRebindAdmissionBindingV1:
    try:
        return PackageProductRebindAdmissionBindingV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Product rebind admission binding is invalid",
            code="invalid_package_product_rebind_admission_binding",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(encoder=_encode, decoder=_decode)


class PackageProductRebindAdmissionBindingJournal:
    """Append-once Product evidence for each proposed rebind decision."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def bind(
        self,
        decision: PackageLifecycleRebindRequestV1,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageProductRebindAdmissionBindingV1:
        if not isinstance(decision, PackageLifecycleRebindRequestV1) or not isinstance(
            admission, PackageEpochRuntimeAdmissionReceiptV1
        ):
            raise TypeError("Exact Product rebind admission evidence is required")
        if (
            decision.new_runtime_admission_request_id
            != admission.request.admission_request_id
        ):
            raise self._error(
                "Product rebind admission changed decision",
                code="package_product_rebind_admission_invalid",
            )
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            records = self._load_unlocked()
            existing = next(
                (
                    record
                    for record in records
                    if record.decision.decision_id == decision.decision_id
                ),
                None,
            )
            if existing is not None:
                if (
                    existing.decision == decision
                    and existing.admission.request == admission.request
                ):
                    return existing
                raise self._error(
                    "Product rebind admission changed for fixed decision",
                    code="package_product_rebind_admission_conflict",
                )
            record = PackageProductRebindAdmissionBindingV1(
                record_revision=len(records) + 1,
                decision=decision,
                admission=admission,
            )
            append_jsonl_record(
                self._path,
                record,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return record

    def read_decision(
        self, decision_id: str
    ) -> PackageProductRebindAdmissionBindingV1 | None:
        """Read a proposal without creating locks or repairing a damaged tail."""

        if not isinstance(decision_id, str) or _SHA256.fullmatch(decision_id) is None:
            raise ValueError("Product rebind decision id is invalid")
        records = self._read_only_records()
        return next(
            (
                record
                for record in records
                if record.decision.decision_id == decision_id
            ),
            None,
        )

    def read_operation(
        self, operation_id: str
    ) -> tuple[PackageProductRebindAdmissionBindingV1, ...]:
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Product rebind operation id is invalid")
        return tuple(
            record
            for record in self._read_only_records()
            if record.decision.operation_id == operation_id
        )

    def _read_only_records(
        self,
    ) -> tuple[PackageProductRebindAdmissionBindingV1, ...]:
        with journal_file_read_lock(
            self._path,
            "shared",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            create_lock=False,
        ):
            return self._load_unlocked(load_policy=_READ_ONLY_LOAD_POLICY)

    def _load_unlocked(
        self, *, load_policy: JournalLoadPolicy | None = None
    ) -> tuple[PackageProductRebindAdmissionBindingV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, PackageProductRebindAdmissionBindingV1] = (
                load_jsonl(
                    self._path,
                    record_codec=_CODEC,
                    format_profile=SORTED_UNICODE_JSONL_FORMAT,
                    durability=self._unlocked_durability,
                    load_policy=load_policy or self._load_policy,
                )
            )
            records = snapshot.records
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if line:
                    json.loads(line, object_pairs_hook=_unique_json_object)
            if any(
                record.record_revision != revision
                for revision, record in enumerate(records, start=1)
            ) or len({record.decision.decision_id for record in records}) != len(
                records
            ):
                raise ValueError("Product rebind admission history changed")
            return records
        except (
            JournalCodecError,
            JournalFileError,
            OSError,
            UnicodeError,
            TypeError,
            ValueError,
        ) as exc:
            raise self._error(
                "Product rebind admission journal is corrupt",
                code="package_product_rebind_admission_corrupt",
            ) from exc

    def _error(
        self, message: str, *, code: str
    ) -> PackageProductRebindAdmissionBindingError:
        return PackageProductRebindAdmissionBindingError(
            message, code=code, path=self._path
        )


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Product rebind admission contains duplicate JSON keys")
        result[key] = value
    return result
