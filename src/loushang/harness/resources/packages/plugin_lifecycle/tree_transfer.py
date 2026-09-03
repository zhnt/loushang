"""Dark verified-tree transfer contracts for PLC9B3e-3c.

The Package quarantine owner keeps every physical source path and handle. Store
owners keep every writable destination root and native handle. The only shared
data is a credential-free manifest of already verified logical regular files,
plus short-lived sink capabilities that never cross a durable boundary.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, Protocol, cast

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

if TYPE_CHECKING:
    from loushang.harness.resources.packages.plugin_lifecycle.staging import (
        PackageArtifactStagingReceiptV1,
        PackageArtifactStagingRequestV1,
    )
    from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
        VerifiedWheelArtifactV1,
        VerifiedWheelCandidate,
    )


PACKAGE_VERIFIED_TREE_ENTRY_VERSION = 1
PACKAGE_VERIFIED_TREE_MANIFEST_VERSION = 1

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_WINDOWS_RESERVED = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


@dataclass(frozen=True, slots=True)
class PackageVerifiedTreeEntryV1:
    """One portable logical regular file; never a host filesystem path."""

    logical_path: str
    content_digest: str
    byte_count: int
    entry_version: int = PACKAGE_VERIFIED_TREE_ENTRY_VERSION

    def __post_init__(self) -> None:
        _require_logical_path(self.logical_path)
        _require_sha256(self.content_digest, name="verified file content digest")
        _require_nonnegative(self.byte_count, name="verified file byte count")
        if self.entry_version != PACKAGE_VERIFIED_TREE_ENTRY_VERSION:
            raise ValueError("Unsupported Package verified-tree entry")

    def to_dict(self) -> dict[str, object]:
        return {
            "byteCount": self.byte_count,
            "contentDigest": self.content_digest,
            "entryVersion": self.entry_version,
            "logicalPath": self.logical_path,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageVerifiedTreeEntryV1:
        document = _exact_dict(
            value,
            fields={
                "byteCount",
                "contentDigest",
                "entryVersion",
                "logicalPath",
            },
            name="Package verified-tree entry",
        )
        return cls(
            logical_path=_wire_string(
                document["logicalPath"], name="verified logical path"
            ),
            content_digest=_wire_string(
                document["contentDigest"], name="verified content digest"
            ),
            byte_count=_wire_int(document["byteCount"], name="verified byte count"),
            entry_version=_wire_int(
                document["entryVersion"], name="verified-tree entry version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageVerifiedTreeManifestV1:
    """Files-only transfer identity bound to one verified Wheel evidence value."""

    manifest_id: str
    operation_id: str
    attempt_epoch: int
    node_id: str
    distribution: str
    version: str
    wheel_evidence_fingerprint: str
    artifact_digest: str
    extraction_tree_digest: str
    total_byte_count: int
    entries: tuple[PackageVerifiedTreeEntryV1, ...]
    manifest_version: int = PACKAGE_VERIFIED_TREE_MANIFEST_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.manifest_id, name="verified-tree manifest id")
        for value, name in (
            (self.operation_id, "Package operation identity"),
            (self.node_id, "Package node identity"),
            (self.distribution, "Package distribution"),
            (self.version, "Package version"),
        ):
            _require_nonsecret_text(value, name=name)
        _require_positive(self.attempt_epoch, name="Package attempt epoch")
        for value, name in (
            (self.wheel_evidence_fingerprint, "Wheel evidence fingerprint"),
            (self.artifact_digest, "artifact digest"),
            (self.extraction_tree_digest, "extraction tree digest"),
        ):
            _require_sha256(value, name=name)
        _require_nonnegative(
            self.total_byte_count,
            name="verified-tree total byte count",
        )
        _require_canonical_entries(self.entries)
        if sum(entry.byte_count for entry in self.entries) != self.total_byte_count:
            raise ValueError("Verified-tree total byte count changed")
        if verified_tree_digest(self.entries) != self.extraction_tree_digest:
            raise ValueError("Verified-tree extraction tree digest changed")
        if self.manifest_version != PACKAGE_VERIFIED_TREE_MANIFEST_VERSION:
            raise ValueError("Unsupported Package verified-tree manifest")
        if self.manifest_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package verified-tree manifest id does not match")

    @classmethod
    def create(
        cls,
        evidence: VerifiedWheelArtifactV1,
        *,
        entries: tuple[PackageVerifiedTreeEntryV1, ...],
    ) -> PackageVerifiedTreeManifestV1:
        from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
            VerifiedWheelArtifactV1,
        )

        if not isinstance(evidence, VerifiedWheelArtifactV1):
            raise TypeError("Verified Wheel evidence is required")
        _require_canonical_entries(entries)
        total_byte_count = sum(entry.byte_count for entry in entries)
        if total_byte_count != evidence.expanded_byte_count:
            raise ValueError("Verified-tree byte total changed from Wheel evidence")
        if len(entries) > evidence.entry_count:
            raise ValueError("Verified-tree file count exceeds Wheel evidence")
        if verified_tree_digest(entries) != evidence.extraction_tree_digest:
            raise ValueError("Verified-tree tree digest changed from Wheel evidence")
        values = _manifest_identity_dict(
            operation_id=evidence.operation_id,
            attempt_epoch=evidence.attempt_epoch,
            node_id=evidence.node_id,
            distribution=evidence.distribution,
            version=evidence.version,
            wheel_evidence_fingerprint=evidence.fingerprint,
            artifact_digest=evidence.artifact_digest,
            extraction_tree_digest=evidence.extraction_tree_digest,
            total_byte_count=total_byte_count,
            entries=entries,
            manifest_version=PACKAGE_VERIFIED_TREE_MANIFEST_VERSION,
        )
        return cls(
            manifest_id=_fingerprint(values),
            operation_id=evidence.operation_id,
            attempt_epoch=evidence.attempt_epoch,
            node_id=evidence.node_id,
            distribution=evidence.distribution,
            version=evidence.version,
            wheel_evidence_fingerprint=evidence.fingerprint,
            artifact_digest=evidence.artifact_digest,
            extraction_tree_digest=evidence.extraction_tree_digest,
            total_byte_count=total_byte_count,
            entries=entries,
        )

    def validate_evidence(self, evidence: VerifiedWheelArtifactV1) -> None:
        """Reject a manifest detached from the candidate's exact Wheel proof."""

        from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
            VerifiedWheelArtifactV1,
        )

        if not isinstance(evidence, VerifiedWheelArtifactV1):
            raise TypeError("Verified Wheel evidence is required")
        if (
            self.operation_id != evidence.operation_id
            or self.attempt_epoch != evidence.attempt_epoch
            or self.node_id != evidence.node_id
            or self.distribution != evidence.distribution
            or self.version != evidence.version
            or self.wheel_evidence_fingerprint != evidence.fingerprint
            or self.artifact_digest != evidence.artifact_digest
            or self.extraction_tree_digest != evidence.extraction_tree_digest
            or self.total_byte_count != evidence.expanded_byte_count
            or len(self.entries) > evidence.entry_count
        ):
            raise ValueError("Verified-tree manifest changed from Wheel evidence")

    def _identity_dict(self) -> dict[str, object]:
        return _manifest_identity_dict(
            operation_id=self.operation_id,
            attempt_epoch=self.attempt_epoch,
            node_id=self.node_id,
            distribution=self.distribution,
            version=self.version,
            wheel_evidence_fingerprint=self.wheel_evidence_fingerprint,
            artifact_digest=self.artifact_digest,
            extraction_tree_digest=self.extraction_tree_digest,
            total_byte_count=self.total_byte_count,
            entries=self.entries,
            manifest_version=self.manifest_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {"manifestId": self.manifest_id, **self._identity_dict()}

    @classmethod
    def from_dict(cls, value: object) -> PackageVerifiedTreeManifestV1:
        document = _exact_dict(
            value,
            fields={
                "artifactDigest",
                "attemptEpoch",
                "distribution",
                "entries",
                "extractionTreeDigest",
                "manifestId",
                "manifestVersion",
                "nodeId",
                "operationId",
                "totalByteCount",
                "version",
                "wheelEvidenceFingerprint",
            },
            name="Package verified-tree manifest",
        )
        raw_entries = document["entries"]
        if not isinstance(raw_entries, list):
            raise TypeError("Verified-tree manifest entries must be an array")
        return cls(
            manifest_id=_wire_string(document["manifestId"], name="manifest id"),
            operation_id=_wire_string(
                document["operationId"], name="Package operation identity"
            ),
            attempt_epoch=_wire_int(document["attemptEpoch"], name="attempt epoch"),
            node_id=_wire_string(document["nodeId"], name="Package node identity"),
            distribution=_wire_string(
                document["distribution"], name="Package distribution"
            ),
            version=_wire_string(document["version"], name="Package version"),
            wheel_evidence_fingerprint=_wire_string(
                document["wheelEvidenceFingerprint"],
                name="Wheel evidence fingerprint",
            ),
            artifact_digest=_wire_string(
                document["artifactDigest"], name="artifact digest"
            ),
            extraction_tree_digest=_wire_string(
                document["extractionTreeDigest"], name="extraction tree digest"
            ),
            total_byte_count=_wire_int(
                document["totalByteCount"], name="verified-tree total byte count"
            ),
            entries=tuple(
                PackageVerifiedTreeEntryV1.from_dict(entry) for entry in raw_entries
            ),
            manifest_version=_wire_int(
                document["manifestVersion"], name="verified-tree manifest version"
            ),
        )


class PackageVerifiedTreeFileSinkPort(Protocol):
    """Store-owned bounded writer for exactly one declared regular file."""

    def write(self, chunk: bytes) -> None: ...

    def finish(self) -> None: ...

    def abort(self) -> None: ...


class PackageVerifiedTreeSinkPort(Protocol):
    """One short-lived rooted Store sink already bound to request and manifest."""

    def open_file(
        self,
        entry: PackageVerifiedTreeEntryV1,
    ) -> AbstractContextManager[PackageVerifiedTreeFileSinkPort]: ...

    def finish(self) -> PackageArtifactStagingReceiptV1: ...

    def abort(self) -> None: ...


class PackageVerifiedTreeTransferPort(Protocol):
    """Quarantine owner that streams one candidate without exposing its path."""

    def transfer(
        self,
        request: PackageArtifactStagingRequestV1,
        candidate: VerifiedWheelCandidate,
        sink: PackageVerifiedTreeSinkPort,
    ) -> PackageArtifactStagingReceiptV1: ...


class PackageDependencyMaterializationRootPort(Protocol):
    """Dependency Store authority; cannot open the designated Plugin root."""

    def open_dependency_sink(
        self,
        request: PackageArtifactStagingRequestV1,
        manifest: PackageVerifiedTreeManifestV1,
    ) -> AbstractContextManager[PackageVerifiedTreeSinkPort]: ...


class PackagePluginRootMaterializationRootPort(Protocol):
    """Plugin Store authority; can open only an authority-designated root sink."""

    def open_root_sink(
        self,
        request: PackageArtifactStagingRequestV1,
        manifest: PackageVerifiedTreeManifestV1,
    ) -> AbstractContextManager[PackageVerifiedTreeSinkPort]: ...


class PackagePhysicalStagingError(RuntimeError):
    """Secret-free physical transfer or Store-root rejection."""

    def __init__(self, message: str, *, code: str) -> None:
        if code not in {
            "package_artifact_identity_changed",
            "package_publication_collision",
            "package_publication_root_untrusted",
        }:
            raise ValueError("Unsupported Package physical staging error code")
        super().__init__(message)
        self.code = code
        self.stage = "staging"
        self.retryable = False


class PackageVerifiedTreeTransferOwner:
    """Stream an exact live verified tree into one already-authorized Store sink."""

    def __init__(self, *, chunk_size: int = 64 * 1024) -> None:
        if not isinstance(chunk_size, int) or isinstance(chunk_size, bool):
            raise TypeError("Verified-tree transfer chunk size must be an integer")
        if chunk_size < 1 or chunk_size > 1024 * 1024:
            raise ValueError("Verified-tree transfer chunk size is out of bounds")
        self._chunk_size = chunk_size

    def transfer(
        self,
        request: PackageArtifactStagingRequestV1,
        candidate: VerifiedWheelCandidate,
        sink: PackageVerifiedTreeSinkPort,
    ) -> PackageArtifactStagingReceiptV1:
        from loushang.harness.resources.packages.plugin_lifecycle.staging import (
            PackageArtifactStagingReceiptV1,
            PackageArtifactStagingRequestV1,
        )
        from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
            VerifiedWheelCandidate,
        )

        if not isinstance(request, PackageArtifactStagingRequestV1):
            raise TypeError("Package artifact staging request is required")
        if not isinstance(candidate, VerifiedWheelCandidate):
            raise TypeError("Verified Wheel candidate is required")
        _validate_staging_identity(request, candidate)
        manifest = candidate.transfer_manifest
        try:
            for entry in manifest.entries:
                digest = sha256()
                byte_count = 0
                with candidate._open_verified_tree_file(entry) as source:
                    with sink.open_file(entry) as destination:
                        while chunk := source.read(self._chunk_size):
                            if not isinstance(chunk, bytes):
                                destination.abort()
                                raise OSError("Verified source returned non-byte data")
                            byte_count += len(chunk)
                            if byte_count > entry.byte_count:
                                destination.abort()
                                raise OSError("Verified source file size changed")
                            digest.update(chunk)
                            destination.write(chunk)
                        if (
                            byte_count != entry.byte_count
                            or digest.hexdigest() != entry.content_digest
                        ):
                            destination.abort()
                            raise OSError("Verified source file identity changed")
                        destination.finish()
            receipt = sink.finish()
        except Exception as error:
            sink.abort()
            if getattr(error, "code", None) in {
                "package_publication_root_untrusted",
                "package_publication_collision",
                "package_artifact_identity_changed",
            }:
                raise
            raise PackagePhysicalStagingError(
                "Verified Package tree changed during materialization",
                code="package_artifact_identity_changed",
            ) from None
        if (
            not isinstance(receipt, PackageArtifactStagingReceiptV1)
            or receipt.staging_request != request
        ):
            sink.abort()
            raise TypeError("Store returned an invalid Package staging receipt")
        _validate_receipt_identity(receipt, manifest)
        return receipt


