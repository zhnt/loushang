"""Durable selection and verified-plan evidence for PLC9B closure recovery."""

from __future__ import annotations

import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal

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
    load_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    PackageClosureBudgetV1,
    PackageResolutionEnvironmentV1,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    PackageDependencySelectionRequestV1,
    PackageDependencySelectionV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

PACKAGE_CLOSURE_RESOLUTION_RECORD_VERSION = 1
PACKAGE_CLOSURE_RESOLUTION_BASIS_VERSION = 1

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class PackageClosureResolutionBasisV1:
    """Credential-free, complete resolution inputs bound before dependency I/O."""

    operation_id: str
    attempt_epoch: int
    request_fingerprint: str
    policy_revision: str
    quota_profile_revision: str
    resolution_environment: PackageResolutionEnvironmentV1
    budgets: PackageClosureBudgetV1
    root_extras: tuple[str, ...] = ()
    basis_version: int = PACKAGE_CLOSURE_RESOLUTION_BASIS_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "Package operation id"),
            (self.policy_revision, "Package policy revision"),
            (self.quota_profile_revision, "Package quota profile revision"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        if (
            not isinstance(self.attempt_epoch, int)
            or isinstance(self.attempt_epoch, bool)
            or self.attempt_epoch < 1
        ):
            raise ValueError("Package attempt epoch must be positive")
        if (
            not isinstance(self.request_fingerprint, str)
            or _SHA256.fullmatch(self.request_fingerprint) is None
        ):
            raise ValueError("Package request fingerprint must be SHA-256")
        if not isinstance(self.resolution_environment, PackageResolutionEnvironmentV1):
            raise TypeError("Package resolution environment is required")
        if not isinstance(self.budgets, PackageClosureBudgetV1):
            raise TypeError("Package closure budgets are required")
        if (
            not isinstance(self.root_extras, tuple)
            or any(not isinstance(extra, str) for extra in self.root_extras)
            or self.root_extras != tuple(sorted(set(self.root_extras)))
        ):
            raise ValueError("Root Package extras must be canonical and unique")
        if self.root_extras:
            parsed = NormalizedPackageRequirementV1.parse(
                f"root[{','.join(self.root_extras)}]"
            )
            if parsed.extras != self.root_extras:
                raise ValueError("Root Package extras must be canonical and unique")
        if self.basis_version != PACKAGE_CLOSURE_RESOLUTION_BASIS_VERSION:
            raise ValueError("Unsupported Package closure resolution basis")

    @property
    def fingerprint(self) -> str:
        return sha256(canonical_json_bytes(self.to_dict())).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptEpoch": self.attempt_epoch,
            "basisVersion": self.basis_version,
            "budgets": self.budgets.to_dict(),
            "operationId": self.operation_id,
            "policyRevision": self.policy_revision,
            "quotaProfileRevision": self.quota_profile_revision,
            "requestFingerprint": self.request_fingerprint,
            "resolutionEnvironment": self.resolution_environment.to_dict(),
            "rootExtras": list(self.root_extras),
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageClosureResolutionBasisV1:
        if not isinstance(value, dict) or set(value) != {
            "attemptEpoch",
            "basisVersion",
            "budgets",
            "operationId",
            "policyRevision",
            "quotaProfileRevision",
            "requestFingerprint",
            "resolutionEnvironment",
            "rootExtras",
        }:
            raise ValueError("Package closure resolution basis schema changed")
        extras = value["rootExtras"]
        if not isinstance(extras, list):
            raise TypeError("Root Package extras must be a list")
        return cls(
            operation_id=_wire_string(value["operationId"], name="operation id"),
            attempt_epoch=_wire_int(value["attemptEpoch"], name="attempt epoch"),
            request_fingerprint=_wire_string(
                value["requestFingerprint"], name="request fingerprint"
            ),
            policy_revision=_wire_string(
                value["policyRevision"], name="policy revision"
            ),
            quota_profile_revision=_wire_string(
                value["quotaProfileRevision"], name="quota profile revision"
            ),
            resolution_environment=PackageResolutionEnvironmentV1.from_dict(
                value["resolutionEnvironment"]
            ),
            budgets=PackageClosureBudgetV1.from_dict(value["budgets"]),
            root_extras=tuple(
                _wire_string(extra, name="root extra") for extra in extras
            ),
            basis_version=_wire_int(value["basisVersion"], name="basis version"),
        )


PackageClosureResolutionEvidenceKind = Literal[
    "resolution_basis", "selection", "verified_plan"
]
PackageClosureResolutionEvidence = (
    PackageClosureResolutionBasisV1
    | PackageDependencySelectionV1
    | VerifiedClosurePlanV2
)


class PackageClosureResolutionJournalError(RuntimeError):
    """Fail-closed append, replay, identity, phase, or corruption error."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PackageClosureResolutionRecordV1:
    record_revision: int
    prior_resolution_revision: int
    request_fingerprint: str
    evidence: PackageClosureResolutionEvidence
    record_version: int = PACKAGE_CLOSURE_RESOLUTION_RECORD_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.record_revision, int)
            or isinstance(self.record_revision, bool)
            or self.record_revision < 1
        ):
            raise ValueError("Closure resolution revision must be positive")
        if (
            not isinstance(self.prior_resolution_revision, int)
            or isinstance(self.prior_resolution_revision, bool)
            or self.prior_resolution_revision < 0
        ):
            raise ValueError("Prior closure resolution revision must be non-negative")
        if (
            not isinstance(self.request_fingerprint, str)
            or _SHA256.fullmatch(self.request_fingerprint) is None
        ):
            raise ValueError("Closure request fingerprint must be SHA-256")
        if not isinstance(
            self.evidence,
            PackageClosureResolutionBasisV1
            | PackageDependencySelectionV1
            | VerifiedClosurePlanV2,
        ):
            raise TypeError("Typed Package closure resolution evidence is required")
        if (
            isinstance(
                self.evidence,
                PackageClosureResolutionBasisV1 | PackageDependencySelectionV1,
            )
            and self.evidence.request_fingerprint != self.request_fingerprint
        ):
            raise ValueError("Closure resolution request fingerprint changed")
        if self.record_version != PACKAGE_CLOSURE_RESOLUTION_RECORD_VERSION:
            raise ValueError("Unsupported Package closure resolution record")

    @property
    def operation_id(self) -> str:
        return self.evidence.operation_id

    @property
    def attempt_epoch(self) -> int:
        return self.evidence.attempt_epoch

    @property
    def evidence_kind(self) -> PackageClosureResolutionEvidenceKind:
        if isinstance(self.evidence, PackageClosureResolutionBasisV1):
            return "resolution_basis"
        if isinstance(self.evidence, PackageDependencySelectionV1):
            return "selection"
        return "verified_plan"

    @property
    def evidence_ref(self) -> str:
        return self.evidence.fingerprint

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptEpoch": self.attempt_epoch,
            "evidence": self.evidence.to_dict(),
            "evidenceKind": self.evidence_kind,
            "evidenceRef": self.evidence_ref,
            "operationId": self.operation_id,
            "priorResolutionRevision": self.prior_resolution_revision,
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
            "requestFingerprint": self.request_fingerprint,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageClosureResolutionRecordV1:
        if not isinstance(value, dict) or set(value) != {
            "attemptEpoch",
            "evidence",
            "evidenceKind",
            "evidenceRef",
            "operationId",
            "priorResolutionRevision",
            "recordRevision",
            "recordVersion",
            "requestFingerprint",
        }:
            raise ValueError("Package closure resolution record schema changed")
        kind = value["evidenceKind"]
        if kind == "resolution_basis":
            evidence: PackageClosureResolutionEvidence = (
                PackageClosureResolutionBasisV1.from_dict(value["evidence"])
            )
        elif kind == "selection":
            evidence = PackageDependencySelectionV1.from_dict(value["evidence"])
        elif kind == "verified_plan":
            evidence = VerifiedClosurePlanV2.from_dict(value["evidence"])
        else:
            raise ValueError("Unsupported Package closure resolution evidence kind")
        record = cls(
            record_revision=_wire_int(
                value["recordRevision"], name="resolution record revision"
            ),
            prior_resolution_revision=_wire_int(
                value["priorResolutionRevision"], name="prior resolution revision"
            ),
            request_fingerprint=_wire_string(
                value["requestFingerprint"], name="request fingerprint"
            ),
            evidence=evidence,
            record_version=_wire_int(
                value["recordVersion"], name="resolution record version"
            ),
        )
        if (
            value["operationId"] != record.operation_id
            or value["attemptEpoch"] != record.attempt_epoch
            or value["evidenceRef"] != record.evidence_ref
        ):
            raise ValueError("Package closure resolution projection changed")
        return record


def _encode_record(record: PackageClosureResolutionRecordV1) -> dict[str, object]:
    if not isinstance(record, PackageClosureResolutionRecordV1):
        raise TypeError("Package closure resolution record is required")
    return record.to_dict()


def _decode_record(value: object) -> PackageClosureResolutionRecordV1:
    try:
        return PackageClosureResolutionRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Package closure resolution record is invalid",
            code="invalid_package_closure_resolution_record",
        ) from exc


PACKAGE_CLOSURE_RESOLUTION_JOURNAL_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_record,
    decoder=_decode_record,
)


class PackageClosureResolutionJournal:
    """Bind inputs, append selections before I/O, then one exact verified plan."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def basis(
        self,
        *,
        operation_id: str,
        attempt_epoch: int,
    ) -> PackageClosureResolutionBasisV1 | None:
        with self._exclusive():
            record = _find_basis(
                self._load_unlocked(),
                operation_id=operation_id,
                attempt_epoch=attempt_epoch,
            )
            return (
                record.evidence
                if record is not None
                and isinstance(record.evidence, PackageClosureResolutionBasisV1)
                else None
            )

    def bind_basis(
        self,
        basis: PackageClosureResolutionBasisV1,
    ) -> PackageClosureResolutionBasisV1:
        if not isinstance(basis, PackageClosureResolutionBasisV1):
            raise TypeError("Package closure resolution basis is required")
        with self._exclusive():
            records = self._load_unlocked()
            existing = _find_basis(
                records,
                operation_id=basis.operation_id,
                attempt_epoch=basis.attempt_epoch,
            )
            if existing is not None:
                if existing.evidence == basis:
                    return basis
                raise self._error(
                    "Package closure resolution basis changed",
                    code="package_operation_identity_conflict",
                )
            if any(
                record.operation_id == basis.operation_id
                and record.attempt_epoch == basis.attempt_epoch
                for record in records
            ):
                raise self._error(
                    "Package closure resolution basis follows other evidence",
                    code="package_operation_phase_conflict",
                )
            self._append_unlocked(
                records,
                request_fingerprint=basis.request_fingerprint,
                evidence=basis,
            )
            return basis

    def selection(
        self,
        request: PackageDependencySelectionRequestV1,
    ) -> PackageDependencySelectionV1 | None:
        if not isinstance(request, PackageDependencySelectionRequestV1):
            raise TypeError("Package dependency selection request is required")
        with self._exclusive():
            records = self._load_unlocked()
            try:
                _require_basis_for_selection(records, request)
            except ValueError as exc:
                raise self._error(
                    "Package dependency selection changed its resolution basis",
                    code="package_operation_identity_conflict",
                ) from exc
            record = _find_selection_by_key(records, request)
            if record is not None and (
                not isinstance(record.evidence, PackageDependencySelectionV1)
                or not record.evidence.matches(request)
            ):
                raise self._error(
                    "Package dependency selection request identity changed",
                    code="package_operation_identity_conflict",
                )
            return (
                record.evidence
                if record is not None
                and isinstance(record.evidence, PackageDependencySelectionV1)
                else None
            )

    def append_selection(
        self,
        request: PackageDependencySelectionRequestV1,
        selection: PackageDependencySelectionV1,
    ) -> PackageDependencySelectionV1:
        if not isinstance(request, PackageDependencySelectionRequestV1):
            raise TypeError("Package dependency selection request is required")
        if not isinstance(selection, PackageDependencySelectionV1):
            raise TypeError("Package dependency selection evidence is required")
        if not selection.matches(request):
            raise self._error(
                "Package dependency selection identity changed",
                code="package_operation_identity_conflict",
            )
        with self._exclusive():
            records = self._load_unlocked()
            try:
                _require_basis_for_selection(records, request)
            except ValueError as exc:
                raise self._error(
                    "Package dependency selection changed its resolution basis",
                    code="package_operation_identity_conflict",
                ) from exc
            existing = _find_selection_by_key(records, request)
            if existing is not None:
                if (
                    isinstance(existing.evidence, PackageDependencySelectionV1)
                    and existing.evidence.matches(request)
                    and existing.evidence == selection
                ):
                    return selection
                raise self._error(
                    "Package dependency selection changed",
                    code="package_operation_identity_conflict",
                )
            if (
                _find_plan(
                    records,
                    operation_id=request.operation_id,
                    attempt_epoch=request.attempt_epoch,
                )
                is not None
            ):
                raise self._error(
                    "Package dependency selection follows verified plan",
                    code="package_operation_phase_conflict",
                )
            self._append_unlocked(
                records,
                request_fingerprint=request.request_fingerprint,
                evidence=selection,
            )
            return selection

    def plan(
        self,
        *,
        operation_id: str,
        attempt_epoch: int,
    ) -> VerifiedClosurePlanV2 | None:
        with self._exclusive():
            record = _find_plan(
                self._load_unlocked(),
                operation_id=operation_id,
                attempt_epoch=attempt_epoch,
            )
            return (
                record.evidence
                if record is not None
                and isinstance(record.evidence, VerifiedClosurePlanV2)
                else None
            )

    def append_plan(
        self,
        *,
        request_fingerprint: str,
        plan: VerifiedClosurePlanV2,
    ) -> VerifiedClosurePlanV2:
        if not isinstance(plan, VerifiedClosurePlanV2):
            raise TypeError("Verified Package closure plan is required")
        with self._exclusive():
            records = self._load_unlocked()
            try:
                basis = _require_basis(
                    records,
                    operation_id=plan.operation_id,
                    attempt_epoch=plan.attempt_epoch,
                )
            except ValueError as exc:
                raise self._error(
                    "Verified Package closure plan has no resolution basis",
                    code="package_operation_identity_conflict",
                ) from exc
            if (
                basis.request_fingerprint != request_fingerprint
                or basis.resolution_environment.fingerprint
                != plan.resolution_environment_fingerprint
            ):
                raise self._error(
                    "Verified Package closure plan changed its resolution basis",
                    code="package_operation_identity_conflict",
                )
            existing = _find_plan(
                records,
                operation_id=plan.operation_id,
                attempt_epoch=plan.attempt_epoch,
            )
            if existing is not None:
                if (
                    existing.request_fingerprint == request_fingerprint
                    and existing.evidence == plan
                ):
                    return plan
                raise self._error(
                    "Verified Package closure plan changed",
                    code="package_operation_identity_conflict",
                )
            try:
                _require_exact_plan_selections(
                    records,
                    request_fingerprint=request_fingerprint,
                    plan=plan,
                )
            except ValueError as exc:
                raise self._error(
                    "Verified Package closure plan changed its selections",
                    code="package_operation_identity_conflict",
                ) from exc
            self._append_unlocked(
                records,
                request_fingerprint=request_fingerprint,
                evidence=plan,
            )
            return plan

    def records(self) -> tuple[PackageClosureResolutionRecordV1, ...]:
        with self._exclusive():
            return self._load_unlocked()

    def _append_unlocked(
        self,
        records: tuple[PackageClosureResolutionRecordV1, ...],
        *,
        request_fingerprint: str,
        evidence: PackageClosureResolutionEvidence,
    ) -> None:
        record = PackageClosureResolutionRecordV1(
            record_revision=len(records) + 1,
            prior_resolution_revision=_last_resolution_revision(
                records,
                operation_id=evidence.operation_id,
                attempt_epoch=evidence.attempt_epoch,
            ),
            request_fingerprint=request_fingerprint,
            evidence=evidence,
        )
        append_jsonl_record(
            self._path,
            record,
            record_codec=PACKAGE_CLOSURE_RESOLUTION_JOURNAL_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )

    def _load_unlocked(self) -> tuple[PackageClosureResolutionRecordV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, PackageClosureResolutionRecordV1] = (
                load_jsonl(
                    self._path,
                    record_codec=PACKAGE_CLOSURE_RESOLUTION_JOURNAL_CODEC,
                    format_profile=SORTED_UNICODE_JSONL_FORMAT,
                    durability=self._unlocked_durability,
                    load_policy=self._load_policy,
                )
            )
            records = snapshot.records
            _assert_no_duplicate_json_keys(self._path)
            _validate_records(records)
            return records
        except (JournalCodecError, JournalFileError, TypeError, ValueError) as exc:
            raise self._error(
                "Package closure resolution journal is corrupt",
                code="package_closure_resolution_journal_corrupt",
            ) from exc

    def _exclusive(self) -> AbstractContextManager[None]:
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )

    def _error(
        self,
        message: str,
        *,
        code: str,
    ) -> PackageClosureResolutionJournalError:
        return PackageClosureResolutionJournalError(
            message,
            code=code,
            path=self._path,
        )


