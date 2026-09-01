"""PLC9B2 safe wheel inspection and rooted quarantine extraction."""

from __future__ import annotations

import base64
import csv
import io
import os
import re
import stat
import struct
import time
import unicodedata
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import compat32
from hashlib import new as new_digest
from hashlib import sha256
from typing import BinaryIO, Literal, NoReturn, cast

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AcquiredPackageCandidate,
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

PACKAGE_INSPECTION_BUDGET_VERSION = 1
VERIFIED_WHEEL_ARTIFACT_VERSION = 1

InspectionStage = Literal["inspecting", "extracted"]

_EOCD = struct.Struct("<4s4H2LH")
_CENTRAL = struct.Struct("<4s6H3L5H2L")
_LOCAL = struct.Struct("<4s5H3L2H")
_SUPPORTED_COMPRESSION = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
_SUPPORTED_HASHES = {"sha256", "sha384", "sha512"}
_SAFE_WHEEL_PART = re.compile(r"[A-Za-z0-9_.!+]+\Z")
_SAFE_TAG_PART = re.compile(r"[A-Za-z0-9_.]+\Z")
_WINDOWS_RESERVED = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class PackageWheelVerificationError(RuntimeError):
    """Bounded, secret-free archive or wheel rejection."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        stage: InspectionStage,
        consumed_bytes: int = 0,
        rejection_code: str | None = None,
        rejection_stage: InspectionStage | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.retryable = False
        self.consumed_bytes = consumed_bytes
        self.rejection_code = rejection_code
        self.rejection_stage = rejection_stage
        if (rejection_code is None) != (rejection_stage is None):
            raise ValueError("Cleanup debt must retain the complete rejection")
        if code == "package_quarantine_cleanup_retryable":
            if rejection_code is None or rejection_stage is None:
                raise ValueError("Cleanup debt requires its original rejection")
        elif rejection_code is not None or rejection_stage is not None:
            raise ValueError("Only cleanup debt may carry an original rejection")


@dataclass(frozen=True, slots=True)
class PackageInspectionBudgetV1:
    max_entries: int = 4096
    max_total_expanded_bytes: int = 512 * 1024 * 1024
    max_entry_expanded_bytes: int = 128 * 1024 * 1024
    max_path_length: int = 1024
    max_path_component_length: int = 255
    max_path_components: int = 64
    max_metadata_bytes: int = 4 * 1024 * 1024
    max_wall_time_ms: int = 30_000
    budget_version: int = PACKAGE_INSPECTION_BUDGET_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.max_entries, "entry budget"),
            (self.max_total_expanded_bytes, "total expansion budget"),
            (self.max_entry_expanded_bytes, "entry expansion budget"),
            (self.max_path_length, "path length budget"),
            (self.max_path_component_length, "path component length budget"),
            (self.max_path_components, "path component budget"),
            (self.max_metadata_bytes, "metadata budget"),
            (self.max_wall_time_ms, "inspection wall-clock budget"),
        ):
            _require_positive(value, name=name)
        if self.budget_version != PACKAGE_INSPECTION_BUDGET_VERSION:
            raise ValueError("Unsupported Package inspection budget")

    def to_dict(self) -> dict[str, int]:
        return {
            "budgetVersion": self.budget_version,
            "maxEntries": self.max_entries,
            "maxEntryExpandedBytes": self.max_entry_expanded_bytes,
            "maxMetadataBytes": self.max_metadata_bytes,
            "maxPathComponentLength": self.max_path_component_length,
            "maxPathComponents": self.max_path_components,
            "maxPathLength": self.max_path_length,
            "maxTotalExpandedBytes": self.max_total_expanded_bytes,
            "maxWallTimeMs": self.max_wall_time_ms,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageInspectionBudgetV1:
        document = _exact_dict(
            value,
            fields={
                "budgetVersion",
                "maxEntries",
                "maxEntryExpandedBytes",
                "maxMetadataBytes",
                "maxPathComponentLength",
                "maxPathComponents",
                "maxPathLength",
                "maxTotalExpandedBytes",
                "maxWallTimeMs",
            },
            name="Package inspection budget",
        )
        return cls(
            max_entries=_wire_int(document["maxEntries"], name="entry budget"),
            max_total_expanded_bytes=_wire_int(
                document["maxTotalExpandedBytes"],
                name="total expansion budget",
            ),
            max_entry_expanded_bytes=_wire_int(
                document["maxEntryExpandedBytes"],
                name="entry expansion budget",
            ),
            max_path_length=_wire_int(
                document["maxPathLength"], name="path length budget"
            ),
            max_path_component_length=_wire_int(
                document["maxPathComponentLength"],
                name="path component length budget",
            ),
            max_path_components=_wire_int(
                document["maxPathComponents"], name="path component budget"
            ),
            max_metadata_bytes=_wire_int(
                document["maxMetadataBytes"], name="metadata budget"
            ),
            max_wall_time_ms=_wire_int(
                document["maxWallTimeMs"], name="wall-clock budget"
            ),
            budget_version=_wire_int(document["budgetVersion"], name="budget version"),
        )


@dataclass(frozen=True, slots=True)
class VerifiedWheelArtifactV1:
    operation_id: str
    attempt_epoch: int
    node_id: str
    distribution: str
    version: str
    wheel_filename: str
    compatible_tags: tuple[str, ...]
    artifact_digest: str
    artifact_size: int
    wheel_metadata_digest: str
    package_metadata_digest: str
    record_digest: str
    record_verified: bool
    entry_count: int
    expanded_byte_count: int
    extraction_tree_digest: str
    evidence_version: int = VERIFIED_WHEEL_ARTIFACT_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "operation id"),
            (self.node_id, "node id"),
            (self.distribution, "distribution"),
            (self.version, "version"),
            (self.wheel_filename, "wheel filename"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        _require_positive(self.attempt_epoch, name="attempt epoch")
        _require_nonnegative(self.artifact_size, name="artifact size")
        _require_positive(self.entry_count, name="entry count")
        _require_nonnegative(self.expanded_byte_count, name="expanded byte count")
        for value, name in (
            (self.artifact_digest, "artifact digest"),
            (self.wheel_metadata_digest, "WHEEL digest"),
            (self.package_metadata_digest, "METADATA digest"),
            (self.record_digest, "RECORD digest"),
            (self.extraction_tree_digest, "extraction tree digest"),
        ):
            _require_sha256(value, name=name)
        if (
            not self.compatible_tags
            or tuple(sorted(set(self.compatible_tags))) != self.compatible_tags
        ):
            raise ValueError("Compatible wheel tags must be sorted and unique")
        if self.record_verified is not True:
            raise ValueError("Verified wheel evidence requires complete RECORD proof")
        if self.evidence_version != VERIFIED_WHEEL_ARTIFACT_VERSION:
            raise ValueError("Unsupported verified wheel evidence")

    @property
    def fingerprint(self) -> str:
        return sha256(canonical_json_bytes(self.to_dict())).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "artifactDigest": self.artifact_digest,
            "artifactSize": self.artifact_size,
            "attemptEpoch": self.attempt_epoch,
            "compatibleTags": list(self.compatible_tags),
            "distribution": self.distribution,
            "entryCount": self.entry_count,
            "evidenceVersion": self.evidence_version,
            "expandedByteCount": self.expanded_byte_count,
            "extractionTreeDigest": self.extraction_tree_digest,
            "nodeId": self.node_id,
            "operationId": self.operation_id,
            "packageMetadataDigest": self.package_metadata_digest,
            "recordDigest": self.record_digest,
            "recordVerified": self.record_verified,
            "version": self.version,
            "wheelFilename": self.wheel_filename,
            "wheelMetadataDigest": self.wheel_metadata_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> VerifiedWheelArtifactV1:
        document = _exact_dict(
            value,
            fields={
                "artifactDigest",
                "artifactSize",
                "attemptEpoch",
                "compatibleTags",
                "distribution",
                "entryCount",
                "evidenceVersion",
                "expandedByteCount",
                "extractionTreeDigest",
                "nodeId",
                "operationId",
                "packageMetadataDigest",
                "recordDigest",
                "recordVerified",
                "version",
                "wheelFilename",
                "wheelMetadataDigest",
            },
            name="verified wheel artifact",
        )
        tags = document["compatibleTags"]
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise TypeError("compatible tags must be a string list")
        record_verified = document["recordVerified"]
        if not isinstance(record_verified, bool):
            raise TypeError("RECORD verification must be a boolean")
        return cls(
            operation_id=_wire_string(document["operationId"], name="operation id"),
            attempt_epoch=_wire_int(document["attemptEpoch"], name="attempt epoch"),
            node_id=_wire_string(document["nodeId"], name="node id"),
            distribution=_wire_string(document["distribution"], name="distribution"),
            version=_wire_string(document["version"], name="version"),
            wheel_filename=_wire_string(
                document["wheelFilename"], name="wheel filename"
            ),
            compatible_tags=tuple(tags),
            artifact_digest=_wire_string(
                document["artifactDigest"], name="artifact digest"
            ),
            artifact_size=_wire_int(document["artifactSize"], name="artifact size"),
            wheel_metadata_digest=_wire_string(
                document["wheelMetadataDigest"], name="WHEEL digest"
            ),
            package_metadata_digest=_wire_string(
                document["packageMetadataDigest"], name="METADATA digest"
            ),
            record_digest=_wire_string(document["recordDigest"], name="RECORD digest"),
            record_verified=record_verified,
            entry_count=_wire_int(document["entryCount"], name="entry count"),
            expanded_byte_count=_wire_int(
                document["expandedByteCount"], name="expanded byte count"
            ),
            extraction_tree_digest=_wire_string(
                document["extractionTreeDigest"], name="extraction tree digest"
            ),
            evidence_version=_wire_int(
                document["evidenceVersion"], name="evidence version"
            ),
        )


class VerifiedWheelCandidate:
    """Opaque verified-tree capability; no quarantine pathname is exposed."""

    def __init__(
        self,
        *,
        acquired: AcquiredPackageCandidate,
        evidence: VerifiedWheelArtifactV1,
        requires_dist: tuple[str, ...],
        requires_python: str | None,
        provides_extra: tuple[str, ...],
    ) -> None:
        self._acquired = acquired
        self.evidence = evidence
        self.requires_dist = requires_dist
        self.requires_python = requires_python
        self.provides_extra = provides_extra
        self._closed = False

    def __repr__(self) -> str:
        return (
            "VerifiedWheelCandidate("
            f"operation_id={self.evidence.operation_id!r}, "
            f"node_id={self.evidence.node_id!r}, "
            f"fingerprint={self.evidence.fingerprint!r})"
        )

    @property
    def authenticated_envelope(self) -> AuthenticatedSourceEnvelopeV1 | None:
        return self._acquired.authenticated_envelope

    @property
    def acquisition_receipt(self) -> BoundedAcquisitionReceiptV1:
        return self._acquired.receipt

    def cleanup(self) -> None:
        if self._closed:
            return
        self._acquired.cleanup()
        self._closed = True

    def suspend_for_recovery(self) -> None:
        """Release process-local handles while preserving verified local state."""

        if self._closed:
            return
        self._acquired.suspend_for_recovery()
        self._closed = True


@dataclass(frozen=True, slots=True)
class _WheelIdentity:
    distribution: str
    version: str
    dist_info: str
    filename_tags: frozenset[str]


@dataclass(frozen=True, slots=True)
class _ArchiveEntry:
    name: str
    canonical_parts: tuple[str, ...]
    is_directory: bool
    compression: int
    crc32: int
    compressed_size: int
    expanded_size: int
    local_offset: int
    data_offset: int
    data_end: int


@dataclass(frozen=True, slots=True)
class _ContentEvidence:
    digests: Mapping[str, Mapping[str, bytes]]
    sizes: Mapping[str, int]
    metadata: Mapping[str, bytes]
    expanded_bytes: int


@dataclass(frozen=True, slots=True)
class _PackageMetadataClaims:
    requires_dist: tuple[str, ...]
    requires_python: str | None
    provides_extra: tuple[str, ...]


class PackageWheelVerifier:
    """Verify inert wheel bytes completely, then extract through a rooted writer."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic

    def verify(
        self,
        candidate: AcquiredPackageCandidate,
        *,
        wheel_filename: str,
        supported_tags: frozenset[str],
        budgets: PackageInspectionBudgetV1,
    ) -> VerifiedWheelCandidate:
        if not isinstance(candidate, AcquiredPackageCandidate):
            raise TypeError("Acquired Package candidate is required")
        if not isinstance(budgets, PackageInspectionBudgetV1):
            raise TypeError("Package inspection budgets are required")
        if not isinstance(supported_tags, frozenset) or not all(
            isinstance(tag, str) and tag for tag in supported_tags
        ):
            raise TypeError("Supported wheel tags must be a non-empty frozen set")
        if not supported_tags:
            raise ValueError("Supported wheel tags must not be empty")
        started_at = self._clock()
        try:
            identity = _parse_wheel_filename(wheel_filename, supported_tags)
            with candidate.open_for_verifier() as artifact:
                entries = _preflight_archive(
                    artifact,
                    artifact_size=candidate.receipt.actual_byte_count,
                    budgets=budgets,
                    started_at=started_at,
                    clock=self._clock,
                )
                required = _required_metadata_entries(entries, identity)
                content = _verify_archive_content(
                    artifact,
                    entries=entries,
                    required_metadata=required,
                    budgets=budgets,
                    started_at=started_at,
                    clock=self._clock,
                )
                metadata_claims = _verify_wheel_metadata(
                    identity,
                    wheel_bytes=content.metadata[required[0]],
                    package_bytes=content.metadata[required[1]],
                )
                _verify_record(
                    record_path=required[2],
                    record_bytes=content.metadata[required[2]],
                    entries=entries,
                    content=content,
                )
                _revalidate_artifact_identity(
                    artifact,
                    expected_digest=candidate.receipt.actual_byte_digest,
                    expected_size=candidate.receipt.actual_byte_count,
                    budgets=budgets,
                    started_at=started_at,
                    clock=self._clock,
                )
                tree_digest = _extract_verified_tree(
                    candidate,
                    artifact,
                    entries=entries,
                    content=content,
                    budgets=budgets,
                    started_at=started_at,
                    clock=self._clock,
                )
            evidence = VerifiedWheelArtifactV1(
                operation_id=candidate.receipt.operation_id,
                attempt_epoch=candidate.receipt.attempt_epoch,
                node_id=candidate.receipt.node_id,
                distribution=identity.distribution,
                version=identity.version,
                wheel_filename=wheel_filename,
                compatible_tags=tuple(sorted(identity.filename_tags & supported_tags)),
                artifact_digest=candidate.receipt.actual_byte_digest,
                artifact_size=candidate.receipt.actual_byte_count,
                wheel_metadata_digest=sha256(content.metadata[required[0]]).hexdigest(),
                package_metadata_digest=sha256(
                    content.metadata[required[1]]
                ).hexdigest(),
                record_digest=sha256(content.metadata[required[2]]).hexdigest(),
                record_verified=True,
                entry_count=len(entries),
                expanded_byte_count=content.expanded_bytes,
                extraction_tree_digest=tree_digest,
            )
            return VerifiedWheelCandidate(
                acquired=candidate,
                evidence=evidence,
                requires_dist=metadata_claims.requires_dist,
                requires_python=metadata_claims.requires_python,
                provides_extra=metadata_claims.provides_extra,
            )
        except PackageWheelVerificationError as rejection:
            _cleanup_rejected(candidate, rejection=rejection)
            raise
        except Exception:
            malformed_rejection = PackageWheelVerificationError(
                "Package archive structure is malformed",
                code="package_archive_malformed",
                stage="inspecting",
            )
            _cleanup_rejected(candidate, rejection=malformed_rejection)
            raise malformed_rejection from None