def _validate_staging_identity(
    request: PackageArtifactStagingRequestV1,
    candidate: VerifiedWheelCandidate,
) -> None:
    evidence = candidate.evidence
    manifest = candidate.transfer_manifest
    manifest.validate_evidence(evidence)
    node = request.plan_node
    if (
        request.operation_id != evidence.operation_id
        or request.attempt_epoch != evidence.attempt_epoch
        or request.node_id != evidence.node_id
        or node.distribution != evidence.distribution
        or node.version != evidence.version
        or node.wheel_evidence_fingerprint != evidence.fingerprint
        or node.artifact_digest != evidence.artifact_digest
        or node.extraction_tree_digest != evidence.extraction_tree_digest
    ):
        raise PackagePhysicalStagingError(
            "Package staging request changed verified artifact identity",
            code="package_artifact_identity_changed",
        )


def _validate_receipt_identity(
    receipt: PackageArtifactStagingReceiptV1,
    manifest: PackageVerifiedTreeManifestV1,
) -> None:
    stable_ref = receipt.stable_ref
    if (
        stable_ref.distribution != manifest.distribution
        or stable_ref.version != manifest.version
        or stable_ref.artifact_digest != manifest.artifact_digest
        or stable_ref.extraction_tree_digest != manifest.extraction_tree_digest
    ):
        raise PackagePhysicalStagingError(
            "Store receipt changed verified artifact identity",
            code="package_publication_collision",
        )