def _validate_records(records: tuple[PackageClosureResolutionRecordV1, ...]) -> None:
    latest: dict[tuple[str, int], int] = {}
    bases: dict[tuple[str, int], PackageClosureResolutionBasisV1] = {}
    selections: dict[tuple[str, int, str, str], PackageClosureResolutionRecordV1] = {}
    plans: set[tuple[str, int]] = set()
    for revision, record in enumerate(records, start=1):
        if record.record_revision != revision:
            raise ValueError("Package closure resolution revisions are not contiguous")
        attempt_key = (record.operation_id, record.attempt_epoch)
        if record.prior_resolution_revision != latest.get(attempt_key, 0):
            raise ValueError("Package closure resolution predecessor changed")
        if record.evidence_kind == "resolution_basis":
            basis_evidence = record.evidence
            if (
                not isinstance(basis_evidence, PackageClosureResolutionBasisV1)
                or attempt_key in bases
                or attempt_key in latest
            ):
                raise ValueError("Package closure resolution basis was appended twice")
            bases[attempt_key] = basis_evidence
        elif record.evidence_kind == "selection":
            selection = record.evidence
            if not isinstance(selection, PackageDependencySelectionV1):
                raise ValueError("Package dependency selection kind changed")
            selection_basis = bases.get(attempt_key)
            if (
                selection_basis is None
                or selection_basis.request_fingerprint
                != selection.request_fingerprint
                or selection_basis.resolution_environment.fingerprint
                != selection.resolution_environment_fingerprint
            ):
                raise ValueError("Package selection changed its resolution basis")
            if attempt_key in plans:
                raise ValueError("Package dependency selection follows verified plan")
            key = (
                *attempt_key,
                selection.parent_node_id,
                selection.requirement_fingerprint,
            )
            if key in selections:
                raise ValueError("Package dependency selection was appended twice")
            selections[key] = record
        else:
            plan = record.evidence
            if not isinstance(plan, VerifiedClosurePlanV2) or attempt_key in plans:
                raise ValueError("Verified Package closure plan was appended twice")
            plan_basis = bases.get(attempt_key)
            if (
                plan_basis is None
                or plan_basis.request_fingerprint != record.request_fingerprint
                or plan_basis.resolution_environment.fingerprint
                != plan.resolution_environment_fingerprint
            ):
                raise ValueError("Verified plan changed its resolution basis")
            _require_exact_plan_selections(
                tuple(selections.values()),
                request_fingerprint=record.request_fingerprint,
                plan=plan,
            )
            plans.add(attempt_key)
        latest[attempt_key] = record.record_revision