def _parse_wheel_filename(
    filename: str,
    supported_tags: frozenset[str],
) -> _WheelIdentity:
    if (
        not isinstance(filename, str)
        or not filename.endswith(".whl")
        or filename != os.path.basename(filename)
        or "/" in filename
        or "\\" in filename
    ):
        _reject_artifact_type()
    parts = filename[:-4].split("-")
    if len(parts) == 5:
        distribution, version, python_tag, abi_tag, platform_tag = parts
    elif len(parts) == 6:
        distribution, version, build, python_tag, abi_tag, platform_tag = parts
        if not build or not build[0].isdigit() or not _SAFE_WHEEL_PART.fullmatch(build):
            _reject_artifact_type()
    else:
        _reject_artifact_type()
    if (
        not distribution
        or not version
        or not _SAFE_WHEEL_PART.fullmatch(distribution)
        or not _SAFE_WHEEL_PART.fullmatch(version)
        or not all(
            _SAFE_TAG_PART.fullmatch(value)
            for value in (python_tag, abi_tag, platform_tag)
        )
    ):
        _reject_artifact_type()
    filename_tags = frozenset(
        f"{python}-{abi}-{platform}"
        for python in python_tag.split(".")
        for abi in abi_tag.split(".")
        for platform in platform_tag.split(".")
    )
    if not filename_tags & supported_tags:
        _reject_artifact_type()
    canonical_distribution = _canonical_distribution(distribution)
    canonical_version = version.replace("_", "-")
    return _WheelIdentity(
        distribution=canonical_distribution,
        version=canonical_version,
        dist_info=f"{distribution}-{version}.dist-info",
        filename_tags=filename_tags,
    )