def verified_tree_digest(
    entries: tuple[PackageVerifiedTreeEntryV1, ...],
) -> str:
    """Return the accepted files-only Wheel extraction-tree digest."""

    _require_canonical_entries(entries)
    records = [
        {
            "digest": entry.content_digest,
            "path": entry.logical_path,
            "size": entry.byte_count,
            "type": "regular_file",
        }
        for entry in entries
    ]
    return sha256(canonical_json_bytes(records)).hexdigest()


def _manifest_identity_dict(
    *,
    operation_id: str,
    attempt_epoch: int,
    node_id: str,
    distribution: str,
    version: str,
    wheel_evidence_fingerprint: str,
    artifact_digest: str,
    extraction_tree_digest: str,
    total_byte_count: int,
    entries: tuple[PackageVerifiedTreeEntryV1, ...],
    manifest_version: int,
) -> dict[str, object]:
    return {
        "artifactDigest": artifact_digest,
        "attemptEpoch": attempt_epoch,
        "distribution": distribution,
        "entries": [entry.to_dict() for entry in entries],
        "extractionTreeDigest": extraction_tree_digest,
        "manifestVersion": manifest_version,
        "nodeId": node_id,
        "operationId": operation_id,
        "totalByteCount": total_byte_count,
        "version": version,
        "wheelEvidenceFingerprint": wheel_evidence_fingerprint,
    }


