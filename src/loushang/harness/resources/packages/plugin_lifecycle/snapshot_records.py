"""Authenticated pre-B snapshot records; persisted wire identities are unchanged."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import cast

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    _string_value as _wire_string,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

PACKAGE_OFFLINE_RESTORE_SNAPSHOT_EVIDENCE_VERSION = 1

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

PACKAGE_PRE_B_SNAPSHOT_DOMAINS = (
    "binding_history",
    "desired_state",
    "enablement_state",
    "fence_record",
    "instance_state",
    "legacy_root_pointer",
    "lock_history",
    "source_configuration",
    "store_bytes",
)


class PackageOfflineRestoreError(RuntimeError):
    """Fail-closed local cleanup or contract failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        evidence_ref: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.evidence_ref = evidence_ref


@dataclass(frozen=True, slots=True)
class PackageOfflineRestoreSnapshotEvidenceV1:
    """Complete authenticated pre-B backup manifest around the cutover proof."""

    evidence_id: str
    snapshot: PackageEpochCutoverSnapshotReceiptV1
    snapshot_tree_digest: str
    state_manifest_digest: str
    covered_domains: tuple[str, ...] = PACKAGE_PRE_B_SNAPSHOT_DOMAINS
    evidence_version: int = PACKAGE_OFFLINE_RESTORE_SNAPSHOT_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.evidence_id, name="offline snapshot evidence identity")
        if not isinstance(self.snapshot, PackageEpochCutoverSnapshotReceiptV1):
            raise TypeError("Package epoch snapshot receipt is required")
        _require_sha256(
            self.snapshot_tree_digest,
            name="Package snapshot tree digest",
        )
        _require_sha256(
            self.state_manifest_digest,
            name="Package pre-B state manifest digest",
        )
        if self.covered_domains != PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
            raise ValueError("Package pre-B snapshot domains are incomplete")
        if self.evidence_version != PACKAGE_OFFLINE_RESTORE_SNAPSHOT_EVIDENCE_VERSION:
            raise ValueError("Unsupported Package offline snapshot evidence")
        if self.evidence_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package offline snapshot evidence does not match")

    @classmethod
    def create(
        cls,
        snapshot: PackageEpochCutoverSnapshotReceiptV1,
        *,
        snapshot_tree_digest: str,
        state_manifest_digest: str,
    ) -> PackageOfflineRestoreSnapshotEvidenceV1:
        if not isinstance(snapshot, PackageEpochCutoverSnapshotReceiptV1):
            raise TypeError("Package epoch snapshot receipt is required")
        values = _snapshot_evidence_identity(
            snapshot=snapshot,
            snapshot_tree_digest=snapshot_tree_digest,
            state_manifest_digest=state_manifest_digest,
            covered_domains=PACKAGE_PRE_B_SNAPSHOT_DOMAINS,
            evidence_version=PACKAGE_OFFLINE_RESTORE_SNAPSHOT_EVIDENCE_VERSION,
        )
        return cls(
            evidence_id=_fingerprint(values),
            snapshot=snapshot,
            snapshot_tree_digest=snapshot_tree_digest,
            state_manifest_digest=state_manifest_digest,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _snapshot_evidence_identity(
            snapshot=self.snapshot,
            snapshot_tree_digest=self.snapshot_tree_digest,
            state_manifest_digest=self.state_manifest_digest,
            covered_domains=self.covered_domains,
            evidence_version=self.evidence_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"evidenceId": self.evidence_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageOfflineRestoreSnapshotEvidenceV1:
        document = _wire_object(
            value,
            expected=_OFFLINE_RESTORE_SNAPSHOT_EVIDENCE_V1_SCHEMA.keys,
            name="Package offline snapshot evidence",
        )
        return _OFFLINE_RESTORE_SNAPSHOT_EVIDENCE_V1_SCHEMA.decode(cls, document)


def _snapshot_evidence_identity(
    *,
    snapshot: PackageEpochCutoverSnapshotReceiptV1,
    snapshot_tree_digest: str,
    state_manifest_digest: str,
    covered_domains: tuple[str, ...],
    evidence_version: int,
) -> dict[str, object]:
    return {
        "snapshot": snapshot.to_dict(),
        "snapshotTreeDigest": snapshot_tree_digest,
        "stateManifestDigest": state_manifest_digest,
        "coveredDomains": list(covered_domains),
        "evidenceVersion": evidence_version,
    }


def _fingerprint(value: dict[str, object]) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _wire_object(
    value: object,
    *,
    expected: set[str],
    name: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise TypeError(f"{name} must be an object")
    if set(value) != expected:
        raise ValueError(f"{name} does not match its versioned schema")
    return cast(dict[str, object], value)


def _wire_int(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    return value


def _wire_string_tuple(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TypeError(f"{name} must be a string array")
    return tuple(value)


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


__all__: tuple[str, ...] = ()


_OFFLINE_RESTORE_SNAPSHOT_EVIDENCE_V1_SCHEMA = RecordSchema.for_dataclass(
    PackageOfflineRestoreSnapshotEvidenceV1,
    _wire_string,
    RecordField("snapshot", decoder=PackageEpochCutoverSnapshotReceiptV1.from_dict),
    RecordField("covered_domains", "covered domains", _wire_string_tuple),
    RecordField("evidence_version", "evidence version", _wire_int),
    derive_labels=True,
)