def _preflight_archive(
    artifact: BinaryIO,
    *,
    artifact_size: int,
    budgets: PackageInspectionBudgetV1,
    started_at: float,
    clock: Callable[[], float],
) -> tuple[_ArchiveEntry, ...]:
    if artifact_size < _EOCD.size:
        _reject_malformed()
    artifact.seek(artifact_size - _EOCD.size)
    eocd = _read_exact(artifact, _EOCD.size)
    (
        signature,
        disk_number,
        central_disk,
        disk_entries,
        total_entries,
        central_size,
        central_offset,
        comment_length,
    ) = _EOCD.unpack(eocd)
    if signature != b"PK\x05\x06":
        _reject_malformed()
    if total_entries > budgets.max_entries:
        _reject_limit()
    if (
        disk_number != 0
        or central_disk != 0
        or disk_entries != total_entries
        or total_entries in {0, 0xFFFF}
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
        or comment_length != 0
        or central_offset + central_size + _EOCD.size != artifact_size
    ):
        _reject_malformed()
    entries: list[_ArchiveEntry] = []
    seen: dict[str, bool] = {}
    total_expanded = 0
    metadata_bytes = 0
    cursor = central_offset
    for _index in range(total_entries):
        _check_time(started_at, budgets, clock)
        if cursor + _CENTRAL.size > central_offset + central_size:
            _reject_malformed()
        artifact.seek(cursor)
        fixed = _read_exact(artifact, _CENTRAL.size)
        values = _CENTRAL.unpack(fixed)
        (
            central_signature,
            version_made,
            version_needed,
            flags,
            compression,
            modified_time,
            modified_date,
            crc32,
            compressed_size,
            expanded_size,
            name_length,
            extra_length,
            file_comment_length,
            start_disk,
            _internal_attributes,
            external_attributes,
            local_offset,
        ) = values
        variable_size = name_length + extra_length + file_comment_length
        cursor += _CENTRAL.size
        if (
            central_signature != b"PK\x01\x02"
            or name_length == 0
            or extra_length != 0
            or file_comment_length != 0
            or start_disk != 0
            or version_needed > 20
            or flags & ~0x800
            or compression not in _SUPPORTED_COMPRESSION
            or cursor + variable_size > central_offset + central_size
        ):
            _reject_malformed()
        raw_name = _read_exact(artifact, name_length)
        cursor += variable_size
        metadata_bytes += _CENTRAL.size + variable_size
        if metadata_bytes > budgets.max_metadata_bytes:
            _reject_limit()
        name = _decode_zip_name(raw_name, flags)
        canonical_parts, is_directory = _validate_archive_path(name, budgets)
        collision_key = "/".join(part.casefold() for part in canonical_parts)
        if collision_key in seen:
            _reject_collision()
        for depth in range(1, len(canonical_parts)):
            ancestor = "/".join(part.casefold() for part in canonical_parts[:depth])
            if ancestor in seen and not seen[ancestor]:
                _reject_collision()
        if not is_directory:
            prefix = collision_key + "/"
            if any(existing.startswith(prefix) for existing in seen):
                _reject_collision()
        seen[collision_key] = is_directory
        _validate_entry_type(
            name=name,
            is_directory=is_directory,
            version_made=version_made,
            external_attributes=external_attributes,
        )
        if (
            expanded_size > budgets.max_entry_expanded_bytes
            or total_expanded + expanded_size > budgets.max_total_expanded_bytes
        ):
            _reject_limit()
        total_expanded += expanded_size
        artifact.seek(local_offset)
        local = _read_exact(artifact, _LOCAL.size)
        (
            local_signature,
            local_version,
            local_flags,
            local_compression,
            local_time,
            local_date,
            local_crc32,
            local_compressed_size,
            local_expanded_size,
            local_name_length,
            local_extra_length,
        ) = _LOCAL.unpack(local)
        local_name = _read_exact(artifact, local_name_length)
        if (
            local_signature != b"PK\x03\x04"
            or local_version != version_needed
            or local_flags != flags
            or local_compression != compression
            or local_time != modified_time
            or local_date != modified_date
            or local_crc32 != crc32
            or local_compressed_size != compressed_size
            or local_expanded_size != expanded_size
            or local_name != raw_name
            or local_extra_length != 0
        ):
            _reject_malformed()
        data_offset = local_offset + _LOCAL.size + local_name_length
        data_end = data_offset + compressed_size
        if data_end > central_offset:
            _reject_malformed()
        entries.append(
            _ArchiveEntry(
                name=name,
                canonical_parts=canonical_parts,
                is_directory=is_directory,
                compression=compression,
                crc32=crc32,
                compressed_size=compressed_size,
                expanded_size=expanded_size,
                local_offset=local_offset,
                data_offset=data_offset,
                data_end=data_end,
            )
        )
    if cursor != central_offset + central_size:
        _reject_malformed()
    expected_offset = 0
    for entry in sorted(entries, key=lambda value: value.local_offset):
        if entry.local_offset != expected_offset:
            _reject_malformed()
        expected_offset = entry.data_end
    if expected_offset != central_offset:
        _reject_malformed()
    return tuple(entries)


