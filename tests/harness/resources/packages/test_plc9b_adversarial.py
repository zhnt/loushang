from __future__ import annotations

import base64
import csv
import inspect
import io
import os
import stat
import struct
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleJournal,
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AcquiredPackageCandidate,
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionSinkPort,
    PackageAcquisitionBudgetV1,
    PackageAcquisitionError,
    PackageAcquisitionOwner,
    PackageAcquisitionRequestV1,
    PackageAuthenticatedSourceEvidenceV1,
    PackageQuarantineStore,
    SourceAdapterResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.cleanup import (
    PackageQuarantineCleanupJournal,
    PackageQuarantineCleanupOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    PackageClosureBudgetV1,
    PackageClosureVerifier,
    PackageResolutionEnvironmentV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_journal import (
    PackageClosureResolutionBasisV1,
    PackageClosureResolutionJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    PackageDependencySelectionRequestV1,
    PackageDependencySelectionV1,
    PackageRecursiveClosureOwner,
    PackageRecursiveClosureRequestV2,
    VerifiedPackageClosureCandidate,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_runtime import (
    PackageClosureExecutionRequestV2,
    PackageClosureLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.phase_evidence import (
    PackageArtifactEvidenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRequestV1,
    PackageLifecycleStatusV1,
    PluginBoundPackageClassificationV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.runtime import (
    PackageArtifactExecutionRequestV1,
    PackageArtifactLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    PackageWheelVerifier,
    VerifiedWheelCandidate,
)
from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
)

IMPLEMENTED_B1_MANIFEST_CASES = (
    "B-CLASS-PLUGIN",
    "B-CLASS-NONPLUGIN",
    "B-CLASS-INDETERMINATE",
    "B-CLASS-SPOOF",
    "B-CRASH-ACCEPTED",
    "B-CRASH-CLASSIFIED",
    "B-CONCUR-CONFLICT",
    "B-ENTRY-DISABLED",
)

IMPLEMENTED_B2_MANIFEST_CASES = (
    "B-ACQ-AUTH",
    "B-ACQ-PROVENANCE",
    "B-ACQ-BYTES",
    "B-ACQ-REDIRECT",
    "B-ACQ-TIMEOUT",
    "B-ACQ-DIGEST",
)

IMPLEMENTED_B2H_MANIFEST_CASES = (
    "B-ARCH-TRUNCATED",
    "B-ARCH-HEADERS",
    "B-ARCH-OVERLAP",
    "B-ARCH-COMPRESSION",
    "B-ARCH-TRAILING",
    "B-PATH-ABSOLUTE",
    "B-PATH-TRAVERSAL",
    "B-PATH-EMPTY",
    "B-PATH-COLLISION-SEP",
    "B-PATH-COLLISION-UNICODE",
    "B-TYPE-SYMLINK",
    "B-TYPE-DEVICE",
    "B-TYPE-SOCKET",
    "B-TYPE-FIFO",
    "B-LIMIT-ENTRY",
    "B-LIMIT-MEMORY",
    "B-LIMIT-CPU",
    "B-WHEEL-SDIST",
    "B-WHEEL-ZIP",
    "B-WHEEL-TAGS",
    "B-WHEEL-METADATA",
    "B-WHEEL-RECORD-HASH",
    "B-WHEEL-RECORD-SET",
    "B-WHEEL-RECORD-ALGO",
)

IMPLEMENTED_B2I_WINDOWS_MANIFEST_CASES = (
    "B-PATH-WIN-ROOT",
    "B-PATH-WIN-ADS",
    "B-PATH-WIN-RESERVED",
    "B-PATH-WIN-TRAILING",
    "B-PATH-COLLISION-CASE",
    "B-TYPE-REPARSE",
    "B-TYPE-JUNCTION",
)

IMPLEMENTED_B2J_RECOVERY_MANIFEST_CASES = (
    "B-ACQ-IDENTITY",
    "B-CRASH-ACQUIRING",
    "B-CRASH-ACQUIRED",
    "B-CRASH-INSPECTING",
    "B-CRASH-EXTRACTED",
    "B-STATE-REJECT-CLEANUP",
)

IMPLEMENTED_B2K_HARDLINK_MANIFEST_CASES = ("B-TYPE-HARDLINK",)
IMPLEMENTED_B3D_RECOVERY_MANIFEST_CASES = (
    "B-CRASH-RESOLVING",
    "B-CRASH-CLOSURE",
)
IMPLEMENTED_B3D_LIMIT_MANIFEST_CASES = (
    "B-LIMIT-GRAPH",
    "B-LIMIT-SOLVER",
    "B-LIMIT-REQUESTS",
)
IMPLEMENTED_B3D_INTEGRITY_MANIFEST_CASES = (
    "B-CLOSURE-MISSING",
    "B-CLOSURE-DIGEST",
    "B-CLOSURE-ORIGIN",
    "B-CLOSURE-MARKER",
    "B-CLOSURE-NAME",
    "B-CLOSURE-CYCLE",
    "B-CLOSURE-V1",
)

EXECUTABLE_MANIFEST_CASES = (
    IMPLEMENTED_B1_MANIFEST_CASES
    + IMPLEMENTED_B2_MANIFEST_CASES
    + IMPLEMENTED_B2H_MANIFEST_CASES
    + IMPLEMENTED_B2I_WINDOWS_MANIFEST_CASES
    + IMPLEMENTED_B2J_RECOVERY_MANIFEST_CASES
    + IMPLEMENTED_B2K_HARDLINK_MANIFEST_CASES
    + IMPLEMENTED_B3D_RECOVERY_MANIFEST_CASES
    + IMPLEMENTED_B3D_LIMIT_MANIFEST_CASES
    + IMPLEMENTED_B3D_INTEGRITY_MANIFEST_CASES
)

WHEEL_FILENAME = "acme_plugin-1.0-py3-none-any.whl"
DIST_INFO = "acme_plugin-1.0.dist-info"


def _record_digest(payload: bytes) -> str:
    digest = base64.urlsafe_b64encode(sha256(payload).digest()).rstrip(b"=")
    return "sha256=" + digest.decode()


def _wheel_bytes(
    *,
    extra_files: dict[str, bytes] | None = None,
    entry_modes: dict[str, int] | None = None,
    windows_attributes: dict[str, int] | None = None,
    package_metadata: bytes | None = None,
    record_rows: list[tuple[str, str, str]] | None = None,
) -> bytes:
    files = {
        "acme_plugin/__init__.py": b"VALUE = 1\n",
        f"{DIST_INFO}/WHEEL": (
            b"Wheel-Version: 1.0\n"
            b"Generator: plc9b-manifest\n"
            b"Root-Is-Purelib: true\n"
            b"Tag: py3-none-any\n\n"
        ),
        f"{DIST_INFO}/METADATA": package_metadata
        or b"Metadata-Version: 2.1\nName: acme-plugin\nVersion: 1.0\n\n",
    }
    files.update(extra_files or {})
    if record_rows is None:
        record_rows = [
            (name, _record_digest(payload), str(len(payload)))
            for name, payload in files.items()
        ]
        record_rows.append((f"{DIST_INFO}/RECORD", "", ""))
    record = io.StringIO(newline="")
    csv.writer(record, lineterminator="\n").writerows(record_rows)
    files[f"{DIST_INFO}/RECORD"] = record.getvalue().encode()

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            info = zipfile.ZipInfo(name)
            if name in (windows_attributes or {}):
                info.create_system = 0
                info.external_attr = (windows_attributes or {})[name]
            else:
                info.create_system = 3
                info.external_attr = (entry_modes or {}).get(
                    name, stat.S_IFREG | 0o644
                ) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return output.getvalue()


def _package_wheel_bytes(
    project: str,
    version: str,
    *,
    requires_dist: tuple[str, ...] = (),
    requires_python: str | None = None,
) -> bytes:
    normalized = project.replace("-", "_")
    dist_info = f"{normalized}-{version}.dist-info"
    metadata = (
        f"Metadata-Version: 2.1\nName: {project}\nVersion: {version}\n"
        + ("" if requires_python is None else f"Requires-Python: {requires_python}\n")
        + "".join(f"Requires-Dist: {item}\n" for item in requires_dist)
        + "\n"
    ).encode()
    files = {
        f"{normalized}/__init__.py": b"VALUE = 1\n",
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\n"
            b"Generator: plc9b-manifest\n"
            b"Root-Is-Purelib: true\n"
            b"Tag: py3-none-any\n\n"
        ),
        f"{dist_info}/METADATA": metadata,
    }
    rows = [
        (name, _record_digest(payload), str(len(payload)))
        for name, payload in files.items()
    ]
    rows.append((f"{dist_info}/RECORD", "", ""))
    record = io.StringIO(newline="")
    csv.writer(record, lineterminator="\n").writerows(rows)
    files[f"{dist_info}/RECORD"] = record.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return output.getvalue()


def _record_rows() -> list[tuple[str, str, str]]:
    files = {
        "acme_plugin/__init__.py": b"VALUE = 1\n",
        f"{DIST_INFO}/WHEEL": (
            b"Wheel-Version: 1.0\n"
            b"Generator: plc9b-manifest\n"
            b"Root-Is-Purelib: true\n"
            b"Tag: py3-none-any\n\n"
        ),
        f"{DIST_INFO}/METADATA": (
            b"Metadata-Version: 2.1\nName: acme-plugin\nVersion: 1.0\n\n"
        ),
    }
    rows = [
        (name, _record_digest(payload), str(len(payload)))
        for name, payload in files.items()
    ]
    rows.append((f"{DIST_INFO}/RECORD", "", ""))
    return rows


def _hardlinked_source_wheel(
    tmp_path: Path,
) -> tuple[bytes, Path, Path, tuple[str, str]]:
    source = tmp_path / "hardlinked-source"
    source.mkdir()
    first = source / "first.bin"
    second = source / "second.bin"
    payload = b"one-source-inode"
    first.write_bytes(payload)
    os.link(first, second)
    archive_names = (
        "acme_plugin/hardlink-first.bin",
        "acme_plugin/hardlink-second.bin",
    )
    files = {
        f"{DIST_INFO}/WHEEL": (
            b"Wheel-Version: 1.0\n"
            b"Generator: plc9b-hardlink-manifest\n"
            b"Root-Is-Purelib: true\n"
            b"Tag: py3-none-any\n\n"
        ),
        f"{DIST_INFO}/METADATA": (
            b"Metadata-Version: 2.1\nName: acme-plugin\nVersion: 1.0\n\n"
        ),
        archive_names[0]: payload,
        archive_names[1]: payload,
    }
    rows = [
        (name, _record_digest(content), str(len(content)))
        for name, content in files.items()
    ]
    rows.append((f"{DIST_INFO}/RECORD", "", ""))
    record = io.StringIO(newline="")
    csv.writer(record, lineterminator="\n").writerows(rows)
    files[f"{DIST_INFO}/RECORD"] = record.getvalue().encode()

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            if name in archive_names:
                continue
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
        archive.write(first, archive_names[0])
        archive.write(second, archive_names[1])
    return output.getvalue(), first, second, archive_names


def _corrupt_local_header(payload: bytes) -> bytes:
    changed = bytearray(payload)
    central = changed.index(b"PK\x01\x02")
    local_offset = struct.unpack_from("<L", changed, central + 42)[0]
    changed[local_offset + 8 : local_offset + 10] = struct.pack("<H", 0)
    return bytes(changed)


def _claim_overlapping_local_entry(payload: bytes) -> bytes:
    changed = bytearray(payload)
    central_offsets: list[int] = []
    cursor = 0
    while (offset := changed.find(b"PK\x01\x02", cursor)) >= 0:
        central_offsets.append(offset)
        cursor = offset + 4
    assert len(central_offsets) >= 2
    first_local = struct.unpack_from("<L", changed, central_offsets[0] + 42)[0]
    struct.pack_into("<L", changed, central_offsets[1] + 42, first_local)
    return bytes(changed)


def _claim_unsupported_compression(payload: bytes) -> bytes:
    changed = bytearray(payload)
    central = changed.index(b"PK\x01\x02")
    struct.pack_into("<H", changed, central + 10, 99)
    return bytes(changed)


@dataclass(frozen=True)
class _InspectionFixture:
    payload: bytes
    wheel_filename: str = WHEEL_FILENAME
    supported_tags: frozenset[str] = frozenset({"py3-none-any"})
    budgets: PackageInspectionBudgetV1 = PackageInspectionBudgetV1()
    verifier: PackageWheelVerifier | None = None


def _inspection_fixture(case_id: str) -> _InspectionFixture:
    base = _wheel_bytes()
    if case_id == "B-ARCH-TRUNCATED":
        return _InspectionFixture(payload=base[:-8])
    if case_id == "B-ARCH-HEADERS":
        return _InspectionFixture(payload=_corrupt_local_header(base))
    if case_id == "B-ARCH-OVERLAP":
        return _InspectionFixture(payload=_claim_overlapping_local_entry(base))
    if case_id == "B-ARCH-COMPRESSION":
        return _InspectionFixture(payload=_claim_unsupported_compression(base))
    if case_id == "B-ARCH-TRAILING":
        return _InspectionFixture(payload=base + b"attacker-payload")
    if case_id == "B-PATH-ABSOLUTE":
        return _InspectionFixture(
            payload=_wheel_bytes(extra_files={"/absolute.py": b"hostile"})
        )
    if case_id == "B-PATH-TRAVERSAL":
        return _InspectionFixture(
            payload=_wheel_bytes(extra_files={"../escape.py": b"hostile"})
        )
    if case_id == "B-PATH-EMPTY":
        return _InspectionFixture(
            payload=_wheel_bytes(extra_files={"pkg//empty.py": b"hostile"})
        )
    if case_id == "B-PATH-COLLISION-SEP":
        return _InspectionFixture(
            payload=_wheel_bytes(
                extra_files={
                    "pkg/name.py": b"one",
                    "pkg\\name.py": b"two",
                }
            )
        )
    if case_id == "B-PATH-COLLISION-UNICODE":
        return _InspectionFixture(
            payload=_wheel_bytes(
                extra_files={
                    "pkg/caf\N{LATIN SMALL LETTER E WITH ACUTE}.py": b"one",
                    "pkg/cafe\N{COMBINING ACUTE ACCENT}.py": b"two",
                }
            )
        )
    windows_paths = {
        "B-PATH-WIN-ROOT": "C:/escape.py",
        "B-PATH-WIN-ADS": "pkg/file.py:stream",
        "B-PATH-WIN-RESERVED": "pkg/CON",
        "B-PATH-WIN-TRAILING": "pkg/trailing. ",
    }
    if case_id in windows_paths:
        return _InspectionFixture(
            payload=_wheel_bytes(extra_files={windows_paths[case_id]: b"hostile"})
        )
    if case_id == "B-PATH-COLLISION-CASE":
        return _InspectionFixture(
            payload=_wheel_bytes(
                extra_files={
                    "pkg/Name.py": b"one",
                    "pkg/name.py": b"two",
                }
            )
        )
    entry_types = {
        "B-TYPE-SYMLINK": stat.S_IFLNK | 0o777,
        "B-TYPE-DEVICE": stat.S_IFCHR | 0o600,
        "B-TYPE-SOCKET": stat.S_IFSOCK | 0o600,
        "B-TYPE-FIFO": stat.S_IFIFO | 0o600,
    }
    if case_id in entry_types:
        name = "pkg/hostile-entry"
        return _InspectionFixture(
            payload=_wheel_bytes(
                extra_files={name: b"hostile"},
                entry_modes={name: entry_types[case_id]},
            )
        )
    if case_id == "B-TYPE-REPARSE":
        name = "pkg/reparse-entry"
        return _InspectionFixture(
            payload=_wheel_bytes(
                extra_files={name: b"hostile"},
                windows_attributes={name: 0x400},
            )
        )
    if case_id == "B-TYPE-JUNCTION":
        name = "pkg/junction/"
        return _InspectionFixture(
            payload=_wheel_bytes(
                extra_files={name: b""},
                windows_attributes={name: 0x400 | 0x10},
            )
        )
    if case_id == "B-LIMIT-ENTRY":
        return _InspectionFixture(
            payload=_wheel_bytes(extra_files={"pkg/large.bin": b"x" * 200}),
            budgets=PackageInspectionBudgetV1(
                max_entries=4,
                max_total_expanded_bytes=128,
                max_entry_expanded_bytes=64,
            ),
        )
    if case_id == "B-LIMIT-MEMORY":
        return _InspectionFixture(
            payload=base,
            budgets=PackageInspectionBudgetV1(max_metadata_bytes=64),
        )
    if case_id == "B-LIMIT-CPU":
        return _InspectionFixture(
            payload=base,
            budgets=PackageInspectionBudgetV1(max_wall_time_ms=1),
            verifier=PackageWheelVerifier(clock=_AdvancingInspectionClock()),
        )
    if case_id == "B-WHEEL-SDIST":
        return _InspectionFixture(
            payload=base,
            wheel_filename="acme_plugin-1.0.tar.gz",
        )
    if case_id == "B-WHEEL-ZIP":
        return _InspectionFixture(
            payload=base,
            wheel_filename="acme_plugin-1.0.zip",
        )
    if case_id == "B-WHEEL-TAGS":
        return _InspectionFixture(
            payload=base,
            supported_tags=frozenset({"cp313-cp313-win_amd64"}),
        )
    if case_id == "B-WHEEL-METADATA":
        return _InspectionFixture(
            payload=_wheel_bytes(
                package_metadata=(
                    b"Metadata-Version: 2.1\nName: another-project\nVersion: 9\n\n"
                )
            )
        )
    rows = _record_rows()
    if case_id == "B-WHEEL-RECORD-HASH":
        rows[0] = (rows[0][0], "sha256=" + "A" * 43, rows[0][2])
        return _InspectionFixture(payload=_wheel_bytes(record_rows=rows))
    if case_id == "B-WHEEL-RECORD-SET":
        rows.pop(0)
        return _InspectionFixture(payload=_wheel_bytes(record_rows=rows))
    if case_id == "B-WHEEL-RECORD-ALGO":
        rows[0] = (rows[0][0], "md5=deadbeef", rows[0][2])
        return _InspectionFixture(payload=_wheel_bytes(record_rows=rows))
    raise AssertionError(f"Unhandled PLC9B2h inspection fixture: {case_id}")


@dataclass
class _Authority:
    facts: PackageClassificationFactsV1

    def classification_facts(
        self,
        _request: object,
    ) -> PackageClassificationFactsV1:
        return self.facts


@dataclass
class _Clock:
    now: float = 100.0

    def __call__(self) -> float:
        return self.now


@dataclass
class _AdvancingInspectionClock:
    now: float = 100.0

    def __call__(self) -> float:
        self.now += 0.002
        return self.now


@dataclass
class _StableClassificationRecheck:
    def recheck(
        self,
        _request: PackageLifecycleRequestV1,
        prior: PluginBoundPackageClassificationV1,
    ) -> PluginBoundPackageClassificationV1:
        return prior


@dataclass
class _SourceStream:
    envelope: AuthenticatedSourceEnvelopeV1
    chunks: tuple[bytes, ...]
    request_count: int = 1
    redirects: tuple[str, ...] = ()
    clock: _Clock | None = None
    advance_seconds: float = 0.0
    requests_started: int = 0
    redirects_started: int = 0
    writes_started: int = 0

    def transfer_to(self, sink: BoundedAcquisitionSinkPort) -> SourceAdapterResultV1:
        for _index in range(self.request_count):
            sink.begin_request()
            self.requests_started += 1
        for redirect in self.redirects:
            sink.record_redirect(redirect)
            self.redirects_started += 1
        for chunk in self.chunks:
            sink.write(chunk)
            self.writes_started += 1
            if self.clock is not None:
                self.clock.now += self.advance_seconds
        return SourceAdapterResultV1(disposition="complete")


@dataclass
class _SourceAuthority:
    case_id: str
    secret: str
    payload: bytes | None = None
    payloads: dict[str, bytes] | None = None
    clock: _Clock | None = None
    authorize_calls: int = 0
    stream: _SourceStream | None = None

    def authorize(self, request: PackageAcquisitionRequestV1) -> _SourceStream:
        self.authorize_calls += 1
        if self.case_id == "B-ACQ-AUTH":
            raise PackageAcquisitionError(
                f"registry rejected credential {self.secret}",
                code="package_source_unauthorized",
                stage="acquiring",
                retryable=False,
                consumed_bytes=0,
            )
        if self.case_id == "B-CLOSURE-ORIGIN" and request.node_id != "root":
            raise PackageAcquisitionError(
                "Package dependency Source origin is unauthorized",
                code="package_source_unauthorized",
                stage="acquiring",
                retryable=False,
                consumed_bytes=0,
            )

        payload = (
            (self.payloads or {}).get(request.canonical_source_identity)
            if self.payloads is not None
            else self.payload
        )
        chunks = (payload if payload is not None else b"wheel",)
        request_count = 1
        redirects: tuple[str, ...] = ()
        advance_seconds = 0.0
        canonical_source_identity = request.canonical_source_identity
        expected_digest = sha256(b"".join(chunks)).hexdigest()
        if self.case_id == "B-ACQ-PROVENANCE":
            canonical_source_identity = "https://other.example.test/acme.whl"
        elif self.case_id == "B-ACQ-BYTES":
            chunks = (b"12345678", b"overflow")
            expected_digest = sha256(b"".join(chunks)).hexdigest()
        elif self.case_id == "B-ACQ-REDIRECT":
            chunks = ()
            redirects = (
                "https://mirror-1.example.test/acme.whl",
                "https://mirror-2.example.test/acme.whl",
            )
            expected_digest = sha256(b"").hexdigest()
        elif self.case_id == "B-ACQ-TIMEOUT":
            chunks = (b"first", b"second")
            expected_digest = sha256(b"".join(chunks)).hexdigest()
            advance_seconds = 0.006
        elif self.case_id == "B-ACQ-DIGEST":
            chunks = (b"changed-wheel",)
            expected_digest = "d" * 64

        self.stream = _SourceStream(
            envelope=AuthenticatedSourceEnvelopeV1(
                operation_id=request.operation_id,
                node_id=request.node_id,
                canonical_source_identity=canonical_source_identity,
                origin_kind="https",
                authentication_decision="authorized",
                authority_id="source-authority:manifest",
                requested_locator_digest=request.requested_locator_digest,
                expected_artifact_digest=expected_digest,
                redirect_policy_revision="redirect-policy:1",
                policy_revision=request.policy_revision,
                capture_epoch=1,
            ),
            chunks=chunks,
            request_count=request_count,
            redirects=redirects,
            clock=self.clock,
            advance_seconds=advance_seconds,
        )
        return self.stream


class _CleanupDebtWheelVerifier(PackageWheelVerifier):
    def __init__(self, store: PackageQuarantineStore) -> None:
        super().__init__()
        self._store = store

    def verify(
        self,
        candidate: AcquiredPackageCandidate,
        *,
        wheel_filename: str,
        supported_tags: frozenset[str],
        budgets: PackageInspectionBudgetV1,
    ) -> VerifiedWheelCandidate:
        attempt = self._store.root / self._store.attempt_names()[0]
        (attempt / "manifest-cleanup-debt").write_bytes(b"bounded-debt")
        return super().verify(
            candidate,
            wheel_filename=wheel_filename,
            supported_tags=supported_tags,
            budgets=budgets,
        )


@dataclass
class _NoDependencyResolver:
    calls: int = 0

    def resolve(
        self,
        _request: PackageDependencySelectionRequestV1,
    ) -> PackageDependencySelectionV1:
        self.calls += 1
        raise AssertionError("root-only closure must not consult the resolver")


@dataclass(frozen=True)
class _ManifestSelection:
    version: str
    source: str
    filename: str
    digest: str


@dataclass
class _ManifestResolver:
    selections: dict[str | tuple[str, str], _ManifestSelection]
    calls: list[str] = field(default_factory=list)

    def resolve(
        self,
        request: PackageDependencySelectionRequestV1,
    ) -> PackageDependencySelectionV1:
        self.calls.append(request.requirement.project_name)
        selected = (
            self.selections.get(
                (
                    request.requirement.project_name,
                    request.requirement.specifier_text,
                )
            )
            or self.selections[request.requirement.project_name]
        )
        return PackageDependencySelectionV1(
            operation_id=request.operation_id,
            attempt_epoch=request.attempt_epoch,
            parent_node_id=request.parent_node_id,
            request_fingerprint=request.request_fingerprint,
            resolution_environment_fingerprint=(
                request.resolution_environment_fingerprint
            ),
            requirement_fingerprint=request.requirement_fingerprint,
            project_name=request.requirement.project_name,
            version=selected.version,
            canonical_source_identity=selected.source,
            wheel_filename=selected.filename,
            expected_artifact_digest=selected.digest,
            resolver_id="resolver:manifest",
            resolver_revision="resolver-revision:1",
        )


@dataclass
class _LegacyClosureBuilder:
    verifier: PackageClosureVerifier = field(default_factory=PackageClosureVerifier)
    calls: int = 0

    def build(
        self,
        root: VerifiedWheelCandidate,
        _request: PackageRecursiveClosureRequestV2,
    ) -> VerifiedPackageClosureCandidate:
        self.calls += 1
        try:
            self.verifier.verify(
                PluginDependencyClosureLock(
                    package_content_digest="a" * 64,
                    python_distributions=(),
                )
            )
        finally:
            root.cleanup()
        raise AssertionError("Legacy closure evidence unexpectedly satisfied v2")


def _facts(*present: str) -> PackageClassificationFactsV1:
    present_set = set(present)
    kinds = (
        "explicit_plugin_intent",
        "existing_plugin_binding",
        "existing_plugin_history",
        "independent_non_plugin_authority",
    )
    return PackageClassificationFactsV1(
        facts=tuple(
            PackageClassificationBasisFactV1(
                kind=kind,  # type: ignore[arg-type]
                present=kind in present_set,
                authority_id=f"authority:{kind}",
                owner_revision=f"revision:{kind}:1",
            )
            for kind in kinds
        ),
        policy_revision="classification-policy:1",
        classifier_epoch=1,
    )


def _request(
    *,
    source: str = "https://packages.example.test/acme.whl",
    environment_fingerprint: str = "e" * 64,
) -> PackageLifecycleIngressRequestV1:
    return PackageLifecycleIngressRequestV1(
        operation_id="manifest-operation",
        action="install",
        product_id="coding",
        scope_id="workspace:manifest",
        requested_package="acme==1.0",
        requested_plugin_id="acme.plugin",
        source_locator=source,
        policy_revision="package-policy:1",
        quota_profile_revision="quota:1",
        resolution_environment_fingerprint=environment_fingerprint,
    )


def _closure_environment() -> PackageResolutionEnvironmentV1:
    return PackageResolutionEnvironmentV1.from_mapping(
        {
            "implementation_name": "cpython",
            "implementation_version": "3.11.10",
            "os_name": "posix",
            "platform_machine": "x86_64",
            "platform_python_implementation": "CPython",
            "platform_release": "manifest",
            "platform_system": "Linux",
            "platform_version": "manifest",
            "python_full_version": "3.11.10",
            "python_version": "3.11",
            "sys_platform": "linux",
        },
        supported_tags=("py3-none-any",),
    )


def _owner(
    tmp_path: Path,
    *,
    facts: PackageClassificationFactsV1,
    enabled: bool = True,
) -> tuple[PackageLifecycleOwner, PackageLifecycleJournal]:
    journal = PackageLifecycleJournal(tmp_path / "package-lifecycle.jsonl")
    return (
        PackageLifecycleOwner(
            journal=journal,
            classification_authority=_Authority(facts),
            enabled=enabled,
        ),
        journal,
    )


def _b2_owner(
    tmp_path: Path,
    *,
    case_id: str,
    secret: str,
    payload: bytes | None = None,
    payloads: dict[str, bytes] | None = None,
    inspection_budgets: PackageInspectionBudgetV1 | None = None,
    wheel_verifier: PackageWheelVerifier | None = None,
    supported_tags: frozenset[str] | None = None,
    cleanup_debt: bool = False,
):
    lifecycle_journal = PackageLifecycleJournal(tmp_path / "package-lifecycle.jsonl")
    kernel = PackageLifecycleOwner(
        journal=lifecycle_journal,
        classification_authority=_Authority(_facts("explicit_plugin_intent")),
        enabled=True,
    )
    store = PackageQuarantineStore(tmp_path / "quarantine")
    evidence_journal = PackageArtifactEvidenceJournal(
        tmp_path / "package-artifact-evidence.jsonl"
    )
    cleanup_journal = PackageQuarantineCleanupJournal(
        tmp_path / "package-quarantine-cleanup.jsonl"
    )
    cleanup_owner = PackageQuarantineCleanupOwner(
        journal=cleanup_journal,
        store=store,
    )
    clock = _Clock() if case_id == "B-ACQ-TIMEOUT" else None
    source_authority = _SourceAuthority(
        case_id=case_id,
        secret=secret,
        payload=payload,
        payloads=payloads,
        clock=clock,
    )
    artifact_owner = PackageArtifactLifecycleOwner(
        kernel=kernel,
        classification_recheck=_StableClassificationRecheck(),
        acquisition_owner=PackageAcquisitionOwner(
            source_authority=source_authority,
            quarantine_store=store,
            clock=clock,
        ),
        evidence_journal=evidence_journal,
        cleanup_owner=cleanup_owner,
        wheel_verifier=(
            wheel_verifier
            or (
                _CleanupDebtWheelVerifier(store)
                if cleanup_debt
                else PackageWheelVerifier()
            )
        ),
        acquisition_budgets=PackageAcquisitionBudgetV1(
            max_transport_bytes=(8 if case_id == "B-ACQ-BYTES" else 256 * 1024),
            max_requests=1,
            max_redirects=1,
            max_wall_time_ms=5 if case_id == "B-ACQ-TIMEOUT" else 1000,
        ),
        inspection_budgets=inspection_budgets or PackageInspectionBudgetV1(),
        supported_tags=supported_tags or frozenset({"py3-none-any"}),
    )
    return (
        kernel,
        artifact_owner,
        lifecycle_journal,
        evidence_journal,
        cleanup_journal,
        store,
        source_authority,
    )


def _b3d_owner(
    tmp_path: Path,
    *,
    case_id: str,
    secret: str,
    root_payload: bytes | None = None,
    payloads: dict[str, bytes] | None = None,
    resolver: _NoDependencyResolver | _ManifestResolver | None = None,
    closure_builder: _LegacyClosureBuilder | None = None,
):
    components = _b2_owner(
        tmp_path,
        case_id=case_id,
        secret=secret,
        payload=root_payload or _wheel_bytes(),
        payloads=payloads,
    )
    (
        kernel,
        artifact_owner,
        _lifecycle_journal,
        evidence_journal,
        _cleanup_journal,
        _store,
        _source_authority,
    ) = components
    resolution_journal = PackageClosureResolutionJournal(
        tmp_path / "package-closure-resolution.jsonl"
    )
    resolver = resolver or _NoDependencyResolver()
    recursive_owner = closure_builder or PackageRecursiveClosureOwner(
        resolver=resolver,
        acquisition_owner=artifact_owner._acquisition_owner,
        evidence_journal=evidence_journal,
        wheel_verifier=artifact_owner._wheel_verifier,
        closure_verifier=PackageClosureVerifier(),
        acquisition_budgets=artifact_owner._acquisition_budgets,
        inspection_budgets=artifact_owner._inspection_budgets,
        cleanup_owner=artifact_owner._cleanup_owner,
        selection_journal=resolution_journal,
    )
    return (
        *components,
        PackageClosureLifecycleOwner(
            kernel=kernel,
            artifact_owner=artifact_owner,
            closure_builder=recursive_owner,
            resolution_journal=resolution_journal,
        ),
        resolution_journal,
        resolver,
    )


def _artifact_execution(
    status: PackageLifecycleStatusV1,
    *,
    secret: str,
) -> PackageArtifactExecutionRequestV1:
    return PackageArtifactExecutionRequestV1(
        operation_id=status.operation_id,
        request_fingerprint=status.request_fingerprint,
        expected_attempt_epoch=status.attempt_epoch,
        wheel_filename=WHEEL_FILENAME,
        credential_reference=f"opaque:{secret}",
    )


def _land_artifact_phase(
    *,
    kernel: PackageLifecycleOwner,
    artifact_owner: PackageArtifactLifecycleOwner,
    evidence_journal: PackageArtifactEvidenceJournal,
    classified: PackageLifecycleStatusV1,
    target_phase: str,
    secret: str,
) -> tuple[
    PackageLifecycleStatusV1,
    AcquiredPackageCandidate | VerifiedWheelCandidate | None,
    PackageArtifactExecutionRequestV1,
]:
    execution = _artifact_execution(classified, secret=secret)
    if target_phase == "extracted":
        result = artifact_owner.execute(execution)
        assert result.status.phase == "extracted"
        assert result.candidate is not None
        return result.status, result.candidate, execution

    acquiring = kernel.advance(
        classified.operation_id,
        next_phase="acquiring",
        expected_phase="classified",
        expected_journal_revision=classified.journal_revision,
        expected_attempt_epoch=classified.attempt_epoch,
    )
    if target_phase == "acquiring":
        return acquiring, None, execution

    request = kernel.journal.request(acquiring.operation_id)
    assert request is not None
    acquisition_request = PackageAcquisitionRequestV1(
        operation_id=request.operation_id,
        attempt_epoch=acquiring.attempt_epoch,
        node_id="root",
        canonical_source_identity=request.canonical_source_identity,
        request_fingerprint=request.request_fingerprint,
        requested_locator_digest=sha256(
            request.canonical_source_identity.encode("utf-8")
        ).hexdigest(),
        policy_revision=request.policy_revision,
        credential_reference=f"opaque:{secret}",
    )
    authorized = artifact_owner._acquisition_owner.authorize_source(acquisition_request)
    evidence_journal.append(
        request_fingerprint=request.request_fingerprint,
        evidence=PackageAuthenticatedSourceEvidenceV1(
            attempt_epoch=acquiring.attempt_epoch,
            envelope=authorized.envelope,
        ),
    )
    candidate = artifact_owner._acquisition_owner.acquire_authorized(
        acquisition_request,
        authorized,
        budgets=artifact_owner._acquisition_budgets,
    )
    evidence_journal.append(
        request_fingerprint=request.request_fingerprint,
        evidence=candidate.receipt,
    )
    acquired = kernel.advance(
        acquiring.operation_id,
        next_phase="acquired",
        expected_phase="acquiring",
        expected_journal_revision=acquiring.journal_revision,
        expected_attempt_epoch=acquiring.attempt_epoch,
    )
    if target_phase == "acquired":
        return acquired, candidate, execution

    assert target_phase == "inspecting"
    inspecting = kernel.advance(
        acquired.operation_id,
        next_phase="inspecting",
        expected_phase="acquired",
        expected_journal_revision=acquired.journal_revision,
        expected_attempt_epoch=acquired.attempt_epoch,
    )
    return inspecting, candidate, execution


@pytest.mark.parametrize("case_id", EXECUTABLE_MANIFEST_CASES)
def test_manifest_case(case_id: str, tmp_path: Path) -> None:
    if case_id == "B-CLASS-PLUGIN":
        owner, journal = _owner(
            tmp_path,
            facts=_facts("explicit_plugin_intent"),
        )
        status = owner.submit(_request())
        _assert_classification(status, decision="plugin_bound", code=None)
        _assert_replay_is_single_owner(owner, journal)
    elif case_id == "B-CLASS-NONPLUGIN":
        owner, journal = _owner(
            tmp_path,
            facts=_facts("independent_non_plugin_authority"),
        )
        status = owner.submit(_request())
        _assert_classification(status, decision="non_plugin", code=None)
        _assert_replay_is_single_owner(owner, journal)
    elif case_id == "B-CLASS-INDETERMINATE":
        owner, journal = _owner(tmp_path, facts=_facts())
        status = owner.submit(_request())
        _assert_classification(
            status,
            decision="indeterminate",
            code="package_target_classification_indeterminate",
        )
        _assert_replay_is_single_owner(owner, journal)
    elif case_id == "B-CLASS-SPOOF":
        assert (
            "plugin_bound"
            not in inspect.signature(PackageLifecycleIngressRequestV1).parameters
        )
        owner, journal = _owner(tmp_path, facts=_facts())
        status = owner.submit(_request())
        _assert_classification(
            status,
            decision="indeterminate",
            code="package_target_classification_indeterminate",
        )
        _assert_replay_is_single_owner(owner, journal)
    elif case_id in {"B-CRASH-ACCEPTED", "B-CRASH-CLASSIFIED"}:
        owner, journal = _owner(
            tmp_path,
            facts=_facts("explicit_plugin_intent"),
        )
        accepted = owner.accept(_request())
        current = accepted
        if case_id == "B-CRASH-CLASSIFIED":
            current = owner.classify(
                accepted.operation_id,
                expected_journal_revision=accepted.journal_revision,
                expected_attempt_epoch=accepted.attempt_epoch,
            )
        interrupted = owner.interrupt(
            current.operation_id,
            expected_phase=current.phase,
            expected_journal_revision=current.journal_revision,
            expected_attempt_epoch=current.attempt_epoch,
        )
        record_count = len(journal.records())
        replay = owner.interrupt(
            current.operation_id,
            expected_phase=current.phase,
            expected_journal_revision=current.journal_revision,
            expected_attempt_epoch=current.attempt_epoch,
        )
        assert replay == interrupted
        assert len(journal.records()) == record_count
        assert interrupted.disposition == "retryable_failure"
        assert interrupted.failure is not None
        assert interrupted.failure.code == "package_operation_interrupted"
        assert interrupted.request_fingerprint == current.request_fingerprint
    elif case_id == "B-CONCUR-CONFLICT":
        owner, journal = _owner(
            tmp_path,
            facts=_facts("explicit_plugin_intent"),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(owner.submit, _request()),
                executor.submit(
                    owner.submit,
                    _request(source="https://packages.example.test/changed.whl"),
                ),
            )
            statuses = tuple(future.result() for future in futures)
        accepted = next(status for status in statuses if status.disposition == "active")
        conflict = next(
            status for status in statuses if status.disposition == "rejected"
        )
        assert conflict.disposition == "rejected"
        assert conflict.failure is not None
        assert conflict.failure.code == "package_operation_identity_conflict"
        assert journal.status(accepted.operation_id) == accepted
        assert len(journal.records()) == 2
    elif case_id == "B-ENTRY-DISABLED":
        owner, journal = _owner(
            tmp_path,
            facts=_facts("explicit_plugin_intent"),
            enabled=False,
        )
        status = owner.submit(_request())
        assert status.phase == "classified"
        assert status.disposition == "rejected"
        assert status.failure is not None
        assert status.failure.code == "package_route_unavailable"
        assert journal.records() == ()
        assert not journal.path.exists()
    elif case_id in IMPLEMENTED_B2_MANIFEST_CASES:
        secret = f"manifest-secret-{case_id.lower()}"
        (
            kernel,
            artifact_owner,
            journal,
            evidence_journal,
            cleanup_journal,
            store,
            source_authority,
        ) = _b2_owner(tmp_path, case_id=case_id, secret=secret)
        classified = kernel.submit(
            _request(
                source=(
                    f"https://user:{secret}@packages.example.test/acme.whl"
                    f"?token={secret}#{secret}"
                )
            )
        )
        execution = PackageArtifactExecutionRequestV1(
            operation_id=classified.operation_id,
            request_fingerprint=classified.request_fingerprint,
            expected_attempt_epoch=classified.attempt_epoch,
            wheel_filename="acme-1.0-py3-none-any.whl",
            credential_reference=f"opaque:{secret}",
        )
        before_outside = tmp_path / "outside-sentinel"
        before_outside.write_bytes(b"preserve")

        result = artifact_owner.execute(execution)

        expected = {
            "B-ACQ-AUTH": (
                "acquiring",
                "rejected",
                "package_source_unauthorized",
            ),
            "B-ACQ-PROVENANCE": (
                "acquiring",
                "rejected",
                "package_source_provenance_changed",
            ),
            "B-ACQ-BYTES": (
                "acquiring",
                "retryable_failure",
                "package_acquisition_limit_exceeded",
            ),
            "B-ACQ-REDIRECT": (
                "acquiring",
                "retryable_failure",
                "package_acquisition_limit_exceeded",
            ),
            "B-ACQ-TIMEOUT": (
                "acquiring",
                "retryable_failure",
                "package_operation_timed_out",
            ),
            "B-ACQ-DIGEST": (
                "acquired",
                "rejected",
                "package_acquisition_digest_mismatch",
            ),
        }[case_id]
        assert (
            result.status.phase,
            result.status.disposition,
            result.status.failure.code if result.status.failure is not None else None,
        ) == expected
        assert result.candidate is None
        assert result.cleanup_status is None
        assert source_authority.authorize_calls == 1
        evidence = evidence_journal.records()
        expected_evidence_kinds = (
            ()
            if case_id in {"B-ACQ-AUTH", "B-ACQ-PROVENANCE"}
            else ("authenticated_source",)
        )
        assert tuple(record.evidence_kind for record in evidence) == (
            expected_evidence_kinds
        )
        assert cleanup_journal.records() == ()
        assert store.attempt_names() == ()
        assert store.total_residue_bytes() == 0
        assert before_outside.read_bytes() == b"preserve"
        records = journal.records()
        replay = artifact_owner.execute(execution)
        assert replay.status == result.status
        assert replay.candidate is None
        assert journal.records() == records
        assert source_authority.authorize_calls == 1
        assert secret not in repr(result)
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert secret.encode() not in path.read_bytes()
    elif case_id == "B-ACQ-IDENTITY":
        secret = f"manifest-secret-{case_id.lower()}"
        payload = _wheel_bytes()
        (
            kernel,
            artifact_owner,
            journal,
            evidence_journal,
            cleanup_journal,
            store,
            source_authority,
        ) = _b2_owner(
            tmp_path,
            case_id=case_id,
            secret=secret,
            payload=payload,
        )
        classified = kernel.submit(
            _request(
                source=(
                    f"https://user:{secret}@packages.example.test/{WHEEL_FILENAME}"
                    f"?token={secret}#{secret}"
                )
            )
        )
        inspecting, candidate, execution = _land_artifact_phase(
            kernel=kernel,
            artifact_owner=artifact_owner,
            evidence_journal=evidence_journal,
            classified=classified,
            target_phase="inspecting",
            secret=secret,
        )
        assert candidate is not None
        candidate.suspend_for_recovery()
        attempt = store.root / store.attempt_names()[0]
        artifact = next(path for path in attempt.iterdir() if path.is_file())
        original = artifact.read_bytes()
        artifact.unlink()
        artifact.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        outside = tmp_path / "outside-sentinel"
        outside.write_bytes(b"preserve")
        evidence_before = evidence_journal.records()

        result = artifact_owner.execute(execution)

        assert result.status.phase == inspecting.phase
        assert result.status.disposition == "rejected"
        assert result.status.failure is not None
        assert result.status.failure.code == "package_artifact_identity_changed"
        assert result.candidate is None
        assert result.cleanup_status is None
        assert evidence_journal.records() == evidence_before
        assert len(evidence_before) == 2
        assert source_authority.authorize_calls == 1
        assert cleanup_journal.records() == ()
        assert store.attempt_names() == ()
        assert outside.read_bytes() == b"preserve"
        records = journal.records()
        assert artifact_owner.execute(execution).status == result.status
        assert journal.records() == records
        assert source_authority.authorize_calls == 1
        assert secret not in repr(result)
    elif case_id in IMPLEMENTED_B3D_LIMIT_MANIFEST_CASES:
        secret = f"manifest-secret-{case_id.lower()}"
        environment = _closure_environment()
        root_source = f"https://packages.example.test/{WHEEL_FILENAME}"
        dependency_source = (
            "https://packages.example.test/dependency-2.0-py3-none-any.whl"
        )
        root_payload = _package_wheel_bytes(
            "acme-plugin",
            "1.0",
            requires_dist=("dependency==2",),
        )
        dependency_payload = _package_wheel_bytes("dependency", "2.0")
        resolver = _ManifestResolver(
            {
                "dependency": _ManifestSelection(
                    version="2.0",
                    source=dependency_source,
                    filename="dependency-2.0-py3-none-any.whl",
                    digest=sha256(dependency_payload).hexdigest(),
                )
            }
        )
        (
            kernel,
            _artifact_owner,
            journal,
            evidence_journal,
            cleanup_journal,
            store,
            source_authority,
            closure_owner,
            resolution_journal,
            _resolver,
        ) = _b3d_owner(
            tmp_path,
            case_id=case_id,
            secret=secret,
            root_payload=root_payload,
            payloads={
                root_source: root_payload,
                dependency_source: dependency_payload,
            },
            resolver=resolver,
        )
        classified = kernel.submit(
            _request(
                source=(
                    f"https://user:{secret}@packages.example.test/{WHEEL_FILENAME}"
                    f"?token={secret}#{secret}"
                ),
                environment_fingerprint=environment.fingerprint,
            )
        )
        budgets = {
            "B-LIMIT-GRAPH": PackageClosureBudgetV1(max_nodes=1),
            "B-LIMIT-SOLVER": PackageClosureBudgetV1(max_solver_steps=0),
            "B-LIMIT-REQUESTS": PackageClosureBudgetV1(max_total_requests=1),
        }[case_id]
        execution = PackageClosureExecutionRequestV2(
            artifact=_artifact_execution(classified, secret=secret),
            resolution_environment=environment,
            budgets=budgets,
        )
        outside = tmp_path / "outside-sentinel"
        outside.write_bytes(b"preserve")

        result = closure_owner.execute(execution)

        assert result.status.phase == "resolving_closure"
        assert result.status.disposition == "rejected"
        assert result.status.failure is not None
        assert result.status.failure.code == "package_resource_limit_exceeded"
        assert result.candidate is None
        assert result.cleanup_status is None
        assert source_authority.authorize_calls == 1
        assert resolver.calls == ([] if case_id == "B-LIMIT-SOLVER" else ["dependency"])
        assert tuple(
            record.evidence_kind for record in resolution_journal.records()
        ) == (
            ("resolution_basis",)
            if case_id == "B-LIMIT-SOLVER"
            else ("resolution_basis", "selection")
        )
        assert tuple(record.evidence_kind for record in evidence_journal.records()) == (
            "authenticated_source",
            "bounded_acquisition",
            "verified_wheel",
        )
        assert cleanup_journal.records() == ()
        assert store.attempt_names() == ()
        assert outside.read_bytes() == b"preserve"
        lifecycle_records = journal.records()
        resolution_records = resolution_journal.records()
        evidence_records = evidence_journal.records()
        replay = closure_owner.execute(execution)
        assert replay.status == result.status
        assert journal.records() == lifecycle_records
        assert resolution_journal.records() == resolution_records
        assert evidence_journal.records() == evidence_records
        assert source_authority.authorize_calls == 1
        assert secret not in repr(result)
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert secret.encode() not in path.read_bytes()
    elif case_id in IMPLEMENTED_B3D_INTEGRITY_MANIFEST_CASES:
        secret = f"manifest-secret-{case_id.lower()}"
        environment = _closure_environment()
        root_source = f"https://packages.example.test/{WHEEL_FILENAME}"
        dependency_source_1 = (
            "https://packages.example.test/dependency-1.0-py3-none-any.whl"
        )
        dependency_source_2 = (
            "https://packages.example.test/dependency-2.0-py3-none-any.whl"
        )
        root_requirements: tuple[str, ...] = ()
        root_requires_python: str | None = None
        dependency_requirements: tuple[str, ...] = ()
        selections: dict[str | tuple[str, str], _ManifestSelection] = {}
        payloads: dict[str, bytes] = {}
        legacy_builder: _LegacyClosureBuilder | None = None

        if case_id == "B-CLOSURE-MISSING":
            root_requirements = ("missing==1",)
        elif case_id in {"B-CLOSURE-DIGEST", "B-CLOSURE-ORIGIN"}:
            root_requirements = ("dependency==2",)
        elif case_id == "B-CLOSURE-MARKER":
            root_requires_python = ">=4"
        elif case_id == "B-CLOSURE-NAME":
            root_requirements = ("dependency==1", "dependency==2")
        elif case_id == "B-CLOSURE-CYCLE":
            root_requirements = ("dependency==2",)
            dependency_requirements = ("acme-plugin==1",)
        elif case_id == "B-CLOSURE-V1":
            legacy_builder = _LegacyClosureBuilder()

        root_payload = _package_wheel_bytes(
            "acme-plugin",
            "1.0",
            requires_dist=root_requirements,
            requires_python=root_requires_python,
        )
        dependency_payload_1 = _package_wheel_bytes("dependency", "1.0")
        dependency_payload_2 = _package_wheel_bytes(
            "dependency",
            "2.0",
            requires_dist=dependency_requirements,
        )
        payloads[root_source] = root_payload
        payloads[dependency_source_1] = dependency_payload_1
        payloads[dependency_source_2] = dependency_payload_2

        if case_id in {"B-CLOSURE-DIGEST", "B-CLOSURE-ORIGIN"}:
            selections["dependency"] = _ManifestSelection(
                version="2.0",
                source=dependency_source_2,
                filename="dependency-2.0-py3-none-any.whl",
                digest=(
                    "f" * 64
                    if case_id == "B-CLOSURE-DIGEST"
                    else sha256(dependency_payload_2).hexdigest()
                ),
            )
        elif case_id == "B-CLOSURE-NAME":
            selections[("dependency", "==1")] = _ManifestSelection(
                version="1.0",
                source=dependency_source_1,
                filename="dependency-1.0-py3-none-any.whl",
                digest=sha256(dependency_payload_1).hexdigest(),
            )
            selections[("dependency", "==2")] = _ManifestSelection(
                version="2.0",
                source=dependency_source_2,
                filename="dependency-2.0-py3-none-any.whl",
                digest=sha256(dependency_payload_2).hexdigest(),
            )
        elif case_id == "B-CLOSURE-CYCLE":
            selections["dependency"] = _ManifestSelection(
                version="2.0",
                source=dependency_source_2,
                filename="dependency-2.0-py3-none-any.whl",
                digest=sha256(dependency_payload_2).hexdigest(),
            )
            selections["acme-plugin"] = _ManifestSelection(
                version="1.0",
                source=root_source,
                filename=WHEEL_FILENAME,
                digest=sha256(root_payload).hexdigest(),
            )

        resolver = _ManifestResolver(selections)
        (
            kernel,
            _artifact_owner,
            journal,
            evidence_journal,
            cleanup_journal,
            store,
            source_authority,
            closure_owner,
            resolution_journal,
            _resolver,
        ) = _b3d_owner(
            tmp_path,
            case_id=case_id,
            secret=secret,
            root_payload=root_payload,
            payloads=payloads,
            resolver=resolver,
            closure_builder=legacy_builder,
        )
        classified = kernel.submit(
            _request(
                source=(
                    f"https://user:{secret}@packages.example.test/{WHEEL_FILENAME}"
                    f"?token={secret}#{secret}"
                ),
                environment_fingerprint=environment.fingerprint,
            )
        )
        execution = PackageClosureExecutionRequestV2(
            artifact=_artifact_execution(classified, secret=secret),
            resolution_environment=environment,
            budgets=PackageClosureBudgetV1(),
        )
        outside = tmp_path / "outside-sentinel"
        outside.write_bytes(b"preserve")

        result = closure_owner.execute(execution)

        expected_code = {
            "B-CLOSURE-MISSING": "package_closure_artifact_invalid",
            "B-CLOSURE-DIGEST": "package_closure_artifact_invalid",
            "B-CLOSURE-ORIGIN": "package_closure_artifact_invalid",
            "B-CLOSURE-MARKER": "package_closure_conflict",
            "B-CLOSURE-NAME": "package_closure_conflict",
            "B-CLOSURE-CYCLE": "package_closure_conflict",
            "B-CLOSURE-V1": "package_closure_evidence_unsupported",
        }[case_id]
        expected_resolver_calls = {
            "B-CLOSURE-MISSING": ["missing"],
            "B-CLOSURE-DIGEST": ["dependency"],
            "B-CLOSURE-ORIGIN": ["dependency"],
            "B-CLOSURE-MARKER": [],
            "B-CLOSURE-NAME": ["dependency", "dependency"],
            "B-CLOSURE-CYCLE": ["dependency", "acme-plugin"],
            "B-CLOSURE-V1": [],
        }[case_id]
        expected_source_calls = {
            "B-CLOSURE-MISSING": 1,
            "B-CLOSURE-DIGEST": 2,
            "B-CLOSURE-ORIGIN": 2,
            "B-CLOSURE-MARKER": 1,
            "B-CLOSURE-NAME": 2,
            "B-CLOSURE-CYCLE": 2,
            "B-CLOSURE-V1": 1,
        }[case_id]
        expected_selection_count = {
            "B-CLOSURE-MISSING": 0,
            "B-CLOSURE-DIGEST": 1,
            "B-CLOSURE-ORIGIN": 1,
            "B-CLOSURE-MARKER": 0,
            "B-CLOSURE-NAME": 2,
            "B-CLOSURE-CYCLE": 2,
            "B-CLOSURE-V1": 0,
        }[case_id]
        expected_dependency_evidence = case_id in {
            "B-CLOSURE-DIGEST",
            "B-CLOSURE-NAME",
            "B-CLOSURE-CYCLE",
        }
        assert result.status.phase == "resolving_closure"
        assert result.status.disposition == "rejected"
        assert result.status.failure is not None
        assert result.status.failure.code == expected_code
        assert result.candidate is None
        assert result.cleanup_status is None
        assert resolver.calls == expected_resolver_calls
        assert source_authority.authorize_calls == expected_source_calls
        assert (
            tuple(record.evidence_kind for record in resolution_journal.records())
            == ("resolution_basis",) + ("selection",) * expected_selection_count
        )
        expected_evidence_kinds = (
            "authenticated_source",
            "bounded_acquisition",
            "verified_wheel",
        )
        assert tuple(
            record.evidence_kind for record in evidence_journal.records()
        ) == expected_evidence_kinds * (2 if expected_dependency_evidence else 1)
        assert cleanup_journal.records() == ()
        assert store.attempt_names() == ()
        assert store.total_residue_bytes() == 0
        assert outside.read_bytes() == b"preserve"
        assert not (tmp_path / "published").exists()
        assert not (tmp_path / "binding.json").exists()
        assert not (tmp_path / "desired.json").exists()
        lifecycle_records = journal.records()
        resolution_records = resolution_journal.records()
        evidence_records = evidence_journal.records()
        replay = closure_owner.execute(execution)
        assert replay.status == result.status
        assert journal.records() == lifecycle_records
        assert resolution_journal.records() == resolution_records
        assert evidence_journal.records() == evidence_records
        assert resolver.calls == expected_resolver_calls
        assert source_authority.authorize_calls == expected_source_calls
        if legacy_builder is not None:
            assert legacy_builder.calls == 1
        assert secret not in repr(result)
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert secret.encode() not in path.read_bytes()
    elif case_id in IMPLEMENTED_B3D_RECOVERY_MANIFEST_CASES:
        secret = f"manifest-secret-{case_id.lower()}"
        environment = _closure_environment()
        (
            kernel,
            artifact_owner,
            journal,
            evidence_journal,
            cleanup_journal,
            store,
            source_authority,
            closure_owner,
            resolution_journal,
            resolver,
        ) = _b3d_owner(tmp_path, case_id=case_id, secret=secret)
        classified = kernel.submit(
            _request(
                source=(
                    f"https://user:{secret}@packages.example.test/{WHEEL_FILENAME}"
                    f"?token={secret}#{secret}"
                ),
                environment_fingerprint=environment.fingerprint,
            )
        )
        artifact_execution = _artifact_execution(classified, secret=secret)
        execution = PackageClosureExecutionRequestV2(
            artifact=artifact_execution,
            resolution_environment=environment,
            budgets=PackageClosureBudgetV1(),
        )
        if case_id == "B-CRASH-RESOLVING":
            request = kernel.journal.request(classified.operation_id)
            assert request is not None
            resolution_journal.bind_basis(
                PackageClosureResolutionBasisV1(
                    operation_id=classified.operation_id,
                    attempt_epoch=classified.attempt_epoch,
                    request_fingerprint=classified.request_fingerprint,
                    policy_revision=request.policy_revision,
                    quota_profile_revision=request.quota_profile_revision,
                    resolution_environment=environment,
                    budgets=execution.budgets,
                )
            )
            artifact_result = artifact_owner.execute(artifact_execution)
            assert artifact_result.candidate is not None
            current = kernel.advance(
                classified.operation_id,
                next_phase="resolving_closure",
                expected_phase="extracted",
                expected_journal_revision=artifact_result.status.journal_revision,
                expected_attempt_epoch=artifact_result.status.attempt_epoch,
            )
            artifact_result.candidate.suspend_for_recovery()
            expected_resolution_kinds = ("resolution_basis",)
        else:
            closure_result = closure_owner.execute(execution)
            assert closure_result.candidate is not None
            current = closure_result.status
            closure_result.candidate.suspend_for_recovery()
            expected_resolution_kinds = (
                "resolution_basis",
                "verified_plan",
            )
        assert current.phase == (
            "resolving_closure"
            if case_id == "B-CRASH-RESOLVING"
            else "closure_verified"
        )
        evidence_before = evidence_journal.records()
        resolution_before = resolution_journal.records()
        lifecycle_before = journal.records()
        source_calls = source_authority.authorize_calls

        interrupted = kernel.interrupt(
            current.operation_id,
            expected_phase=current.phase,
            expected_journal_revision=current.journal_revision,
            expected_attempt_epoch=current.attempt_epoch,
        )

        assert interrupted.disposition == "retryable_failure"
        assert interrupted.failure is not None
        assert interrupted.failure.code == "package_operation_interrupted"
        assert interrupted.failure.retry_domain == "operation"
        assert (
            tuple(record.evidence_kind for record in resolution_before)
            == expected_resolution_kinds
        )
        assert len(journal.records()) == len(lifecycle_before) + 1
        replay = closure_owner.execute(execution)
        assert replay.status == interrupted
        assert replay.candidate is None
        assert evidence_journal.records() == evidence_before
        assert resolution_journal.records() == resolution_before
        assert source_authority.authorize_calls == source_calls == 1
        assert resolver.calls == 0
        assert cleanup_journal.records() == ()
        assert len(store.attempt_names()) == 1
        assert store.total_residue_bytes() <= 512 * 1024
        assert secret not in repr(interrupted)
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert secret.encode() not in path.read_bytes()
    elif case_id.startswith("B-CRASH-") and case_id not in {
        "B-CRASH-ACCEPTED",
        "B-CRASH-CLASSIFIED",
    }:
        target_phase = {
            "B-CRASH-ACQUIRING": "acquiring",
            "B-CRASH-ACQUIRED": "acquired",
            "B-CRASH-INSPECTING": "inspecting",
            "B-CRASH-EXTRACTED": "extracted",
        }[case_id]
        secret = f"manifest-secret-{case_id.lower()}"
        (
            kernel,
            artifact_owner,
            journal,
            evidence_journal,
            cleanup_journal,
            store,
            source_authority,
        ) = _b2_owner(
            tmp_path,
            case_id=case_id,
            secret=secret,
            payload=_wheel_bytes(),
        )
        classified = kernel.submit(
            _request(
                source=(
                    f"https://user:{secret}@packages.example.test/{WHEEL_FILENAME}"
                    f"?token={secret}#{secret}"
                )
            )
        )
        current, candidate, execution = _land_artifact_phase(
            kernel=kernel,
            artifact_owner=artifact_owner,
            evidence_journal=evidence_journal,
            classified=classified,
            target_phase=target_phase,
            secret=secret,
        )
        if candidate is not None:
            candidate.suspend_for_recovery()
        outside = tmp_path / "outside-sentinel"
        outside.write_bytes(b"preserve")
        evidence_before = evidence_journal.records()
        records_before = journal.records()
        source_calls = source_authority.authorize_calls

        interrupted = kernel.interrupt(
            current.operation_id,
            expected_phase=current.phase,
            expected_journal_revision=current.journal_revision,
            expected_attempt_epoch=current.attempt_epoch,
        )

        assert interrupted.phase == target_phase
        assert interrupted.disposition == "retryable_failure"
        assert interrupted.request_fingerprint == current.request_fingerprint
        assert interrupted.attempt_epoch == current.attempt_epoch
        assert interrupted.failure is not None
        assert interrupted.failure.code == "package_operation_interrupted"
        assert interrupted.failure.retry_domain == "operation"
        assert interrupted.failure.operator_action == "retry"
        assert evidence_journal.records() == evidence_before
        assert len(journal.records()) == len(records_before) + 1
        record_count = len(journal.records())
        assert (
            kernel.interrupt(
                current.operation_id,
                expected_phase=current.phase,
                expected_journal_revision=current.journal_revision,
                expected_attempt_epoch=current.attempt_epoch,
            )
            == interrupted
        )
        assert len(journal.records()) == record_count
        assert artifact_owner.execute(execution).status == interrupted
        assert source_authority.authorize_calls == source_calls
        assert cleanup_journal.records() == ()
        assert len(store.attempt_names()) <= 1
        assert store.total_residue_bytes() <= 512 * 1024
        assert outside.read_bytes() == b"preserve"
        assert secret not in repr(interrupted)
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert secret.encode() not in path.read_bytes()
    elif case_id == "B-STATE-REJECT-CLEANUP":
        secret = f"manifest-secret-{case_id.lower()}"
        (
            kernel,
            artifact_owner,
            journal,
            evidence_journal,
            cleanup_journal,
            store,
            source_authority,
        ) = _b2_owner(
            tmp_path,
            case_id=case_id,
            secret=secret,
            payload=b"not-a-wheel",
            cleanup_debt=True,
        )
        classified = kernel.submit(
            _request(
                source=(
                    f"https://user:{secret}@packages.example.test/rejected.whl"
                    f"?token={secret}#{secret}"
                )
            )
        )
        execution = _artifact_execution(classified, secret=secret)
        outside = tmp_path / "outside-sentinel"
        outside.write_bytes(b"preserve")

        result = artifact_owner.execute(execution)

        assert result.status.phase == "inspecting"
        assert result.status.disposition == "rejected"
        assert result.status.failure is not None
        assert result.status.failure.code == "package_archive_malformed"
        assert result.cleanup_status is not None
        assert result.cleanup_status.disposition == "cleanup_retryable"
        assert result.cleanup_status.failure is not None
        assert (
            result.cleanup_status.failure.code == "package_quarantine_cleanup_retryable"
        )
        assert result.cleanup_status.failure.retry_domain == "cleanup"
        assert result.cleanup_status.failure.operator_action == "repair"
        assert len(evidence_journal.records()) == 2
        assert len(cleanup_journal.records()) == 1
        assert len(store.attempt_names()) == 1
        assert store.total_residue_bytes() <= 512 * 1024
        assert outside.read_bytes() == b"preserve"
        operation_records = journal.records()
        cleanup_records = cleanup_journal.records()
        replay = artifact_owner.execute(execution)
        assert replay.status == result.status
        assert replay.cleanup_status is None
        assert journal.records() == operation_records
        assert cleanup_journal.records() == cleanup_records
        repaired = PackageQuarantineCleanupOwner(
            journal=cleanup_journal,
            store=store,
        ).repair(
            result.cleanup_status.target.cleanup_id,
            expected_cleanup_revision=result.cleanup_status.cleanup_revision,
        )
        assert repaired.disposition == "cleanup_complete"
        assert store.attempt_names() == ()
        assert source_authority.authorize_calls == 1
        assert secret not in repr(result)
    elif case_id == "B-TYPE-HARDLINK":
        if os.name != "posix":
            pytest.skip("hardlink normalization requires a native POSIX filesystem")
        secret = f"manifest-secret-{case_id.lower()}"
        payload, source_first, source_second, archive_names = _hardlinked_source_wheel(
            tmp_path
        )
        first_source_stat = source_first.stat()
        second_source_stat = source_second.stat()
        assert (first_source_stat.st_dev, first_source_stat.st_ino) == (
            second_source_stat.st_dev,
            second_source_stat.st_ino,
        )
        assert first_source_stat.st_nlink >= 2
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            infos = tuple(archive.getinfo(name) for name in archive_names)
            assert all(info.create_system == 3 for info in infos)
            assert all(
                stat.S_IFMT(info.external_attr >> 16) == stat.S_IFREG for info in infos
            )
            assert all(info.extra == b"" for info in infos)
            assert archive.read(archive_names[0]) == archive.read(archive_names[1])

        (
            kernel,
            artifact_owner,
            journal,
            evidence_journal,
            cleanup_journal,
            store,
            source_authority,
        ) = _b2_owner(
            tmp_path / "runtime",
            case_id=case_id,
            secret=secret,
            payload=payload,
        )
        classified = kernel.submit(
            _request(
                source=(
                    f"https://user:{secret}@packages.example.test/{WHEEL_FILENAME}"
                    f"?token={secret}#{secret}"
                )
            )
        )
        outside = tmp_path / "outside-sentinel"
        outside.write_bytes(b"preserve")

        result = artifact_owner.execute(_artifact_execution(classified, secret=secret))

        assert result.status.phase == "extracted"
        assert result.status.disposition == "active"
        assert result.status.failure is None
        assert result.candidate is not None
        tree = result.candidate._acquired._attempt._attempt_path / "tree"
        extracted = tuple(
            tree.joinpath(*name.split("/")).stat() for name in archive_names
        )
        assert all(stat.S_ISREG(metadata.st_mode) for metadata in extracted)
        assert extracted[0].st_ino != extracted[1].st_ino
        assert all(metadata.st_nlink == 1 for metadata in extracted)
        assert len(evidence_journal.records()) == 3
        assert cleanup_journal.records() == ()
        assert source_authority.authorize_calls == 1
        assert outside.read_bytes() == b"preserve"
        assert secret not in repr(result)
        operation_records = journal.records()
        result.candidate.cleanup()
        assert store.attempt_names() == ()
        assert journal.records() == operation_records
    elif case_id in (
        IMPLEMENTED_B2H_MANIFEST_CASES + IMPLEMENTED_B2I_WINDOWS_MANIFEST_CASES
    ):
        fixture = _inspection_fixture(case_id)
        secret = f"manifest-secret-{case_id.lower()}"
        (
            kernel,
            artifact_owner,
            journal,
            evidence_journal,
            cleanup_journal,
            store,
            source_authority,
        ) = _b2_owner(
            tmp_path,
            case_id=case_id,
            secret=secret,
            payload=fixture.payload,
            inspection_budgets=fixture.budgets,
            wheel_verifier=fixture.verifier,
            supported_tags=fixture.supported_tags,
        )
        classified = kernel.submit(
            _request(
                source=(
                    f"https://user:{secret}@packages.example.test/hostile.whl"
                    f"?token={secret}#{secret}"
                )
            )
        )
        execution = PackageArtifactExecutionRequestV1(
            operation_id=classified.operation_id,
            request_fingerprint=classified.request_fingerprint,
            expected_attempt_epoch=classified.attempt_epoch,
            wheel_filename=fixture.wheel_filename,
            credential_reference=f"opaque:{secret}",
        )
        outside = tmp_path / "outside-sentinel"
        outside.write_bytes(b"preserve")
        process_marker = tmp_path / "artifact-process-marker"

        result = artifact_owner.execute(execution)

        if case_id.startswith("B-ARCH-"):
            expected_code = "package_archive_malformed"
        elif case_id in {
            "B-PATH-ABSOLUTE",
            "B-PATH-TRAVERSAL",
            "B-PATH-EMPTY",
            "B-PATH-COLLISION-SEP",
            "B-PATH-WIN-ROOT",
            "B-PATH-WIN-ADS",
            "B-PATH-WIN-RESERVED",
            "B-PATH-WIN-TRAILING",
        }:
            expected_code = "package_archive_path_rejected"
        elif case_id in {
            "B-PATH-COLLISION-UNICODE",
            "B-PATH-COLLISION-CASE",
        }:
            expected_code = "package_archive_name_collision"
        elif case_id.startswith("B-TYPE-"):
            expected_code = "package_archive_entry_type_rejected"
        elif case_id.startswith("B-LIMIT-"):
            expected_code = "package_resource_limit_exceeded"
        elif case_id in {"B-WHEEL-SDIST", "B-WHEEL-ZIP", "B-WHEEL-TAGS"}:
            expected_code = "package_artifact_type_rejected"
        elif case_id == "B-WHEEL-METADATA":
            expected_code = "package_wheel_metadata_invalid"
        else:
            expected_code = "package_wheel_record_invalid"
        expected_phase = (
            "extracted" if case_id.startswith("B-WHEEL-RECORD-") else "inspecting"
        )
        assert result.status.phase == expected_phase
        assert result.status.disposition == "rejected"
        assert result.status.failure is not None
        assert result.status.failure.code == expected_code
        assert result.candidate is None
        assert result.cleanup_status is None
        assert source_authority.authorize_calls == 1
        assert source_authority.stream is not None
        assert source_authority.stream.requests_started == 1
        assert source_authority.stream.writes_started == 1
        evidence = evidence_journal.records()
        assert tuple(record.evidence_kind for record in evidence) == (
            "authenticated_source",
            "bounded_acquisition",
        )
        assert cleanup_journal.records() == ()
        assert store.attempt_names() == ()
        assert store.total_residue_bytes() == 0
        assert outside.read_bytes() == b"preserve"
        assert not process_marker.exists()
        assert "acme_plugin" not in sys.modules
        records = journal.records()
        replay = artifact_owner.execute(execution)
        assert replay.status == result.status
        assert replay.candidate is None
        assert journal.records() == records
        assert source_authority.authorize_calls == 1
        assert secret not in repr(result)
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert secret.encode() not in path.read_bytes()
    else:  # pragma: no cover - the parametrization is deliberately closed
        raise AssertionError(f"Unhandled PLC9B manifest case: {case_id}")

    if case_id in IMPLEMENTED_B1_MANIFEST_CASES:
        _assert_no_capability_side_effect(tmp_path)


def _assert_classification(status: object, *, decision: str, code: str | None) -> None:
    assert getattr(status, "phase") == "classified"
    classification = getattr(status, "classification")
    assert classification is not None
    assert classification.decision == decision
    failure = getattr(status, "failure")
    if code is None:
        assert getattr(status, "disposition") == "active"
        assert failure is None
    else:
        assert getattr(status, "disposition") == "rejected"
        assert failure is not None
        assert failure.code == code


def _assert_replay_is_single_owner(
    owner: PackageLifecycleOwner,
    journal: PackageLifecycleJournal,
) -> None:
    current = journal.status("manifest-operation")
    records = journal.records()
    assert owner.submit(_request()) == current
    assert journal.records() == records


def _assert_no_capability_side_effect(tmp_path: Path) -> None:
    names = {path.name for path in tmp_path.rglob("*") if path.is_file()}
    assert names <= {"package-lifecycle.jsonl", "package-lifecycle.jsonl.lock"}