def _require_exact_plan_selections(
    records: tuple[PackageClosureResolutionRecordV1, ...],
    *,
    request_fingerprint: str,
    plan: VerifiedClosurePlanV2,
) -> None:
    by_id = {node.node_id: node for node in plan.nodes}
    expected: dict[tuple[str, int, str, str], tuple[str, str, str, str]] = {}
    for node in plan.nodes:
        for resolution in node.requirements:
            if not resolution.marker_applies:
                continue
            selected_id = resolution.selected_node_id
            if selected_id is None or selected_id not in by_id:
                raise ValueError("Verified plan selection target is missing")
            target = by_id[selected_id]
            requirement_fingerprint = sha256(
                canonical_json_bytes(resolution.requirement.to_dict())
            ).hexdigest()
            expected[
                (
                    plan.operation_id,
                    plan.attempt_epoch,
                    node.node_id,
                    requirement_fingerprint,
                )
            ] = (
                target.distribution,
                target.version,
                target.canonical_source_identity,
                target.artifact_digest,
            )
    observed: dict[tuple[str, int, str, str], tuple[str, str, str, str]] = {}
    for record in records:
        evidence = record.evidence
        if (
            record.operation_id != plan.operation_id
            or record.attempt_epoch != plan.attempt_epoch
            or not isinstance(evidence, PackageDependencySelectionV1)
        ):
            continue
        if record.request_fingerprint != request_fingerprint:
            raise ValueError("Package closure request fingerprint changed")
        observed[
            (
                evidence.operation_id,
                evidence.attempt_epoch,
                evidence.parent_node_id,
                evidence.requirement_fingerprint,
            )
        ] = (
            evidence.project_name,
            evidence.version,
            evidence.canonical_source_identity,
            evidence.expected_artifact_digest,
        )
        if evidence.resolution_environment_fingerprint != (
            plan.resolution_environment_fingerprint
        ):
            raise ValueError("Package closure resolution environment changed")
    if observed != expected:
        raise ValueError("Verified plan does not cover the exact selection set")