def _required_metadata_entries(
    entries: tuple[_ArchiveEntry, ...],
    identity: _WheelIdentity,
) -> tuple[str, str, str]:
    wheel_path = f"{identity.dist_info}/WHEEL"
    metadata_path = f"{identity.dist_info}/METADATA"
    record_path = f"{identity.dist_info}/RECORD"
    names = {entry.name for entry in entries if not entry.is_directory}
    if not {wheel_path, metadata_path, record_path} <= names:
        _reject_wheel_metadata()
    for entry in entries:
        for component in entry.name.rstrip("/").split("/"):
            if component.endswith(".dist-info") and component != identity.dist_info:
                _reject_wheel_metadata()
    return wheel_path, metadata_path, record_path


def _verify_archive_content(
    artifact: BinaryIO,
    *,
    entries: tuple[_ArchiveEntry, ...],
    required_metadata: tuple[str, str, str],
    budgets: PackageInspectionBudgetV1,
    started_at: float,
    clock: Callable[[], float],
) -> _ContentEvidence:
    artifact.seek(0)
    digests: dict[str, dict[str, bytes]] = {}
    sizes: dict[str, int] = {}
    metadata: dict[str, bytes] = {}
    expanded_total = 0
    try:
        with zipfile.ZipFile(artifact, "r") as archive:
            infos = archive.infolist()
            if len(infos) != len(entries):
                _reject_malformed()
            raw_by_name = {entry.name: entry for entry in entries}
            if len(raw_by_name) != len(entries):
                _reject_collision()
            for info in infos:
                _check_time(started_at, budgets, clock)
                entry = raw_by_name.get(info.filename)
                if (
                    entry is None
                    or info.compress_type != entry.compression
                    or info.CRC != entry.crc32
                    or info.compress_size != entry.compressed_size
                    or info.file_size != entry.expanded_size
                    or info.is_dir() != entry.is_directory
                ):
                    _reject_malformed()
                if entry.is_directory:
                    continue
                hashers = {name: new_digest(name) for name in _SUPPORTED_HASHES}
                byte_count = 0
                captured = io.BytesIO() if entry.name in required_metadata else None
                with archive.open(info, "r") as source:
                    while chunk := source.read(64 * 1024):
                        _check_time(started_at, budgets, clock)
                        byte_count += len(chunk)
                        expanded_total += len(chunk)
                        if (
                            byte_count > budgets.max_entry_expanded_bytes
                            or expanded_total > budgets.max_total_expanded_bytes
                            or byte_count > entry.expanded_size
                        ):
                            _reject_limit()
                        for hasher in hashers.values():
                            hasher.update(chunk)
                        if captured is not None:
                            if (
                                captured.tell() + len(chunk)
                                > budgets.max_metadata_bytes
                            ):
                                _reject_limit()
                            captured.write(chunk)
                if byte_count != entry.expanded_size:
                    _reject_malformed()
                sizes[entry.name] = byte_count
                digests[entry.name] = {
                    name: hasher.digest() for name, hasher in hashers.items()
                }
                if captured is not None:
                    metadata[entry.name] = captured.getvalue()
    except PackageWheelVerificationError:
        raise
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile):
        _reject_malformed()
    if set(metadata) != set(required_metadata):
        _reject_wheel_metadata()
    if sum(map(len, metadata.values())) > budgets.max_metadata_bytes:
        _reject_limit()
    return _ContentEvidence(
        digests=digests,
        sizes=sizes,
        metadata=metadata,
        expanded_bytes=expanded_total,
    )