def _fingerprint(value: Mapping[str, object]) -> str:
    return sha256(canonical_json_bytes(dict(value))).hexdigest()


def _require_logical_path(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or unicodedata.normalize("NFC", value) != value
    ):
        raise ValueError("Verified logical path must be non-empty normalized text")
    if (
        "\x00" in value
        or "\\" in value
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
    ):
        raise ValueError("Verified logical path is not portable")
    parts = value.split("/")
    for part in parts:
        stem = part.split(".", 1)[0].casefold()
        if (
            not part
            or part in {".", ".."}
            or part.endswith((".", " "))
            or ":" in part
            or stem in _WINDOWS_RESERVED
        ):
            raise ValueError("Verified logical path is not portable")


def _logical_path_sort_key(value: str) -> tuple[str, ...]:
    return tuple(value.split("/"))


def _require_canonical_entries(
    entries: tuple[PackageVerifiedTreeEntryV1, ...],
) -> None:
    if (
        not isinstance(entries, tuple)
        or not entries
        or not all(isinstance(entry, PackageVerifiedTreeEntryV1) for entry in entries)
    ):
        raise TypeError("Verified-tree manifest requires a non-empty typed entry tuple")
    paths = tuple(entry.logical_path for entry in entries)
    if paths != tuple(sorted(paths, key=_logical_path_sort_key)) or len(
        set(paths)
    ) != len(paths):
        raise ValueError("Verified-tree entries must be canonical and unique")


def _require_nonsecret_text(value: str, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\r" in value
        or "\n" in value
    ):
        raise ValueError(f"{name} must be non-empty text")


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_positive(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_nonnegative(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


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