def _require_basis(
    records: tuple[PackageClosureResolutionRecordV1, ...],
    *,
    operation_id: str,
    attempt_epoch: int,
) -> PackageClosureResolutionBasisV1:
    record = _find_basis(
        records,
        operation_id=operation_id,
        attempt_epoch=attempt_epoch,
    )
    if record is None or not isinstance(
        record.evidence, PackageClosureResolutionBasisV1
    ):
        raise ValueError("Package closure resolution basis is missing")
    return record.evidence


def _require_basis_for_selection(
    records: tuple[PackageClosureResolutionRecordV1, ...],
    request: PackageDependencySelectionRequestV1,
) -> PackageClosureResolutionBasisV1:
    basis = _require_basis(
        records,
        operation_id=request.operation_id,
        attempt_epoch=request.attempt_epoch,
    )
    if (
        basis.request_fingerprint != request.request_fingerprint
        or basis.resolution_environment.fingerprint
        != request.resolution_environment_fingerprint
    ):
        raise ValueError("Package selection changed its resolution basis")
    return basis


def _find_basis(
    records: tuple[PackageClosureResolutionRecordV1, ...],
    *,
    operation_id: str,
    attempt_epoch: int,
) -> PackageClosureResolutionRecordV1 | None:
    return next(
        (
            record
            for record in reversed(records)
            if record.operation_id == operation_id
            and record.attempt_epoch == attempt_epoch
            and isinstance(record.evidence, PackageClosureResolutionBasisV1)
        ),
        None,
    )