def _verify_wheel_metadata(
    identity: _WheelIdentity,
    *,
    wheel_bytes: bytes,
    package_bytes: bytes,
) -> _PackageMetadataClaims:
    try:
        wheel = BytesParser(policy=compat32).parsebytes(wheel_bytes, headersonly=True)
        package = BytesParser(policy=compat32).parsebytes(
            package_bytes, headersonly=True
        )
    except (TypeError, ValueError):
        _reject_wheel_metadata()
    wheel_version = _one_header(wheel.get_all("Wheel-Version"))
    root_is_purelib = _one_header(wheel.get_all("Root-Is-Purelib"))
    wheel_tags = frozenset(wheel.get_all("Tag", []))
    if (
        wheel_version not in {"1.0", "1.1"}
        or root_is_purelib.lower() not in {"true", "false"}
        or wheel_tags != identity.filename_tags
    ):
        _reject_wheel_metadata()
    metadata_version = _one_header(package.get_all("Metadata-Version"))
    name = _one_header(package.get_all("Name"))
    version = _one_header(package.get_all("Version"))
    if (
        metadata_version not in {"1.2", "2.0", "2.1", "2.2", "2.3", "2.4"}
        or _canonical_distribution(name) != identity.distribution
        or version.replace("_", "-") != identity.version
    ):
        _reject_wheel_metadata()
    requires_dist = _normalized_metadata_headers(package.get_all("Requires-Dist", []))
    requires_python_values = package.get_all("Requires-Python")
    requires_python = (
        None if requires_python_values is None else _one_header(requires_python_values)
    )
    provides_extra = tuple(
        sorted(
            _canonical_distribution(value)
            for value in _normalized_metadata_headers(
                package.get_all("Provides-Extra", [])
            )
        )
    )
    if len(provides_extra) != len(set(provides_extra)):
        _reject_wheel_metadata()
    return _PackageMetadataClaims(
        requires_dist=requires_dist,
        requires_python=requires_python,
        provides_extra=provides_extra,
    )


def _normalized_metadata_headers(values: list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or "\x00" in value:
            _reject_wheel_metadata()
        item = re.sub(r"\r?\n[ \t]+", " ", value).strip()
        if not item or "\r" in item or "\n" in item:
            _reject_wheel_metadata()
        normalized.append(item)
    return tuple(sorted(normalized))


def _verify_record(
    *,
    record_path: str,
    record_bytes: bytes,
    entries: tuple[_ArchiveEntry, ...],
    content: _ContentEvidence,
) -> None:
    try:
        text = record_bytes.decode("utf-8", errors="strict")
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeError, csv.Error):
        _reject_record()
    expected_files = {entry.name for entry in entries if not entry.is_directory}
    observed: set[str] = set()
    blank_allowed = {record_path, f"{record_path}.jws", f"{record_path}.p7s"}
    for row in rows:
        if len(row) != 3:
            _reject_record()
        path, encoded_hash, encoded_size = row
        if path not in expected_files or path in observed:
            _reject_record()
        observed.add(path)
        if not encoded_hash and not encoded_size:
            if path not in blank_allowed:
                _reject_record()
            continue
        if not encoded_hash or not encoded_size or not encoded_size.isascii():
            _reject_record()
        if not encoded_size.isdecimal() or str(int(encoded_size)) != encoded_size:
            _reject_record()
        algorithm, separator, encoded = encoded_hash.partition("=")
        if separator != "=" or algorithm not in _SUPPORTED_HASHES or not encoded:
            _reject_record()
        if "=" in encoded:
            _reject_record()
        try:
            padding = "=" * (-len(encoded) % 4)
            expected_digest = base64.b64decode(
                encoded + padding,
                altchars=b"-_",
                validate=True,
            )
        except (ValueError, TypeError):
            _reject_record()
        if (
            content.sizes.get(path) != int(encoded_size)
            or content.digests.get(path, {}).get(algorithm) != expected_digest
        ):
            _reject_record()
    if observed != expected_files:
        _reject_record()