def _find_selection_by_key(
    records: tuple[PackageClosureResolutionRecordV1, ...],
    request: PackageDependencySelectionRequestV1,
) -> PackageClosureResolutionRecordV1 | None:
    return next(
        (
            record
            for record in reversed(records)
            if isinstance(record.evidence, PackageDependencySelectionV1)
            and record.operation_id == request.operation_id
            and record.attempt_epoch == request.attempt_epoch
            and record.evidence.parent_node_id == request.parent_node_id
            and record.evidence.requirement_fingerprint
            == request.requirement_fingerprint
        ),
        None,
    )


def _find_plan(
    records: tuple[PackageClosureResolutionRecordV1, ...],
    *,
    operation_id: str,
    attempt_epoch: int,
) -> PackageClosureResolutionRecordV1 | None:
    return next(
        (
            record
            for record in reversed(records)
            if record.operation_id == operation_id
            and record.attempt_epoch == attempt_epoch
            and isinstance(record.evidence, VerifiedClosurePlanV2)
        ),
        None,
    )


def _last_resolution_revision(
    records: tuple[PackageClosureResolutionRecordV1, ...],
    *,
    operation_id: str,
    attempt_epoch: int,
) -> int:
    for record in reversed(records):
        if (
            record.operation_id == operation_id
            and record.attempt_epoch == attempt_epoch
        ):
            return record.record_revision
    return 0


def _assert_no_duplicate_json_keys(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            json.loads(line, object_pairs_hook=_unique_json_object)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("Package closure resolution has duplicate JSON keys")
        document[key] = value
    return document


def _wire_int(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return value


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string")
    return value


__all__ = [
    "PACKAGE_CLOSURE_RESOLUTION_JOURNAL_CODEC",
    "PackageClosureResolutionBasisV1",
    "PackageClosureResolutionJournal",
    "PackageClosureResolutionJournalError",
    "PackageClosureResolutionRecordV1",
]