def _extract_verified_tree(
    candidate: AcquiredPackageCandidate,
    artifact: BinaryIO,
    *,
    entries: tuple[_ArchiveEntry, ...],
    content: _ContentEvidence,
    budgets: PackageInspectionBudgetV1,
    started_at: float,
    clock: Callable[[], float],
) -> str:
    writer = candidate._attempt._begin_extraction()
    tree_records: list[dict[str, object]] = []
    try:
        artifact.seek(0)
        with zipfile.ZipFile(artifact, "r") as archive:
            infos = {info.filename: info for info in archive.infolist()}
            for entry in sorted(entries, key=lambda value: value.canonical_parts):
                _check_time(started_at, budgets, clock)
                if entry.is_directory:
                    writer._ensure_directory(entry.canonical_parts)
                    continue
                handle = writer._open_file(entry.canonical_parts)
                digest = sha256()
                byte_count = 0
                try:
                    with archive.open(infos[entry.name], "r") as source:
                        while chunk := source.read(64 * 1024):
                            _check_time(started_at, budgets, clock)
                            byte_count += len(chunk)
                            if byte_count > entry.expanded_size:
                                _reject_limit(stage="extracted")
                            handle.write(chunk)
                            digest.update(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                finally:
                    handle.close()
                if (
                    byte_count != content.sizes[entry.name]
                    or digest.digest() != content.digests[entry.name]["sha256"]
                ):
                    raise PackageWheelVerificationError(
                        "Verified archive content changed during extraction",
                        code="package_artifact_identity_changed",
                        stage="extracted",
                        consumed_bytes=byte_count,
                    )
                tree_records.append(
                    {
                        "digest": digest.hexdigest(),
                        "path": "/".join(entry.canonical_parts),
                        "size": byte_count,
                        "type": "regular_file",
                    }
                )
        writer._finish()
    except Exception:
        writer._abort()
        raise
    return sha256(canonical_json_bytes(tree_records)).hexdigest()


def _revalidate_artifact_identity(
    artifact: BinaryIO,
    *,
    expected_digest: str,
    expected_size: int,
    budgets: PackageInspectionBudgetV1,
    started_at: float,
    clock: Callable[[], float],
) -> None:
    artifact.seek(0)
    digest = sha256()
    byte_count = 0
    while chunk := artifact.read(64 * 1024):
        _check_time(started_at, budgets, clock)
        byte_count += len(chunk)
        digest.update(chunk)
    if byte_count != expected_size or digest.hexdigest() != expected_digest:
        raise PackageWheelVerificationError(
            "Acquired artifact identity changed during verification",
            code="package_artifact_identity_changed",
            stage="inspecting",
            consumed_bytes=byte_count,
        )


def _validate_archive_path(
    name: str,
    budgets: PackageInspectionBudgetV1,
) -> tuple[tuple[str, ...], bool]:
    if (
        not name
        or "\x00" in name
        or "\\" in name
        or name.startswith("/")
        or name.startswith("//")
        or "//" in name
    ):
        _reject_path()
    is_directory = name.endswith("/")
    raw = name[:-1] if is_directory else name
    if not raw or raw.endswith("/"):
        _reject_path()
    raw_parts = raw.split("/")
    if len(raw_parts) > budgets.max_path_components:
        _reject_limit()
    canonical: list[str] = []
    for index, component in enumerate(raw_parts):
        normalized = unicodedata.normalize("NFC", component)
        if (
            not normalized
            or normalized in {".", ".."}
            or normalized.endswith((".", " "))
            or ":" in normalized
            or (index == 0 and re.match(r"[A-Za-z]:", normalized))
            or normalized.split(".", 1)[0].casefold() in _WINDOWS_RESERVED
        ):
            _reject_path()
        if len(normalized) > budgets.max_path_component_length:
            _reject_limit()
        canonical.append(normalized)
    canonical_path = "/".join(canonical)
    if len(canonical_path) > budgets.max_path_length:
        _reject_limit()
    return tuple(canonical), is_directory


def _validate_entry_type(
    *,
    name: str,
    is_directory: bool,
    version_made: int,
    external_attributes: int,
) -> None:
    create_system = version_made >> 8
    if external_attributes & 0x400:
        _reject_entry_type()
    if create_system == 3:
        mode = external_attributes >> 16 & 0xFFFF
        file_type = stat.S_IFMT(mode)
        permitted = stat.S_IFDIR if is_directory else stat.S_IFREG
        if file_type not in {0, permitted}:
            _reject_entry_type()
    if name.endswith("/") != is_directory:
        _reject_entry_type()


def _decode_zip_name(raw_name: bytes, flags: int) -> str:
    try:
        return raw_name.decode("utf-8" if flags & 0x800 else "cp437", errors="strict")
    except UnicodeError:
        _reject_malformed()


def _read_exact(handle: BinaryIO, size: int) -> bytes:
    value = handle.read(size)
    if len(value) != size:
        raise EOFError
    return value


def _one_header(values: list[str] | None) -> str:
    if values is None or len(values) != 1 or not values[0].strip():
        _reject_wheel_metadata()
    value = values[0].strip()
    if "\x00" in value or "\r" in value or "\n" in value:
        _reject_wheel_metadata()
    return value


def _canonical_distribution(value: str) -> str:
    result = re.sub(r"[-_.]+", "-", value).lower()
    if not result or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", result):
        _reject_wheel_metadata()
    return result


def _check_time(
    started_at: float,
    budgets: PackageInspectionBudgetV1,
    clock: Callable[[], float],
) -> None:
    if (clock() - started_at) * 1000 > budgets.max_wall_time_ms:
        raise PackageWheelVerificationError(
            "Package inspection exceeded the wall-clock budget",
            code="package_resource_limit_exceeded",
            stage="inspecting",
        )


def _cleanup_rejected(
    candidate: AcquiredPackageCandidate,
    *,
    rejection: PackageWheelVerificationError,
) -> None:
    try:
        candidate.cleanup()
    except OSError:
        raise PackageWheelVerificationError(
            "Rejected Package quarantine requires bounded owner cleanup",
            code="package_quarantine_cleanup_retryable",
            stage=rejection.stage,
            rejection_code=rejection.code,
            rejection_stage=rejection.stage,
        ) from None


def _reject_malformed() -> NoReturn:
    raise PackageWheelVerificationError(
        "Package archive structure is malformed",
        code="package_archive_malformed",
        stage="inspecting",
    )


def _reject_path() -> NoReturn:
    raise PackageWheelVerificationError(
        "Package archive path is not portable and rooted",
        code="package_archive_path_rejected",
        stage="inspecting",
    )


def _reject_collision() -> NoReturn:
    raise PackageWheelVerificationError(
        "Package archive names collide after platform normalization",
        code="package_archive_name_collision",
        stage="inspecting",
    )


def _reject_entry_type() -> NoReturn:
    raise PackageWheelVerificationError(
        "Package archive entry is not a regular file or directory",
        code="package_archive_entry_type_rejected",
        stage="inspecting",
    )


def _reject_limit(*, stage: InspectionStage = "inspecting") -> NoReturn:
    raise PackageWheelVerificationError(
        "Package inspection exceeded a resource budget",
        code="package_resource_limit_exceeded",
        stage=stage,
    )


def _reject_artifact_type() -> NoReturn:
    raise PackageWheelVerificationError(
        "Package artifact is not a compatible wheel",
        code="package_artifact_type_rejected",
        stage="inspecting",
    )


def _reject_wheel_metadata() -> NoReturn:
    raise PackageWheelVerificationError(
        "Wheel metadata does not match the requested artifact",
        code="package_wheel_metadata_invalid",
        stage="inspecting",
    )


def _reject_record() -> NoReturn:
    raise PackageWheelVerificationError(
        "Wheel RECORD does not prove the complete artifact set",
        code="package_wheel_record_invalid",
        stage="extracted",
    )


def _require_positive(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_nonnegative(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _exact_dict(
    value: object,
    *,
    fields: set[str],
    name: str,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    document = dict(value)
    if set(document) != fields:
        raise ValueError(f"{name} fields do not match the versioned schema")
    return cast(dict[str, object], document)


def _wire_int(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return value


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string")
    return value
