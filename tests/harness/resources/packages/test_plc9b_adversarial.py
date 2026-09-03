from __future__ import annotations

import base64
import csv
import inspect
import io
import json
import os
import shutil
import socket
import stat
import struct
import subprocess
import sys
import zipfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from threading import Lock

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
from loushang.harness.resources.packages.plugin_lifecycle.adoption import (
    PackageLegacyAdoptionOwner,
    PackageLegacyAdoptionRequestV1,
    PackageLegacyStateEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.adoption_transaction import (
    PackageLegacyAdoptionTransactionAdapter,
)
from loushang.harness.resources.packages.plugin_lifecycle.cleanup import (
    PackageQuarantineCleanupJournal,
    PackageQuarantineCleanupOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    PackageClosureBudgetV1,
    PackageClosureVerifier,
    PackageResolutionEnvironmentV1,
    ResolvedPackageRequirementV1,
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
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
from loushang.harness.resources.packages.plugin_lifecycle.commit_admission import (
    PackageCommitAdmissionOwner,
    PackageCommitAdmissionRequestV1,
    PackageCommitLifecycleOwner,
    PackagePublicationReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    DependencyClosureLockV2,
    PluginRevisionRefV1,
    VerifiedArtifactRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
    PackageEpochFenceReceiptV1,
    PackageEpochFenceRequestV1,
    PackageEpochLeaseSnapshotV1,
    PackageEpochRuntimeAdmissionOwner,
    PackageEpochRuntimeAdmissionRequestV1,
    PackageEpochRuntimeAdmissionResultV1,
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PACKAGE_PRE_B_SNAPSHOT_DOMAINS,
    PackageOfflineRestoreOwner,
    PackageOfflineRestoreRequestV1,
    PackageOfflineRestoreSnapshotEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.phase_evidence import (
    PackageArtifactEvidenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverQuiescenceReceiptV1,
    PackageEpochCutoverSnapshotReceiptV1,
    PackagePosixEpochCutoverOwner,
    PackagePosixEpochCutoverRequestV1,
    PackagePosixEpochCutoverResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    PosixPackageDependencyMaterializationStore,
    PosixPackagePluginRootMaterializationStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_offline_restore import (
    PackagePosixOfflineRestoreMaterializer,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleCancelRequestV1,
    PackageLifecyclePhase,
    PackageLifecycleRequestV1,
    PackageLifecycleRetryRequestV1,
    PackageLifecycleStatusV1,
    PluginBoundPackageClassificationV1,
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageDependencyPinReceiptV1,
    PackageDesiredStateCommitRequestV1,
    PackageDesiredStateCommitResultV1,
    PackageRetentionHandoffJournal,
    PackageRetentionHandoffOwner,
    PackageRetentionHandoffReceiptV1,
    PackageRetentionHandoffRequestV1,
    PackageRetentionHandoffResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.runtime import (
    PackageArtifactExecutionRequestV1,
    PackageArtifactLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackageArtifactStagingJournal,
    PackageArtifactStagingReceiptV1,
    PackageArtifactStagingRequestV1,
    PackagePluginRootTargetV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging_set_runtime import (
    PackageStagingSetLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pin_runtime import (
    PackageTransactionPinLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
    PackageTransactionPinReceiptV1,
    PackageTransactionPinRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    PackageWheelVerifier,
    VerifiedWheelCandidate,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    PackageWindowsEpochCutoverOwner,
    PackageWindowsEpochCutoverRequestV1,
    PackageWindowsEpochCutoverResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_materialization import (
    WindowsPackageDependencyMaterializationStore,
    WindowsPackagePluginRootMaterializationStore,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductEntrypoint,
    PackageProductLifecycleRouter,
    PackageProductPublishAttemptV1,
    PackageProductRouteRequestV1,
)
from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
)
from loushang.harness.sandbox.package_legacy_runtime import (
    PackageLinuxLegacyRuntimeActivationOwner,
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
IMPLEMENTED_B3E_PIN_MANIFEST_CASES = ("B-CRASH-PINNED",)
IMPLEMENTED_B3E_STAGING_SET_MANIFEST_CASES = (
    "B-CRASH-STAGING",
    "B-CRASH-SET",
)
IMPLEMENTED_B3E3C1_POSIX_MANIFEST_CASES = (
    "B-PUB-PRECREATE",
    "B-PUB-POSIX-ROOT-SWAP",
    "B-PUB-POSIX-ANCESTOR-SWAP",
    "B-PUB-POSIX-HANDLE-SUCCESS",
    "B-PUB-POSIX-HANDLE-REJECT",
)
IMPLEMENTED_B3E3C2_WINDOWS_MANIFEST_CASES = (
    "B-PUB-SWAP-WINDOWS",
    "B-PUB-WIN-ROOT-ABA",
    "B-PUB-WIN-ANCESTOR-ABA",
    "B-PUB-WIN-HANDLE-SUCCESS",
    "B-PUB-WIN-HANDLE-REJECT",
)
IMPLEMENTED_B3E3C3_SETTLEMENT_MANIFEST_CASES = (
    "B-PUB-COLLISION",
    "B-PUB-REUSE",
)
IMPLEMENTED_B4A_COMMIT_ADMISSION_MANIFEST_CASES = (
    "B-PUB-UNCOMMITTED",
    "B-ADMISSION-DEPENDENCY",
    "B-ADMISSION-WRONG-SET",
    "B-ADMISSION-WRONG-REQUEST",
    "B-ADMISSION-WRONG-OPERATION",
    "B-ADMISSION-WRONG-SCOPE",
    "B-ADMISSION-WRONG-PLUGIN",
    "B-ADMISSION-DIGEST-TAMPER",
)
IMPLEMENTED_B4B_RETENTION_HANDOFF_MANIFEST_CASES = (
    "B-HANDOFF-BEFORE-DESIRED",
    "B-HANDOFF-AFTER-DESIRED",
    "B-HANDOFF-AFTER-SETTLEMENT",
    "B-HANDOFF-DESIRED-REJECT",
    "B-HANDOFF-STALE-RECEIPT",
    "B-HANDOFF-CONCURRENT-REPLAY",
)
IMPLEMENTED_B4C0_EPOCH_ADMISSION_MANIFEST_CASES = (
    "B-COMPAT-EPOCH",
    "B-COMPAT-MIXED",
)
IMPLEMENTED_B4C1_POSIX_EPOCH_CUTOVER_MANIFEST_CASES = (
    "B-COMPAT-CUTOVER-POSIX",
    "B-COMPAT-PREFENCE-LIVE-POSIX",
)
IMPLEMENTED_B4C2_WINDOWS_EPOCH_CUTOVER_MANIFEST_CASES = (
    "B-COMPAT-CUTOVER-WINDOWS",
    "B-COMPAT-PREFENCE-LIVE-WINDOWS",
)
IMPLEMENTED_B4C3C_LINUX_OFFLINE_RESTORE_MANIFEST_CASES = (
    "B-COMPAT-OFFLINE-RESTORE-POSIX",
)
IMPLEMENTED_B4C4D_LINUX_ADOPTION_MANIFEST_CASES = ("B-COMPAT-ADOPT",)
IMPLEMENTED_B4C4E_LINUX_ADOPTION_FAILURE_MANIFEST_CASES = (
    "B-COMPAT-ADOPT-UNAUTHORIZED",
    "B-COMPAT-ADOPT-UNAVAILABLE",
)
IMPLEMENTED_B4C4F_LINUX_ADOPTION_COMMITTED_CRASH_MANIFEST_CASES = (
    "B-COMPAT-ADOPT-CRASH-AFTER-COMMITTED",
)
IMPLEMENTED_B4C4G_LINUX_ADOPTION_PRECOMMIT_CRASH_MANIFEST_CASES = (
    "B-COMPAT-ADOPT-CRASH",
)
IMPLEMENTED_B4D_STATE_MANIFEST_CASES = (
    "B-CRASH-COMMITTED",
    "B-CONCUR-SAME",
    "B-CONCUR-STALE",
    "B-STATE-CANCEL-EARLY",
    "B-STATE-CANCEL-PINNED",
    "B-STATE-STATUS",
    "B-COMPAT-LEGACY",
    "B-COMPAT-ROLLFORWARD",
)
IMPLEMENTED_B4D_LINUX_PIPELINE_MANIFEST_CASES = (
    "B-CLASS-CHANGED",
    "B-NOEXEC-IMPORT",
    "B-NOEXEC-SETUP",
    "B-NOEXEC-ENTRYPOINT",
    "B-NOEXEC-ADJACENT",
    "B-STATE-SECRETS",
)
IMPLEMENTED_B5_ROUTING_MANIFEST_CASES = (
    "B-ENTRY-CLI",
    "B-ENTRY-RPC",
    "B-ENTRY-SESSION",
    "B-ENTRY-STARTUP",
    "B-ENTRY-OPERATIONS",
    "B-ENTRY-MATERIALIZER",
    "B-ENTRY-PUBLISH",
)
ADOPTION_PRECOMMIT_CRASH_PHASES: tuple[PackageLifecyclePhase, ...] = (
    "acquiring",
    "acquired",
    "inspecting",
    "extracted",
    "resolving_closure",
    "closure_verified",
    "transaction_pinned",
    "staging",
    "set_published",
)
PLANNED_B3E3C_MATERIALIZATION_MANIFEST_CASES: tuple[str, ...] = ()
PLANNED_B4_COMMIT_ADMISSION_MANIFEST_CASES: tuple[str, ...] = ()

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
    + IMPLEMENTED_B3E_PIN_MANIFEST_CASES
    + IMPLEMENTED_B3E_STAGING_SET_MANIFEST_CASES
    + IMPLEMENTED_B3E3C1_POSIX_MANIFEST_CASES
    + IMPLEMENTED_B3E3C3_SETTLEMENT_MANIFEST_CASES
    + IMPLEMENTED_B4A_COMMIT_ADMISSION_MANIFEST_CASES
    + IMPLEMENTED_B4B_RETENTION_HANDOFF_MANIFEST_CASES
    + IMPLEMENTED_B4C0_EPOCH_ADMISSION_MANIFEST_CASES
    + (
        IMPLEMENTED_B4C1_POSIX_EPOCH_CUTOVER_MANIFEST_CASES
        if os.name == "posix"
        else ()
    )
    + (IMPLEMENTED_B3E3C2_WINDOWS_MANIFEST_CASES if os.name == "nt" else ())
    + (IMPLEMENTED_B4C2_WINDOWS_EPOCH_CUTOVER_MANIFEST_CASES if os.name == "nt" else ())
    + (
        IMPLEMENTED_B4C3C_LINUX_OFFLINE_RESTORE_MANIFEST_CASES
        if sys.platform.startswith("linux")
        else ()
    )
    + (
        IMPLEMENTED_B4C4D_LINUX_ADOPTION_MANIFEST_CASES
        if sys.platform.startswith("linux")
        else ()
    )
    + (
        IMPLEMENTED_B4C4E_LINUX_ADOPTION_FAILURE_MANIFEST_CASES
        if sys.platform.startswith("linux")
        else ()
    )
    + (
        IMPLEMENTED_B4C4F_LINUX_ADOPTION_COMMITTED_CRASH_MANIFEST_CASES
        if sys.platform.startswith("linux")
        else ()
    )
    + (
        IMPLEMENTED_B4C4G_LINUX_ADOPTION_PRECOMMIT_CRASH_MANIFEST_CASES
        if sys.platform.startswith("linux")
        else ()
    )
    + IMPLEMENTED_B4D_STATE_MANIFEST_CASES
    + (
        IMPLEMENTED_B4D_LINUX_PIPELINE_MANIFEST_CASES
        if sys.platform.startswith("linux")
        else ()
    )
    + IMPLEMENTED_B5_ROUTING_MANIFEST_CASES
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
class _ChangedClassificationRecheck:
    def recheck(
        self,
        _request: PackageLifecycleRequestV1,
        prior: PluginBoundPackageClassificationV1,
    ) -> PluginBoundPackageClassificationV1:
        facts = PackageClassificationFactsV1(
            facts=prior.basis_facts.facts,
            policy_revision="classification-policy:changed",
            classifier_epoch=prior.classifier_epoch + 1,
        )
        return PluginBoundPackageClassificationV1(
            decision=prior.decision,
            request_fingerprint=prior.request_fingerprint,
            basis_facts=facts,
            policy_revision=facts.policy_revision,
            classifier_epoch=facts.classifier_epoch,
            canonical_source_identity=prior.canonical_source_identity,
        )


@dataclass
class _TransactionPinRetentionState:
    receipts: dict[str, PackageTransactionPinReceiptV1] = field(default_factory=dict)
    calls: list[PackageTransactionPinRequestV1] = field(default_factory=list)
    physical_acquisitions: int = 0


@dataclass
class _TransactionPinRetentionOwner:
    state: _TransactionPinRetentionState = field(
        default_factory=_TransactionPinRetentionState
    )

    @property
    def receipts(self) -> dict[str, PackageTransactionPinReceiptV1]:
        return self.state.receipts

    @property
    def calls(self) -> list[PackageTransactionPinRequestV1]:
        return self.state.calls

    @property
    def physical_acquisitions(self) -> int:
        return self.state.physical_acquisitions

    def acquire(
        self,
        request: PackageTransactionPinRequestV1,
    ) -> PackageTransactionPinReceiptV1:
        self.calls.append(request)
        existing = self.receipts.get(request.operation_id)
        if existing is not None:
            if existing.pin_request != request:
                raise RuntimeError("transaction pin request changed")
            return existing
        receipt = PackageTransactionPinReceiptV1.acquire(
            request,
            pin_id="f" * 64,
            owner_identity="manifest-retention-owner",
            owner_revision=1,
            lease_id="manifest-transaction-pin",
            lease_revision=1,
        )
        self.receipts[request.operation_id] = receipt
        self.state.physical_acquisitions += 1
        return receipt

    def release(
        self,
        receipt: PackageTransactionPinReceiptV1,
        *,
        transition_evidence_ref: str,
    ) -> PackageTransactionPinReceiptV1:
        return PackageTransactionPinReceiptV1.transition(
            receipt,
            state="released",
            owner_revision=receipt.owner_revision + 1,
            lease_revision=receipt.lease_revision + 1,
            transition_evidence_ref=transition_evidence_ref,
        )


class _ManifestCrashEdge(RuntimeError):
    pass


class _CrashAfterPhasePackageOwner(PackageLifecycleOwner):
    def __init__(
        self,
        *,
        journal: PackageLifecycleJournal,
        facts: PackageClassificationFactsV1,
        crash_after: PackageLifecyclePhase,
    ) -> None:
        super().__init__(
            journal=journal,
            classification_authority=_Authority(facts),
            enabled=True,
        )
        self._crash_after: PackageLifecyclePhase | None = crash_after

    def advance(
        self,
        operation_id: str,
        *,
        next_phase: PackageLifecyclePhase,
        expected_phase: PackageLifecyclePhase,
        expected_journal_revision: int,
        expected_attempt_epoch: int,
    ) -> PackageLifecycleStatusV1:
        status = super().advance(
            operation_id,
            next_phase=next_phase,
            expected_phase=expected_phase,
            expected_journal_revision=expected_journal_revision,
            expected_attempt_epoch=expected_attempt_epoch,
        )
        if self._crash_after == next_phase:
            self._crash_after = None
            raise _ManifestCrashEdge(next_phase)
        return status


@dataclass
class _ManifestRootTargetAuthorityState:
    calls: int = 0


@dataclass
class _ManifestRootTargetAuthority:
    state: _ManifestRootTargetAuthorityState = field(
        default_factory=_ManifestRootTargetAuthorityState
    )

    @property
    def calls(self) -> int:
        return self.state.calls

    def issue_target(
        self,
        request: PackageLifecycleRequestV1,
        _classification: PluginBoundPackageClassificationV1,
    ) -> PackagePluginRootTargetV1:
        self.state.calls += 1
        return PackagePluginRootTargetV1.create(
            operation_id=request.operation_id,
            request_fingerprint=request.request_fingerprint,
            product_id=request.product_id,
            scope_id=request.scope_id,
            installation_id="manifest-installation",
            plugin_id=request.requested_plugin_id or "manifest-plugin",
            authority_id="manifest-root-target-authority",
            authority_revision="manifest-root-target:1",
        )


@dataclass
class _ManifestDependencyStagingOwner:
    receipts: dict[str, PackageArtifactStagingReceiptV1] = field(default_factory=dict)
    physical_stages: int = 0

    def stage_dependency(
        self,
        request: PackageArtifactStagingRequestV1,
        _candidate: VerifiedWheelCandidate,
    ) -> PackageArtifactStagingReceiptV1:
        existing = self.receipts.get(request.staging_request_id)
        if existing is not None:
            return existing
        node = request.plan_node
        receipt = PackageArtifactStagingReceiptV1.create(
            request,
            stable_ref=VerifiedArtifactRefV1.create(
                store_identity="manifest-dependency-store",
                store_revision=f"dependency:{node.artifact_digest}",
                distribution=node.distribution,
                version=node.version,
                artifact_digest=node.artifact_digest,
                extraction_tree_digest=node.extraction_tree_digest,
            ),
        )
        self.receipts[request.staging_request_id] = receipt
        self.physical_stages += 1
        return receipt


@dataclass
class _ManifestRootStagingOwner:
    receipts: dict[str, PackageArtifactStagingReceiptV1] = field(default_factory=dict)
    physical_stages: int = 0

    def stage_root(
        self,
        request: PackageArtifactStagingRequestV1,
        _candidate: VerifiedWheelCandidate,
    ) -> PackageArtifactStagingReceiptV1:
        existing = self.receipts.get(request.staging_request_id)
        if existing is not None:
            return existing
        target = request.root_target
        assert target is not None
        node = request.plan_node
        receipt = PackageArtifactStagingReceiptV1.create(
            request,
            stable_ref=PluginRevisionRefV1.create(
                store_identity="manifest-plugin-revision-store",
                store_revision=f"plugin:{node.artifact_digest}",
                installation_id=target.installation_id,
                plugin_id=target.plugin_id,
                distribution=node.distribution,
                version=node.version,
                artifact_digest=node.artifact_digest,
                extraction_tree_digest=node.extraction_tree_digest,
            ),
        )
        self.receipts[request.staging_request_id] = receipt
        self.physical_stages += 1
        return receipt


@dataclass
class _ManifestNativeRootStagingState:
    calls: int = 0
    same_receipt: bool = False


@dataclass
class _ManifestNativeRootStagingOwner:
    store: (
        PosixPackagePluginRootMaterializationStore
        | WindowsPackagePluginRootMaterializationStore
    )
    verify_reuse: bool = False
    state: _ManifestNativeRootStagingState = field(
        default_factory=_ManifestNativeRootStagingState
    )

    @property
    def calls(self) -> int:
        return self.state.calls

    @property
    def same_receipt(self) -> bool:
        return self.state.same_receipt

    def authorize_adoption(
        self,
        *,
        store_id: str,
        current_root_identity: str,
        target: PackagePluginRootTargetV1,
    ) -> bool:
        return self.store.authorize_adoption(
            store_id=store_id,
            current_root_identity=current_root_identity,
            target=target,
        )

    def stage_root(
        self,
        request: PackageArtifactStagingRequestV1,
        candidate: VerifiedWheelCandidate,
    ) -> PackageArtifactStagingReceiptV1:
        self.state.calls += 1
        receipt = self.store.stage_root(request, candidate)
        if self.verify_reuse:
            replay = self.store.stage_root(request, candidate)
            assert replay == receipt
            self.state.same_receipt = True
        return receipt


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
        if self.case_id in {"B-ACQ-AUTH", "B-COMPAT-ADOPT-UNAUTHORIZED"}:
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
        elif self.case_id in {"B-ACQ-TIMEOUT", "B-COMPAT-ADOPT-UNAVAILABLE"}:
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

    def reacquire(
        self,
        root: VerifiedWheelCandidate,
        request: PackageRecursiveClosureRequestV2,
    ) -> VerifiedPackageClosureCandidate:
        return self.build(root, request)


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
    operation_id: str = "manifest-operation",
    source: str = "https://packages.example.test/acme.whl",
    environment_fingerprint: str = "e" * 64,
) -> PackageLifecycleIngressRequestV1:
    return PackageLifecycleIngressRequestV1(
        operation_id=operation_id,
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


_LIFECYCLE_PHASES: tuple[PackageLifecyclePhase, ...] = (
    "accepted",
    "classified",
    "acquiring",
    "acquired",
    "inspecting",
    "extracted",
    "resolving_closure",
    "closure_verified",
    "transaction_pinned",
    "staging",
    "set_published",
    "committed",
)


def _advance_lifecycle(
    owner: PackageLifecycleOwner,
    status: PackageLifecycleStatusV1,
    target: PackageLifecyclePhase,
) -> PackageLifecycleStatusV1:
    current = status
    start = _LIFECYCLE_PHASES.index(current.phase)
    end = _LIFECYCLE_PHASES.index(target)
    for next_phase in _LIFECYCLE_PHASES[start + 1 : end + 1]:
        current = owner.advance(
            current.operation_id,
            next_phase=next_phase,
            expected_phase=current.phase,
            expected_journal_revision=current.journal_revision,
            expected_attempt_epoch=current.attempt_epoch,
        )
    return current


@dataclass
class _ManifestProductTransaction:
    owner: PackageLifecycleOwner
    calls: list[PackageProductEntrypoint] = field(default_factory=list)

    def execute(
        self,
        request: PackageProductRouteRequestV1,
        *,
        classified: PackageLifecycleStatusV1,
    ) -> PackageLifecycleStatusV1:
        self.calls.append(request.entrypoint)
        return _advance_lifecycle(self.owner, classified, "committed")


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
    crash_after_phase: PackageLifecyclePhase | None = None,
):
    lifecycle_journal = PackageLifecycleJournal(tmp_path / "package-lifecycle.jsonl")
    kernel = (
        PackageLifecycleOwner(
            journal=lifecycle_journal,
            classification_authority=_Authority(_facts("explicit_plugin_intent")),
            enabled=True,
        )
        if crash_after_phase is None
        else _CrashAfterPhasePackageOwner(
            journal=lifecycle_journal,
            facts=_facts("explicit_plugin_intent"),
            crash_after=crash_after_phase,
        )
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
    clock = (
        _Clock() if case_id in {"B-ACQ-TIMEOUT", "B-COMPAT-ADOPT-UNAVAILABLE"} else None
    )
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
            max_wall_time_ms=(
                5
                if case_id in {"B-ACQ-TIMEOUT", "B-COMPAT-ADOPT-UNAVAILABLE"}
                else 1000
            ),
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
    crash_after_phase: PackageLifecyclePhase | None = None,
):
    components = _b2_owner(
        tmp_path,
        case_id=case_id,
        secret=secret,
        payload=root_payload or _wheel_bytes(),
        payloads=payloads,
        crash_after_phase=crash_after_phase,
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


@dataclass(frozen=True)
class _ManifestCommitAdmissionFixture:
    kernel: PackageLifecycleOwner
    committed_sets: PackageCommittedSetJournal
    pin_journal: PackageTransactionPinJournal
    pin_receipt: PackageTransactionPinReceiptV1
    commit_owner: PackageCommitLifecycleOwner
    admission_owner: PackageCommitAdmissionOwner


def _manifest_commit_admission_fixture(
    tmp_path: Path,
) -> _ManifestCommitAdmissionFixture:
    journal = PackageLifecycleJournal(tmp_path / "package-lifecycle.jsonl")
    kernel = PackageLifecycleOwner(
        journal=journal,
        classification_authority=_Authority(_facts("explicit_plugin_intent")),
        enabled=True,
    )
    status = kernel.submit(_request())
    assert status.classification is not None
    for phase in (
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "resolving_closure",
        "closure_verified",
    ):
        prior = status.phase
        status = kernel.advance(
            status.operation_id,
            next_phase=phase,  # type: ignore[arg-type]
            expected_phase=prior,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )

    dependency = VerifiedClosurePlanNodeV2(
        node_id="manifest-admission-dependency",
        role="dependency",
        distribution="dependency",
        version="2.0",
        canonical_source_identity="https://packages.example.test/dependency.whl",
        source_envelope_fingerprint="1" * 64,
        acquisition_receipt_fingerprint="2" * 64,
        wheel_evidence_fingerprint="3" * 64,
        artifact_digest="4" * 64,
        extraction_tree_digest="5" * 64,
        selected_extras=(),
        requirements=(),
        selected_edges=(),
    )
    root_requirement = ResolvedPackageRequirementV1(
        requirement=NormalizedPackageRequirementV1.parse("dependency==2.0"),
        marker_applies=True,
        selected_node_id=dependency.node_id,
        expected_source_identity=dependency.canonical_source_identity,
        expected_artifact_digest=dependency.artifact_digest,
    )
    root = VerifiedClosurePlanNodeV2(
        node_id="manifest-admission-root",
        role="root",
        distribution="acme",
        version="1.0",
        canonical_source_identity="https://packages.example.test/acme.whl",
        source_envelope_fingerprint="a" * 64,
        acquisition_receipt_fingerprint="b" * 64,
        wheel_evidence_fingerprint="c" * 64,
        artifact_digest="d" * 64,
        extraction_tree_digest="e" * 64,
        selected_extras=(),
        requirements=(root_requirement,),
        selected_edges=(dependency.node_id,),
    )
    plan = VerifiedClosurePlanV2.create(
        operation_id=status.operation_id,
        attempt_epoch=status.attempt_epoch,
        root_node_id=root.node_id,
        resolution_environment_fingerprint="e" * 64,
        nodes=(root, dependency),
        max_depth=1,
    )
    pin_request = PackageTransactionPinRequestV1.create(
        plan,
        request_fingerprint=status.request_fingerprint,
        classification_fingerprint=status.classification.evidence_ref,
        recovery_identity="manifest-commit-admission",
    )
    pin_receipt = PackageTransactionPinReceiptV1.acquire(
        pin_request,
        pin_id="f" * 64,
        owner_identity="manifest-retention-owner",
        owner_revision=1,
        lease_id="manifest-admission-lease",
        lease_revision=1,
    )
    pin_journal = PackageTransactionPinJournal(
        tmp_path / "package-transaction-pins.jsonl"
    )
    pin_journal.append(pin_receipt)
    for phase in ("transaction_pinned", "staging"):
        prior = status.phase
        status = kernel.advance(
            status.operation_id,
            next_phase=phase,  # type: ignore[arg-type]
            expected_phase=prior,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )

    root_ref = PluginRevisionRefV1.create(
        store_identity="manifest-plugin-store",
        store_revision="manifest-plugin-revision:1",
        installation_id="manifest-installation",
        plugin_id="acme.plugin",
        distribution=root.distribution,
        version=root.version,
        artifact_digest=root.artifact_digest,
        extraction_tree_digest=root.extraction_tree_digest,
    )
    dependency_ref = VerifiedArtifactRefV1.create(
        store_identity="manifest-dependency-store",
        store_revision="manifest-dependency-revision:1",
        distribution=dependency.distribution,
        version=dependency.version,
        artifact_digest=dependency.artifact_digest,
        extraction_tree_digest=dependency.extraction_tree_digest,
    )
    closure_lock = DependencyClosureLockV2.create(
        plan,
        stable_refs={
            root.node_id: root_ref,
            dependency.node_id: dependency_ref,
        },
    )
    committed_sets = PackageCommittedSetJournal(
        tmp_path / "package-committed-sets.jsonl"
    )
    committed_sets.publish(
        closure_lock,
        request_fingerprint=status.request_fingerprint,
        product_id="coding",
        scope_id="workspace:manifest",
        installation_id="manifest-installation",
        plugin_id="acme.plugin",
        classification_fingerprint=status.classification.evidence_ref,
    )
    status = kernel.advance(
        status.operation_id,
        next_phase="set_published",
        expected_phase="staging",
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
    )
    assert status.phase == "set_published"
    return _ManifestCommitAdmissionFixture(
        kernel=kernel,
        committed_sets=committed_sets,
        pin_journal=pin_journal,
        pin_receipt=pin_receipt,
        commit_owner=PackageCommitLifecycleOwner(
            kernel=kernel,
            committed_sets=committed_sets,
            pin_journal=pin_journal,
        ),
        admission_owner=PackageCommitAdmissionOwner(
            lifecycle_journal=journal,
            committed_sets=committed_sets,
            pin_journal=pin_journal,
        ),
    )


def _manifest_admission_request(
    receipt: PackagePublicationReceiptV1,
    **changes: object,
) -> PackageCommitAdmissionRequestV1:
    values: dict[str, object] = {
        "operation_id": receipt.operation_id,
        "request_fingerprint": receipt.request_fingerprint,
        "product_id": receipt.product_id,
        "scope_id": receipt.scope_id,
        "installation_id": receipt.installation_id,
        "plugin_id": receipt.plugin_id,
        "claimed_root_ref": receipt.committed_set.root_ref,
        "committed_set_id": receipt.committed_set.set_id,
        "closure_lock_digest": receipt.committed_set.closure_lock_digest,
        "publication_receipt": receipt,
    }
    values.update(changes)
    return PackageCommitAdmissionRequestV1.create(**values)  # type: ignore[arg-type]


class _ManifestDesiredStateCommitOwner:
    def __init__(self, *, inventory_revision: int = 0) -> None:
        self.inventory_revision = inventory_revision
        self.interruptions = 0
        self.calls = 0
        self.physical_commits = 0
        self._results: dict[str, PackageDesiredStateCommitResultV1] = {}
        self._lock = Lock()

    def commit(
        self,
        request: PackageDesiredStateCommitRequestV1,
    ) -> PackageDesiredStateCommitResultV1:
        with self._lock:
            self.calls += 1
            repeated = self._results.get(request.desired_request_id)
            if repeated is not None:
                return repeated
            if self.interruptions:
                self.interruptions -= 1
                raise RuntimeError("desired owner interrupted")
            if request.expected_inventory_revision != self.inventory_revision:
                result = PackageDesiredStateCommitResultV1.rejected(
                    request,
                    observed_inventory_revision=self.inventory_revision,
                    owner_identity="manifest-desired-owner",
                    owner_revision=max(self.inventory_revision, 1),
                )
            else:
                self.inventory_revision += 1
                self.physical_commits += 1
                result = PackageDesiredStateCommitResultV1.committed(
                    request,
                    owner_identity="manifest-desired-owner",
                    owner_revision=self.inventory_revision,
                )
            self._results[request.desired_request_id] = result
            return result


class _ManifestProcessCrash(BaseException):
    pass


class _ManifestRetentionSettlementOwner:
    def __init__(self, pin_journal: PackageTransactionPinJournal) -> None:
        self.pin_journal = pin_journal
        self.settle_interruptions = 0
        self.settle_postcommit_crashes = 0
        self.acquire_calls = 0
        self.abort_calls = 0
        self.settle_calls = 0
        self.physical_acquisitions = 0
        self.physical_aborts = 0
        self.physical_settlements = 0
        self.zero_pin_observed = False
        self._receipts: dict[str, PackageDependencyPinReceiptV1] = {}
        self._lock = Lock()

    def acquire(
        self,
        request: object,
        *,
        transaction_pin_receipt: PackageTransactionPinReceiptV1,
    ) -> PackageDependencyPinReceiptV1:
        from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
            PackageDependencyPinRequestV1,
        )

        assert isinstance(request, PackageDependencyPinRequestV1)
        with self._lock:
            self.acquire_calls += 1
            repeated = self._receipts.get(request.pin_request_id)
            if repeated is not None:
                return repeated
            assert transaction_pin_receipt.state == "acquired"
            pin_ids = tuple(
                sha256(f"{request.pin_request_id}:{ref_id}".encode()).hexdigest()
                for ref_id in request.target_ref_ids
            )
            receipt = PackageDependencyPinReceiptV1.acquire(
                request,
                pin_ids=pin_ids,
                owner_identity="manifest-handoff-retention-owner",
                owner_revision=1,
                lease_revision=1,
                transaction_pin_receipt=transaction_pin_receipt,
            )
            self._receipts[request.pin_request_id] = receipt
            self.physical_acquisitions += 1
            return receipt

    def abort(
        self,
        receipt: PackageDependencyPinReceiptV1,
        *,
        failure: object,
    ) -> PackageDependencyPinReceiptV1:
        from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
            PackageDesiredStateCommitFailureV1,
        )

        assert isinstance(failure, PackageDesiredStateCommitFailureV1)
        with self._lock:
            self.abort_calls += 1
            current = self._receipts[receipt.request.pin_request_id]
            if current.state == "aborted":
                return current
            assert current == receipt and current.state == "acquired"
            aborted = PackageDependencyPinReceiptV1.abort(
                current,
                failure,
                owner_revision=current.owner_revision + 1,
                lease_revision=current.lease_revision + 1,
            )
            self._receipts[receipt.request.pin_request_id] = aborted
            self.physical_aborts += 1
            assert aborted.transaction_pin_receipt.state == "acquired"
            return aborted

    def settle(
        self,
        receipt: PackageDependencyPinReceiptV1,
        *,
        desired_receipt: object,
    ) -> PackageDependencyPinReceiptV1:
        from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
            PackageDesiredStateCommitReceiptV1,
        )

        assert isinstance(desired_receipt, PackageDesiredStateCommitReceiptV1)
        with self._lock:
            self.settle_calls += 1
            current = self._receipts[receipt.request.pin_request_id]
            if current.state == "settled":
                return current
            assert current == receipt and current.state == "acquired"
            if self.settle_interruptions:
                self.settle_interruptions -= 1
                raise RuntimeError("retention settlement interrupted")
            if not current.dependency_pins_live:
                self.zero_pin_observed = True
            released = PackageTransactionPinReceiptV1.transition(
                current.transaction_pin_receipt,
                state="released",
                owner_revision=current.transaction_pin_receipt.owner_revision + 1,
                lease_revision=current.transaction_pin_receipt.lease_revision + 1,
                transition_evidence_ref=desired_receipt.receipt_id,
            )
            self.pin_journal.append(released)
            settled = PackageDependencyPinReceiptV1.settle(
                current,
                desired_receipt,
                released,
                owner_revision=current.owner_revision + 1,
                lease_revision=current.lease_revision + 1,
            )
            self._receipts[receipt.request.pin_request_id] = settled
            self.physical_settlements += 1
            if self.settle_postcommit_crashes:
                self.settle_postcommit_crashes -= 1
                raise _ManifestProcessCrash
            return settled

    def current(
        self,
        request: PackageRetentionHandoffRequestV1,
    ) -> PackageDependencyPinReceiptV1 | None:
        with self._lock:
            return self._receipts.get(request.dependency_pin_request.pin_request_id)


@dataclass(frozen=True)
class _ManifestRetentionHandoffFixture:
    request: PackageRetentionHandoffRequestV1
    journal: PackageRetentionHandoffJournal
    owner: PackageRetentionHandoffOwner
    retention: _ManifestRetentionSettlementOwner
    desired: _ManifestDesiredStateCommitOwner
    pin_journal: PackageTransactionPinJournal


def _manifest_retention_handoff_fixture(
    tmp_path: Path,
    *,
    desired_inventory_revision: int = 0,
) -> _ManifestRetentionHandoffFixture:
    admission = _manifest_commit_admission_fixture(tmp_path)
    publication = admission.commit_owner.commit("manifest-operation")
    admission_request = _manifest_admission_request(publication)
    admission_result = admission.admission_owner.admit(admission_request)
    assert admission_result.receipt is not None
    desired_request = PackageDesiredStateCommitRequestV1.create(
        admission_request,
        command_id="manifest-desired-command",
        command_fingerprint=sha256(b"manifest-desired-command").hexdigest(),
        expected_inventory_revision=0,
    )
    request = PackageRetentionHandoffRequestV1.create(
        admission_request=admission_request,
        admission_receipt=admission_result.receipt,
        transaction_pin_receipt=admission.pin_receipt,
        desired_request=desired_request,
    )
    journal = PackageRetentionHandoffJournal(tmp_path / "retention-handoff.jsonl")
    retention = _ManifestRetentionSettlementOwner(admission.pin_journal)
    desired = _ManifestDesiredStateCommitOwner(
        inventory_revision=desired_inventory_revision
    )
    return _ManifestRetentionHandoffFixture(
        request=request,
        journal=journal,
        owner=PackageRetentionHandoffOwner(
            journal=journal,
            admission=admission.admission_owner,
            retention=retention,
            desired_state=desired,
        ),
        retention=retention,
        desired=desired,
        pin_journal=admission.pin_journal,
    )


@dataclass
class _ManifestEpochLeaseAuthority:
    snapshot_value: PackageEpochLeaseSnapshotV1
    calls: int = 0

    def snapshot(self, *, store_id: str) -> PackageEpochLeaseSnapshotV1:
        self.calls += 1
        assert store_id == self.snapshot_value.store_id
        return self.snapshot_value


@dataclass(frozen=True)
class _ManifestEpochAdmissionFixture:
    journal: PackageEpochFenceJournal
    owner: PackageEpochRuntimeAdmissionOwner
    leases: _ManifestEpochLeaseAuthority
    request: PackageEpochRuntimeAdmissionRequestV1


def _manifest_epoch_admission_fixture(
    tmp_path: Path,
    *,
    mixed_epoch: bool,
) -> _ManifestEpochAdmissionFixture:
    journal = PackageEpochFenceJournal(tmp_path / "package-epoch.jsonl")
    first = journal.publish(
        PackageEpochFenceRequestV1.create(
            store_id="package-store:manifest",
            prior_fence=None,
            legacy_root_identity="1" * 64,
            fenced_root_identity="2" * 64,
            namespace_id="3" * 64,
            minimum_runtime_version="1.0.0",
            minimum_runtime_protocol_epoch=1,
            quiescence_receipt_id="4" * 64,
            snapshot_receipt_id="5" * 64,
            root_switch_receipt_id="6" * 64,
        )
    )
    current = journal.publish(
        PackageEpochFenceRequestV1.create(
            store_id=first.store_id,
            prior_fence=first,
            legacy_root_identity=first.fenced_root_identity,
            fenced_root_identity="7" * 64,
            namespace_id="8" * 64,
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
            quiescence_receipt_id="9" * 64,
            snapshot_receipt_id="a" * 64,
            root_switch_receipt_id="b" * 64,
        )
    )
    current_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id="runtime:manifest-current",
        runtime_epoch=current.epoch,
        store_root_identity=current.fenced_root_identity,
        registration_receipt_id="c" * 64,
    )
    stale_lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id="runtime:manifest-stale",
        runtime_epoch=first.epoch,
        store_root_identity=first.fenced_root_identity,
        registration_receipt_id="d" * 64,
    )
    active_leases = (current_lease, stale_lease) if mixed_epoch else (current_lease,)
    leases = _ManifestEpochLeaseAuthority(
        PackageEpochLeaseSnapshotV1.create(
            store_id=current.store_id,
            owner_revision=2,
            active_leases=active_leases,
        )
    )
    request_lease = current_lease if mixed_epoch else stale_lease
    request = PackageEpochRuntimeAdmissionRequestV1.create(
        fence=current,
        runtime_id=request_lease.runtime_id,
        runtime_version="2.0.0" if mixed_epoch else "1.0.0",
        runtime_protocol_epoch=2 if mixed_epoch else 1,
        runtime_epoch=request_lease.runtime_epoch,
        store_root_identity=request_lease.store_root_identity,
        lease_id=request_lease.lease_id,
    )
    return _ManifestEpochAdmissionFixture(
        journal=journal,
        owner=PackageEpochRuntimeAdmissionOwner(fences=journal, leases=leases),
        leases=leases,
        request=request,
    )


@dataclass
class _ManifestEpochCutoverCoordination:
    active_pre_fence_registration_ids: tuple[str, ...] = ()
    calls: int = 0

    def __post_init__(self) -> None:
        self._lock = Lock()

    @contextmanager
    def exclusive_quiescence(
        self,
        *,
        store_id: str,
    ) -> Iterator[PackageEpochCutoverQuiescenceReceiptV1]:
        with self._lock:
            self.calls += 1
            yield PackageEpochCutoverQuiescenceReceiptV1.create(
                store_id=store_id,
                owner_revision=1,
                active_runtime_lease_ids=(),
                active_pre_fence_registration_ids=(
                    self.active_pre_fence_registration_ids
                ),
            )


@dataclass
class _ManifestEpochCutoverSnapshots:
    calls: int = 0

    def capture(
        self,
        *,
        store_id: str,
        legacy_root_identity: str,
        quiescence_receipt_id: str,
    ) -> PackageEpochCutoverSnapshotReceiptV1:
        self.calls += 1
        return PackageEpochCutoverSnapshotReceiptV1.create(
            store_id=store_id,
            legacy_root_identity=legacy_root_identity,
            quiescence_receipt_id=quiescence_receipt_id,
            snapshot_id=sha256(
                f"{store_id}:{legacy_root_identity}:manifest".encode()
            ).hexdigest(),
            snapshot_revision=1,
            entry_count=2,
            byte_count=15,
        )


@dataclass(frozen=True)
class _ManifestEpochCutoverFixture:
    owner: PackagePosixEpochCutoverOwner
    request: PackagePosixEpochCutoverRequestV1
    journal: PackageEpochFenceJournal
    coordination: _ManifestEpochCutoverCoordination
    snapshots: _ManifestEpochCutoverSnapshots
    authority: Path
    legacy: Path
    epochs: Path


@dataclass(frozen=True)
class _ManifestWindowsEpochCutoverFixture:
    owner: PackageWindowsEpochCutoverOwner
    request: PackageWindowsEpochCutoverRequestV1
    journal: PackageEpochFenceJournal
    coordination: _ManifestEpochCutoverCoordination
    snapshots: _ManifestEpochCutoverSnapshots
    authority: Path
    legacy: Path
    epochs: Path


def _manifest_posix_epoch_cutover_fixture(
    tmp_path: Path,
    *,
    pre_fence_live: bool,
) -> _ManifestEpochCutoverFixture:
    assert os.name == "posix"
    authority = tmp_path / "manifest-package-epoch-authority"
    legacy = authority / "legacy"
    epochs = authority / "epochs"
    authority.mkdir(mode=0o700)
    legacy.mkdir(mode=0o700)
    epochs.mkdir(mode=0o700)
    (legacy / "state.json").write_bytes(b'{"legacy":1}\n')
    coordination = _ManifestEpochCutoverCoordination(
        active_pre_fence_registration_ids=(("f" * 64,) if pre_fence_live else ())
    )
    snapshots = _ManifestEpochCutoverSnapshots()
    journal = PackageEpochFenceJournal(tmp_path / "manifest-package-epoch.jsonl")
    owner = PackagePosixEpochCutoverOwner(
        authority,
        store_id="package-store:manifest-posix-cutover",
        epoch_journal=journal,
        coordination=coordination,
        snapshots=snapshots,
    )
    request = PackagePosixEpochCutoverRequestV1.create(
        store_id="package-store:manifest-posix-cutover",
        prior_fence=None,
        expected_legacy_root_identity=owner.current_root_identity(),
        namespace_id="e" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    return _ManifestEpochCutoverFixture(
        owner=owner,
        request=request,
        journal=journal,
        coordination=coordination,
        snapshots=snapshots,
        authority=authority,
        legacy=legacy,
        epochs=epochs,
    )


def _manifest_windows_epoch_cutover_fixture(
    tmp_path: Path,
    *,
    pre_fence_live: bool,
) -> _ManifestWindowsEpochCutoverFixture:
    assert os.name == "nt"
    authority = tmp_path / "manifest-package-epoch-authority"
    legacy = authority / "legacy"
    epochs = authority / "epochs"
    legacy.mkdir(parents=True)
    epochs.mkdir()
    (legacy / "state.json").write_bytes(b'{"legacy":1}\n')
    coordination = _ManifestEpochCutoverCoordination(
        active_pre_fence_registration_ids=(("f" * 64,) if pre_fence_live else ())
    )
    snapshots = _ManifestEpochCutoverSnapshots()
    journal = PackageEpochFenceJournal(tmp_path / "manifest-package-epoch.jsonl")
    owner = PackageWindowsEpochCutoverOwner(
        authority,
        store_id="package-store:manifest-windows-cutover",
        epoch_journal=journal,
        coordination=coordination,
        snapshots=snapshots,
    )
    request = PackageWindowsEpochCutoverRequestV1.create(
        store_id="package-store:manifest-windows-cutover",
        prior_fence=None,
        expected_legacy_root_identity=owner.current_root_identity(),
        namespace_id="d" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    return _ManifestWindowsEpochCutoverFixture(
        owner=owner,
        request=request,
        journal=journal,
        coordination=coordination,
        snapshots=snapshots,
        authority=authority,
        legacy=legacy,
        epochs=epochs,
    )


@dataclass
class _ManifestOfflineRestoreSnapshots:
    evidence: PackageOfflineRestoreSnapshotEvidenceV1
    calls: int = 0

    def snapshot(
        self,
        snapshot_receipt_id: str,
    ) -> PackageOfflineRestoreSnapshotEvidenceV1 | None:
        self.calls += 1
        if snapshot_receipt_id != self.evidence.snapshot.receipt_id:
            return None
        return self.evidence


@dataclass(frozen=True)
class _ManifestLinuxOfflineRestoreFixture:
    owner: PackageOfflineRestoreOwner
    materializer: PackagePosixOfflineRestoreMaterializer
    activation: PackageLinuxLegacyRuntimeActivationOwner
    request: PackageOfflineRestoreRequestV1
    journal: PackageEpochFenceJournal
    coordination: _ManifestEpochCutoverCoordination
    snapshots: _ManifestOfflineRestoreSnapshots
    source: Path
    restore_root: Path
    activation_root: Path
    current_b_root: Path


def _manifest_directory_identity(path: Path) -> str:
    metadata = path.stat()
    return sha256(
        canonical_json_bytes(
            {
                "device": metadata.st_dev,
                "fileType": "directory",
                "identityVersion": 1,
                "inode": metadata.st_ino,
            }
        )
    ).hexdigest()


def _manifest_tree_metrics(payload: Path) -> tuple[str, int, int]:
    entries: list[dict[str, object]] = []
    byte_count = 0
    for path in sorted(payload.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(payload).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_dir():
            entries.append({"kind": "directory", "logicalPath": relative, "mode": mode})
            continue
        contents = path.read_bytes()
        byte_count += len(contents)
        entries.append(
            {
                "byteCount": len(contents),
                "contentDigest": sha256(contents).hexdigest(),
                "kind": "file",
                "logicalPath": relative,
                "mode": mode,
            }
        )
    digest = sha256(
        canonical_json_bytes({"entries": entries, "manifestVersion": 1})
    ).hexdigest()
    return digest, len(entries), byte_count


def _manifest_legacy_runtime_command(current_b_root: Path) -> tuple[str, ...]:
    script = f"""
import os
import pathlib
import time

if pathlib.Path("legacy-state.json").read_bytes() != b'{{"legacy":1}}\\n':
    raise SystemExit(41)
try:
    pathlib.Path({str(current_b_root)!r}, "epoch-b.json").read_bytes()
except OSError:
    pass
else:
    raise SystemExit(42)
descriptor = int(os.environ.pop("LOUSHANG_LEGACY_RUNTIME_READY_FD"))
token = os.environ.pop("LOUSHANG_LEGACY_RUNTIME_READY_TOKEN")
os.write(descriptor, f"ready:{{token}}\\n".encode())
os.close(descriptor)
while True:
    time.sleep(60)
"""
    return ("/usr/bin/python3", "-I", "-S", "-c", script)


def _manifest_linux_offline_restore_fixture(
    tmp_path: Path,
) -> _ManifestLinuxOfflineRestoreFixture:
    assert sys.platform.startswith("linux")
    store_id = "package-store:manifest-linux-offline-restore"
    snapshot_root = tmp_path / "manifest-snapshot-authority"
    restore_root = tmp_path / "manifest-restore-authority"
    activation_root = tmp_path / "manifest-activation-authority"
    current_b_root = tmp_path / "manifest-current-b-authority"
    for root in (snapshot_root, restore_root, activation_root, current_b_root):
        root.mkdir(mode=0o700)
    (current_b_root / "epoch-b.json").write_bytes(b'{"epoch":"B"}\n')
    snapshot_id = sha256(b"manifest-pre-b-snapshot").hexdigest()
    source = snapshot_root / snapshot_id / "payload"
    source.mkdir(parents=True, mode=0o700)
    (source / "legacy-state.json").write_bytes(b'{"legacy":1}\n')
    tree_digest, entry_count, byte_count = _manifest_tree_metrics(source)
    snapshot = PackageEpochCutoverSnapshotReceiptV1.create(
        store_id=store_id,
        legacy_root_identity=sha256(b"manifest-legacy-root").hexdigest(),
        quiescence_receipt_id=sha256(b"manifest-quiescence").hexdigest(),
        snapshot_id=snapshot_id,
        snapshot_revision=1,
        entry_count=entry_count,
        byte_count=byte_count,
    )
    state_manifest = canonical_json_bytes(
        {
            "byteCount": snapshot.byte_count,
            "coveredDomains": list(PACKAGE_PRE_B_SNAPSHOT_DOMAINS),
            "entryCount": snapshot.entry_count,
            "legacyRootIdentity": snapshot.legacy_root_identity,
            "manifestVersion": 1,
            "snapshotId": snapshot.snapshot_id,
            "snapshotReceiptId": snapshot.receipt_id,
            "snapshotRevision": snapshot.snapshot_revision,
            "storeId": snapshot.store_id,
            "treeDigest": tree_digest,
        }
    )
    (source.parent / "state-manifest.json").write_bytes(state_manifest)
    evidence = PackageOfflineRestoreSnapshotEvidenceV1.create(
        snapshot,
        snapshot_tree_digest=tree_digest,
        state_manifest_digest=sha256(state_manifest).hexdigest(),
    )
    journal = PackageEpochFenceJournal(tmp_path / "manifest-offline-epoch.jsonl")
    current = journal.publish(
        PackageEpochFenceRequestV1.create(
            store_id=store_id,
            prior_fence=None,
            legacy_root_identity=snapshot.legacy_root_identity,
            fenced_root_identity=_manifest_directory_identity(current_b_root),
            namespace_id=sha256(b"manifest-current-b-namespace").hexdigest(),
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
            quiescence_receipt_id=snapshot.quiescence_receipt_id,
            snapshot_receipt_id=snapshot.receipt_id,
            root_switch_receipt_id=sha256(b"manifest-root-switch").hexdigest(),
        )
    )
    request = PackageOfflineRestoreRequestV1.create(
        current_fence=current,
        genesis_fence=current,
        snapshot_evidence=evidence,
        restore_namespace_id=sha256(b"manifest-isolated-restore").hexdigest(),
        legacy_runtime_version="1.9.0",
    )
    coordination = _ManifestEpochCutoverCoordination()
    snapshots = _ManifestOfflineRestoreSnapshots(evidence)
    materializer = PackagePosixOfflineRestoreMaterializer(
        snapshot_root,
        restore_root,
        current_b_authority_root=current_b_root,
        store_id=store_id,
    )
    activation = PackageLinuxLegacyRuntimeActivationOwner(
        restore_root,
        activation_root,
        current_b_authority_root=current_b_root,
        store_id=store_id,
        legacy_runtime_version=request.legacy_runtime_version,
        command=_manifest_legacy_runtime_command(current_b_root),
    )
    owner = PackageOfflineRestoreOwner(
        store_id=store_id,
        epoch_journal=journal,
        coordination=coordination,
        snapshots=snapshots,
        materialization=materializer,
        activation=activation,
    )
    return _ManifestLinuxOfflineRestoreFixture(
        owner=owner,
        materializer=materializer,
        activation=activation,
        request=request,
        journal=journal,
        coordination=coordination,
        snapshots=snapshots,
        source=source,
        restore_root=restore_root,
        activation_root=activation_root,
        current_b_root=current_b_root,
    )


@dataclass
class _ManifestAdoptionFenceReader:
    journal: PackageEpochFenceJournal
    calls: int = 0

    def current(self, store_id: str) -> PackageEpochFenceReceiptV1 | None:
        self.calls += 1
        return self.journal.current(store_id)


@dataclass
class _ManifestAdoptionLegacyStateOwner:
    root: Path
    store_id: str
    legacy_root_identity: str
    calls: int = 0

    def capture(self) -> PackageLegacyStateEvidenceV1:
        state_digest, entry_count, byte_count = _manifest_tree_metrics(self.root)
        return PackageLegacyStateEvidenceV1.create(
            store_id=self.store_id,
            legacy_root_identity=_manifest_directory_identity(self.root),
            state_digest=state_digest,
            entry_count=entry_count,
            byte_count=byte_count,
        )

    def observe(
        self,
        *,
        store_id: str,
        legacy_root_identity: str,
    ) -> PackageLegacyStateEvidenceV1:
        assert store_id == self.store_id
        assert legacy_root_identity == self.legacy_root_identity
        self.calls += 1
        return self.capture()


@dataclass(frozen=True)
class _ManifestNativeAdoptionFixture:
    owner: PackageLegacyAdoptionOwner
    request: PackageLegacyAdoptionRequestV1
    execution: PackageClosureExecutionRequestV2
    kernel: PackageLifecycleOwner
    lifecycle_journal: PackageLifecycleJournal
    evidence_journal: PackageArtifactEvidenceJournal
    resolution_journal: PackageClosureResolutionJournal
    pin_journal: PackageTransactionPinJournal
    staging_journal: PackageArtifactStagingJournal
    committed_sets: PackageCommittedSetJournal
    fence_journal: PackageEpochFenceJournal
    fence_reader: _ManifestAdoptionFenceReader
    legacy_state: _ManifestAdoptionLegacyStateOwner
    source_authority: _SourceAuthority
    quarantine: PackageQuarantineStore
    resolver: _NoDependencyResolver
    retention: _TransactionPinRetentionOwner
    root_targets: _ManifestRootTargetAuthority
    root_staging: _ManifestNativeRootStagingOwner
    root_settlements: PackageStoreSettlementJournal
    current_root: Path
    product_files: tuple[tuple[Path, bytes], ...]
    product_projections: _ManifestProductProjectionOwner
    product_projection_before: tuple[tuple[str, int, bytes], ...]
    coordination: _ManifestAdoptionCoordination
    commit: PackageCommitLifecycleOwner | _ManifestCrashAfterCommittedCommitOwner
    secret: str


class _ManifestAdoptionCoordination:
    def __init__(self) -> None:
        self.lock = Lock()

    @contextmanager
    def hold(self, _request: PackageLegacyAdoptionRequestV1) -> Iterator[None]:
        with self.lock:
            yield


@dataclass(frozen=True)
class _ManifestProductProjectionOwner:
    paths: tuple[tuple[str, Path], ...]

    @classmethod
    def create(cls, root: Path) -> _ManifestProductProjectionOwner:
        root.mkdir(mode=0o700)
        paths: list[tuple[str, Path]] = []
        for domain in ("binding", "desired", "enablement", "instance"):
            path = root / f"{domain}.json"
            path.write_bytes(
                canonical_json_bytes(
                    {
                        "domain": domain,
                        "projectionVersion": 1,
                        "revision": 1,
                        "value": "legacy",
                    }
                )
                + b"\n"
            )
            path.chmod(0o600)
            paths.append((domain, path))
        return cls(paths=tuple(paths))

    def capture(self) -> tuple[tuple[str, int, bytes], ...]:
        captured: list[tuple[str, int, bytes]] = []
        for domain, path in self.paths:
            payload = path.read_bytes()
            document = json.loads(payload)
            assert document["domain"] == domain
            captured.append((domain, int(document["revision"]), payload))
        return tuple(captured)


class _ManifestCrashAfterCommitted(RuntimeError):
    pass


@dataclass
class _ManifestCrashAfterCommittedCommitOwner:
    owner: PackageCommitLifecycleOwner
    crashed: bool = False
    calls: int = 0
    pre_crash_receipt: PackagePublicationReceiptV1 | None = None

    def commit(self, operation_id: str) -> PackagePublicationReceiptV1:
        self.calls += 1
        receipt = self.owner.commit(operation_id)
        if not self.crashed:
            self.pre_crash_receipt = receipt
            self.crashed = True
            raise _ManifestCrashAfterCommitted
        return receipt


def _assert_manifest_secret_absent(root: Path, secret: str) -> None:
    encoded = secret.encode()
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        assert all(secret not in component for component in relative.parts)
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            assert secret not in os.readlink(path)
        elif stat.S_ISREG(metadata.st_mode):
            assert encoded not in path.read_bytes()


def _manifest_native_adoption_fixture(
    tmp_path: Path,
    *,
    fenced_root_identity: str | None = None,
    adoption_installation_id: str = "manifest-installation",
    case_id: str = "B-COMPAT-ADOPT",
    crash_after_committed: bool = False,
    crash_after_phase: PackageLifecyclePhase | None = None,
    root_payload: bytes | None = None,
    secret: str = "manifest-secret-b-compat-adopt",
    staging_classification_recheck: (
        _StableClassificationRecheck | _ChangedClassificationRecheck | None
    ) = None,
) -> _ManifestNativeAdoptionFixture:
    store_id = "package-store:manifest-adoption"
    environment = _closure_environment()
    (
        kernel,
        _artifact_owner,
        lifecycle_journal,
        evidence_journal,
        _cleanup_journal,
        quarantine,
        source_authority,
        closure_owner,
        resolution_journal,
        resolver,
    ) = _b3d_owner(
        tmp_path,
        case_id=case_id,
        secret=secret,
        crash_after_phase=crash_after_phase,
        root_payload=root_payload,
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
    assert classified.classification is not None

    legacy_root = tmp_path / "legacy-package-snapshot"
    legacy_root.mkdir(mode=0o700)
    product_payloads = {
        "binding_history.json": b'{"binding":"legacy"}\n',
        "desired_state.json": b'{"desired":"legacy"}\n',
        "enablement_state.json": b'{"enabled":true}\n',
        "fence_record.json": b'{"epoch":1}\n',
        "instance_state.json": b'{"instance":"legacy"}\n',
        "legacy_root_pointer.json": b'{"root":"legacy"}\n',
        "lock_history.json": b'{"lock":"legacy"}\n',
        "source_configuration.json": b'{"source":"private-index"}\n',
        "store_bytes.bin": b"legacy-package-store-bytes\n",
    }
    product_files: list[tuple[Path, bytes]] = []
    for name, payload in sorted(product_payloads.items()):
        path = legacy_root / name
        path.write_bytes(payload)
        path.chmod(0o600)
        product_files.append((path, payload))
    legacy_root_identity = _manifest_directory_identity(legacy_root)
    legacy_state = _ManifestAdoptionLegacyStateOwner(
        root=legacy_root,
        store_id=store_id,
        legacy_root_identity=legacy_root_identity,
    )
    legacy_evidence = legacy_state.capture()
    product_projections = _ManifestProductProjectionOwner.create(
        tmp_path / "manifest-product-projections"
    )
    product_projection_before = product_projections.capture()

    dependency_root = tmp_path / "adoption-dependency-store"
    plugin_authority = tmp_path / "adoption-plugin-authority"
    plugin_root = plugin_authority / "plugin-revision-store"
    dependency_root.mkdir(mode=0o700)
    plugin_authority.mkdir(mode=0o700)
    plugin_root.mkdir(mode=0o700)
    fence_journal = PackageEpochFenceJournal(tmp_path / "manifest-adoption-epoch.jsonl")
    fence = fence_journal.publish(
        PackageEpochFenceRequestV1.create(
            store_id=store_id,
            prior_fence=None,
            legacy_root_identity=legacy_root_identity,
            fenced_root_identity=(
                fenced_root_identity or _manifest_directory_identity(plugin_root)
            ),
            namespace_id=sha256(b"manifest-adoption-current-namespace").hexdigest(),
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
            quiescence_receipt_id=sha256(b"manifest-adoption-quiescence").hexdigest(),
            snapshot_receipt_id=sha256(b"manifest-adoption-snapshot").hexdigest(),
            root_switch_receipt_id=sha256(b"manifest-adoption-root-switch").hexdigest(),
        )
    )
    adoption_request = PackageLegacyAdoptionRequestV1.create(
        current_fence=fence,
        legacy_state=legacy_evidence,
        operation_id=classified.operation_id,
        transaction_request_fingerprint=classified.request_fingerprint,
        expected_classification_fingerprint=(classified.classification.evidence_ref),
        expected_attempt_epoch=classified.attempt_epoch,
        product_id="coding",
        scope_id="workspace:manifest",
        installation_id=adoption_installation_id,
        plugin_id="acme.plugin",
    )
    execution = PackageClosureExecutionRequestV2(
        artifact=_artifact_execution(classified, secret=secret),
        resolution_environment=environment,
        budgets=PackageClosureBudgetV1(),
    )

    retention = _TransactionPinRetentionOwner()
    pin_journal = PackageTransactionPinJournal(
        tmp_path / "manifest-adoption-transaction-pins.jsonl"
    )
    pin_owner = PackageTransactionPinLifecycleOwner(
        kernel=kernel,
        closure_plans=resolution_journal,
        retention=retention,
        pin_journal=pin_journal,
    )
    dependency_settlements = PackageStoreSettlementJournal(
        tmp_path / "manifest-adoption-dependency-settlements.jsonl"
    )
    root_settlements = PackageStoreSettlementJournal(
        tmp_path / "manifest-adoption-root-settlements.jsonl"
    )
    root_staging = _ManifestNativeRootStagingOwner(
        PosixPackagePluginRootMaterializationStore(
            plugin_root,
            store_identity="manifest-plugin-revision-store",
            package_store_id=store_id,
            settlement_journal=root_settlements,
        )
    )
    root_targets = _ManifestRootTargetAuthority()
    staging_journal = PackageArtifactStagingJournal(
        tmp_path / "manifest-adoption-staging.jsonl"
    )
    committed_sets = PackageCommittedSetJournal(
        tmp_path / "manifest-adoption-committed-sets.jsonl"
    )
    staging_owner = PackageStagingSetLifecycleOwner(
        kernel=kernel,
        classification_recheck=(
            staging_classification_recheck or _StableClassificationRecheck()
        ),
        closure_plans=resolution_journal,
        pin_journal=pin_journal,
        root_targets=root_targets,
        dependency_staging=PosixPackageDependencyMaterializationStore(
            dependency_root,
            store_identity="manifest-dependency-store",
            settlement_journal=dependency_settlements,
        ),
        root_staging=root_staging,
        staging_journal=staging_journal,
        committed_sets=committed_sets,
    )
    durable_commit = PackageCommitLifecycleOwner(
        kernel=kernel,
        committed_sets=committed_sets,
        pin_journal=pin_journal,
    )
    commit: PackageCommitLifecycleOwner | _ManifestCrashAfterCommittedCommitOwner = (
        _ManifestCrashAfterCommittedCommitOwner(durable_commit)
        if crash_after_committed
        else durable_commit
    )
    transaction = PackageLegacyAdoptionTransactionAdapter(
        kernel=kernel,
        execution=execution,
        recovery_identity="manifest-legacy-adoption-recovery",
        closure=closure_owner,
        pins=pin_owner,
        staging=staging_owner,
        commit=commit,
    )
    fence_reader = _ManifestAdoptionFenceReader(fence_journal)
    coordination = _ManifestAdoptionCoordination()
    owner = PackageLegacyAdoptionOwner(
        store_id=store_id,
        fences=fence_reader,
        legacy_state=legacy_state,
        transaction=transaction,
        coordination=coordination,
    )
    return _ManifestNativeAdoptionFixture(
        owner=owner,
        request=adoption_request,
        execution=execution,
        kernel=kernel,
        lifecycle_journal=lifecycle_journal,
        evidence_journal=evidence_journal,
        resolution_journal=resolution_journal,
        pin_journal=pin_journal,
        staging_journal=staging_journal,
        committed_sets=committed_sets,
        fence_journal=fence_journal,
        fence_reader=fence_reader,
        legacy_state=legacy_state,
        source_authority=source_authority,
        quarantine=quarantine,
        resolver=resolver,
        retention=retention,
        root_targets=root_targets,
        root_staging=root_staging,
        root_settlements=root_settlements,
        current_root=plugin_root,
        product_files=tuple(product_files),
        product_projections=product_projections,
        product_projection_before=product_projection_before,
        coordination=coordination,
        commit=commit,
        secret=secret,
    )


def _restart_manifest_native_adoption_fixture(
    fixture: _ManifestNativeAdoptionFixture,
) -> _ManifestNativeAdoptionFixture:
    """Rebuild the complete Package owner graph over durable local evidence."""

    root = fixture.lifecycle_journal.path.parent
    lifecycle_journal = PackageLifecycleJournal(fixture.lifecycle_journal.path)
    kernel = PackageLifecycleOwner(
        journal=lifecycle_journal,
        classification_authority=_Authority(_facts("explicit_plugin_intent")),
        enabled=True,
    )
    quarantine = PackageQuarantineStore(fixture.quarantine.root)
    evidence_journal = PackageArtifactEvidenceJournal(fixture.evidence_journal.path)
    cleanup_journal = PackageQuarantineCleanupJournal(
        root / "package-quarantine-cleanup.jsonl"
    )
    cleanup_owner = PackageQuarantineCleanupOwner(
        journal=cleanup_journal,
        store=quarantine,
    )
    artifact_owner = PackageArtifactLifecycleOwner(
        kernel=kernel,
        classification_recheck=_StableClassificationRecheck(),
        acquisition_owner=PackageAcquisitionOwner(
            source_authority=fixture.source_authority,
            quarantine_store=quarantine,
            clock=fixture.source_authority.clock,
        ),
        evidence_journal=evidence_journal,
        cleanup_owner=cleanup_owner,
        wheel_verifier=PackageWheelVerifier(),
        acquisition_budgets=PackageAcquisitionBudgetV1(
            max_transport_bytes=256 * 1024,
            max_requests=1,
            max_redirects=1,
            max_wall_time_ms=1000,
        ),
        inspection_budgets=PackageInspectionBudgetV1(),
        supported_tags=frozenset({"py3-none-any"}),
    )
    resolution_journal = PackageClosureResolutionJournal(
        fixture.resolution_journal.path
    )
    recursive_owner = PackageRecursiveClosureOwner(
        resolver=fixture.resolver,
        acquisition_owner=artifact_owner._acquisition_owner,
        evidence_journal=evidence_journal,
        wheel_verifier=artifact_owner._wheel_verifier,
        closure_verifier=PackageClosureVerifier(),
        acquisition_budgets=artifact_owner._acquisition_budgets,
        inspection_budgets=artifact_owner._inspection_budgets,
        cleanup_owner=artifact_owner._cleanup_owner,
        selection_journal=resolution_journal,
    )
    closure_owner = PackageClosureLifecycleOwner(
        kernel=kernel,
        artifact_owner=artifact_owner,
        closure_builder=recursive_owner,
        resolution_journal=resolution_journal,
    )
    retention = _TransactionPinRetentionOwner(fixture.retention.state)
    pin_journal = PackageTransactionPinJournal(fixture.pin_journal.path)
    pin_owner = PackageTransactionPinLifecycleOwner(
        kernel=kernel,
        closure_plans=resolution_journal,
        retention=retention,
        pin_journal=pin_journal,
    )
    root_settlements = PackageStoreSettlementJournal(fixture.root_settlements.path)
    dependency_settlements = PackageStoreSettlementJournal(
        root / "manifest-adoption-dependency-settlements.jsonl"
    )
    root_staging = _ManifestNativeRootStagingOwner(
        PosixPackagePluginRootMaterializationStore(
            fixture.current_root,
            store_identity="manifest-plugin-revision-store",
            package_store_id=fixture.request.store_id,
            settlement_journal=root_settlements,
        ),
        state=fixture.root_staging.state,
    )
    root_targets = _ManifestRootTargetAuthority(fixture.root_targets.state)
    staging_journal = PackageArtifactStagingJournal(fixture.staging_journal.path)
    committed_sets = PackageCommittedSetJournal(fixture.committed_sets.path)
    staging_owner = PackageStagingSetLifecycleOwner(
        kernel=kernel,
        classification_recheck=_StableClassificationRecheck(),
        closure_plans=resolution_journal,
        pin_journal=pin_journal,
        root_targets=root_targets,
        dependency_staging=PosixPackageDependencyMaterializationStore(
            root / "adoption-dependency-store",
            store_identity="manifest-dependency-store",
            settlement_journal=dependency_settlements,
        ),
        root_staging=root_staging,
        staging_journal=staging_journal,
        committed_sets=committed_sets,
    )
    commit = PackageCommitLifecycleOwner(
        kernel=kernel,
        committed_sets=committed_sets,
        pin_journal=pin_journal,
    )
    transaction = PackageLegacyAdoptionTransactionAdapter(
        kernel=kernel,
        execution=fixture.execution,
        recovery_identity="manifest-legacy-adoption-recovery",
        closure=closure_owner,
        pins=pin_owner,
        staging=staging_owner,
        commit=commit,
    )
    fence_journal = PackageEpochFenceJournal(fixture.fence_journal.path)
    fence_reader = _ManifestAdoptionFenceReader(fence_journal)
    legacy_state = _ManifestAdoptionLegacyStateOwner(
        root=fixture.legacy_state.root,
        store_id=fixture.legacy_state.store_id,
        legacy_root_identity=fixture.legacy_state.legacy_root_identity,
    )
    coordination = _ManifestAdoptionCoordination()
    owner = PackageLegacyAdoptionOwner(
        store_id=fixture.request.store_id,
        fences=fence_reader,
        legacy_state=legacy_state,
        transaction=transaction,
        coordination=coordination,
    )
    return _ManifestNativeAdoptionFixture(
        owner=owner,
        request=fixture.request,
        execution=fixture.execution,
        kernel=kernel,
        lifecycle_journal=lifecycle_journal,
        evidence_journal=evidence_journal,
        resolution_journal=resolution_journal,
        pin_journal=pin_journal,
        staging_journal=staging_journal,
        committed_sets=committed_sets,
        fence_journal=fence_journal,
        fence_reader=fence_reader,
        legacy_state=legacy_state,
        source_authority=fixture.source_authority,
        quarantine=quarantine,
        resolver=fixture.resolver,
        retention=retention,
        root_targets=root_targets,
        root_staging=root_staging,
        root_settlements=root_settlements,
        current_root=fixture.current_root,
        product_files=fixture.product_files,
        product_projections=_ManifestProductProjectionOwner(
            paths=fixture.product_projections.paths
        ),
        product_projection_before=fixture.product_projection_before,
        coordination=coordination,
        commit=commit,
        secret=fixture.secret,
    )


@pytest.mark.parametrize(
    ("fixture_options", "reason"),
    (
        (
            {"fenced_root_identity": sha256(b"wrong-native-root").hexdigest()},
            "root",
        ),
        ({"adoption_installation_id": "wrong-installation"}, "installation"),
    ),
)
def test_native_adoption_rejects_wrong_physical_authority_before_source(
    tmp_path: Path,
    fixture_options: dict[str, str],
    reason: str,
) -> None:
    assert sys.platform.startswith("linux")
    fixture = _manifest_native_adoption_fixture(tmp_path, **fixture_options)
    before = (
        fixture.lifecycle_journal.records(),
        fixture.evidence_journal.records(),
        fixture.resolution_journal.records(),
        fixture.pin_journal.records(),
        fixture.staging_journal.records(),
        fixture.committed_sets.records(),
        fixture.root_settlements.records(),
        fixture.product_projections.capture(),
    )

    result = fixture.owner.adopt(fixture.request)

    assert result.disposition == "rejected", reason
    assert result.code == "package_operation_identity_conflict"
    assert fixture.source_authority.authorize_calls == 0
    assert fixture.retention.physical_acquisitions == 0
    assert fixture.root_staging.calls == 0
    assert before == (
        fixture.lifecycle_journal.records(),
        fixture.evidence_journal.records(),
        fixture.resolution_journal.records(),
        fixture.pin_journal.records(),
        fixture.staging_journal.records(),
        fixture.committed_sets.records(),
        fixture.root_settlements.records(),
        fixture.product_projections.capture(),
    )


def test_native_adoption_committed_replay_requires_durable_root_target(
    tmp_path: Path,
) -> None:
    assert sys.platform.startswith("linux")
    fixture = _manifest_native_adoption_fixture(tmp_path)
    adopted = fixture.owner.adopt(fixture.request)
    assert adopted.disposition == "adopted"
    before = (
        fixture.lifecycle_journal.records(),
        fixture.committed_sets.records(),
        fixture.root_settlements.records(),
    )
    fixture.staging_journal.path.write_bytes(b"")

    refused = fixture.owner.adopt(fixture.request)

    assert refused.disposition == "rejected"
    assert refused.code == "package_operation_identity_conflict"
    assert fixture.source_authority.authorize_calls == 1
    assert before == (
        fixture.lifecycle_journal.records(),
        fixture.committed_sets.records(),
        fixture.root_settlements.records(),
    )


@pytest.mark.parametrize("case_id", EXECUTABLE_MANIFEST_CASES)
def test_manifest_case(
    case_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    elif case_id == "B-CLASS-CHANGED":
        assert sys.platform.startswith("linux")
        fixture = _manifest_native_adoption_fixture(
            tmp_path,
            case_id=case_id,
            staging_classification_recheck=_ChangedClassificationRecheck(),
        )
        product_before = fixture.product_projections.capture()

        result = fixture.owner.adopt(fixture.request)
        replay = fixture.owner.adopt(fixture.request)

        assert result == replay
        assert result.disposition == "rejected"
        assert result.code == "package_target_classification_changed"
        status = fixture.kernel.status(fixture.request.operation_id)
        assert status is not None
        assert (status.phase, status.disposition) == ("staging", "rejected")
        assert len(fixture.pin_journal.records()) == 1
        assert fixture.committed_sets.records() == ()
        assert fixture.product_projections.capture() == product_before
        assert not (tmp_path / "binding.json").exists()
        assert not (tmp_path / "desired.json").exists()
    elif case_id == "B-CRASH-COMMITTED":
        owner, journal = _owner(
            tmp_path,
            facts=_facts("explicit_plugin_intent"),
        )
        classified = owner.submit(_request())
        published = _advance_lifecycle(owner, classified, "set_published")
        committed = owner.advance(
            published.operation_id,
            next_phase="committed",
            expected_phase="set_published",
            expected_journal_revision=published.journal_revision,
            expected_attempt_epoch=published.attempt_epoch,
        )
        before = journal.records()
        restarted = PackageLifecycleOwner(
            journal=PackageLifecycleJournal(journal.path),
            classification_authority=_Authority(_facts("explicit_plugin_intent")),
            enabled=True,
        )

        replay = restarted.advance(
            published.operation_id,
            next_phase="committed",
            expected_phase="set_published",
            expected_journal_revision=published.journal_revision,
            expected_attempt_epoch=published.attempt_epoch,
        )

        assert replay == committed
        assert journal.records() == before
        assert committed.disposition == "committed"
    elif case_id == "B-CONCUR-SAME":
        owner, journal = _owner(
            tmp_path,
            facts=_facts("explicit_plugin_intent"),
        )
        current = owner.accept(_request())
        with ThreadPoolExecutor(max_workers=8) as executor:
            classified = tuple(
                executor.map(
                    lambda _index: owner.classify(
                        current.operation_id,
                        expected_journal_revision=current.journal_revision,
                        expected_attempt_epoch=current.attempt_epoch,
                    ),
                    range(8),
                )
            )
        assert len(set(classified)) == 1
        current = classified[0]
        for next_phase in _LIFECYCLE_PHASES[2:]:
            before = len(journal.records())
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = tuple(
                    executor.map(
                        lambda _index, current=current, next_phase=next_phase: (
                            owner.advance(
                                current.operation_id,
                                next_phase=next_phase,
                                expected_phase=current.phase,
                                expected_journal_revision=current.journal_revision,
                                expected_attempt_epoch=current.attempt_epoch,
                            )
                        ),
                        range(8),
                    )
                )
            assert len(set(results)) == 1
            assert len(journal.records()) == before + 1
            current = results[0]
        assert (current.phase, current.disposition) == ("committed", "committed")
    elif case_id == "B-CONCUR-STALE":
        for phase in _LIFECYCLE_PHASES[:-1]:
            root = tmp_path / phase
            root.mkdir()
            owner, journal = _owner(
                root,
                facts=_facts("explicit_plugin_intent"),
            )
            current = owner.accept(_request(operation_id=f"stale-{phase}"))
            if phase != "accepted":
                current = owner.classify(
                    current.operation_id,
                    expected_journal_revision=current.journal_revision,
                    expected_attempt_epoch=current.attempt_epoch,
                )
                current = _advance_lifecycle(owner, current, phase)
            prior = current
            interrupted = owner.interrupt(
                current.operation_id,
                expected_phase=current.phase,
                expected_journal_revision=current.journal_revision,
                expected_attempt_epoch=current.attempt_epoch,
            )
            resumed = owner.retry(
                PackageLifecycleRetryRequestV1(
                    operation_id=current.operation_id,
                    request_fingerprint=current.request_fingerprint,
                    expected_attempt_epoch=interrupted.attempt_epoch,
                )
            )
            before = journal.records()

            stale = owner.cancel(
                PackageLifecycleCancelRequestV1(
                    operation_id=prior.operation_id,
                    request_fingerprint=prior.request_fingerprint,
                    expected_phase=prior.phase,
                    expected_journal_revision=prior.journal_revision,
                    expected_attempt_epoch=prior.attempt_epoch,
                )
            )

            assert stale.disposition == "rejected"
            assert stale.failure is not None
            assert stale.failure.code == "package_attempt_stale"
            assert stale.attempt_epoch == resumed.attempt_epoch == 2
            assert journal.records() == before
    elif case_id in {"B-STATE-CANCEL-EARLY", "B-STATE-CANCEL-PINNED"}:
        transaction_pinned_index = _LIFECYCLE_PHASES.index("transaction_pinned")
        phases = (
            _LIFECYCLE_PHASES[:transaction_pinned_index]
            if case_id == "B-STATE-CANCEL-EARLY"
            else _LIFECYCLE_PHASES[transaction_pinned_index:-1]
        )
        for phase in phases:
            root = tmp_path / phase
            root.mkdir()
            owner, journal = _owner(
                root,
                facts=_facts("explicit_plugin_intent"),
            )
            current = owner.accept(_request(operation_id=f"cancel-{phase}"))
            if phase != "accepted":
                current = owner.classify(
                    current.operation_id,
                    expected_journal_revision=current.journal_revision,
                    expected_attempt_epoch=current.attempt_epoch,
                )
                current = _advance_lifecycle(owner, current, phase)
            before = len(journal.records())
            request = PackageLifecycleCancelRequestV1(
                operation_id=current.operation_id,
                request_fingerprint=current.request_fingerprint,
                expected_phase=current.phase,
                expected_journal_revision=current.journal_revision,
                expected_attempt_epoch=current.attempt_epoch,
            )

            cancelled = owner.cancel(request)
            replay = owner.cancel(request)

            assert replay == cancelled
            assert cancelled.disposition == "cancelled"
            assert cancelled.failure is not None
            assert cancelled.failure.code == "package_operation_cancelled"
            assert len(journal.records()) == before + 1
            assert not (root / "binding.json").exists()
            assert not (root / "desired.json").exists()
    elif case_id in {
        "B-NOEXEC-IMPORT",
        "B-NOEXEC-SETUP",
        "B-NOEXEC-ENTRYPOINT",
        "B-NOEXEC-ADJACENT",
    }:
        assert sys.platform.startswith("linux")
        sentinel = tmp_path / "artifact-executed"
        trap = (
            "from pathlib import Path\n"
            f"Path({str(sentinel)!r}).write_text('executed')\n"
            "def main():\n"
            f"    Path({str(sentinel)!r}).write_text('entrypoint')\n"
        ).encode()
        extras: dict[str, bytes] = {}
        modes: dict[str, int] = {}
        if case_id == "B-NOEXEC-IMPORT":
            extras["acme_plugin/import_trap.py"] = trap
        elif case_id == "B-NOEXEC-ENTRYPOINT":
            extras["acme_plugin/entrypoint_trap.py"] = trap
            extras[f"{DIST_INFO}/entry_points.txt"] = (
                b"[console_scripts]\nacme-trap=acme_plugin.entrypoint_trap:main\n"
            )
        elif case_id == "B-NOEXEC-ADJACENT":
            name = "acme_plugin/post-install"
            extras[name] = f"#!/bin/sh\necho executed > {sentinel}\n".encode()
            modes[name] = stat.S_IFREG | 0o755

        def forbidden_effect(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("Package inspection executed an external effect")

        monkeypatch.setattr(subprocess, "Popen", forbidden_effect)
        monkeypatch.setattr(os, "system", forbidden_effect)
        monkeypatch.setattr(socket, "create_connection", forbidden_effect)

        if case_id == "B-NOEXEC-SETUP":
            (
                kernel,
                artifact_owner,
                _journal,
                _evidence,
                _cleanup,
                _store,
                _source,
            ) = _b2_owner(
                tmp_path,
                case_id=case_id,
                secret="noexec-secret",
                payload=_wheel_bytes(
                    extra_files={"setup.py": trap, "pyproject.toml": trap}
                ),
            )
            classified = kernel.submit(_request())
            result = artifact_owner.execute(
                PackageArtifactExecutionRequestV1(
                    operation_id=classified.operation_id,
                    request_fingerprint=classified.request_fingerprint,
                    expected_attempt_epoch=classified.attempt_epoch,
                    wheel_filename="acme_plugin-1.0.tar.gz",
                    credential_reference="opaque:noexec-secret",
                )
            )
            assert result.status.disposition == "rejected"
            assert result.status.failure is not None
            assert result.status.failure.code == "package_artifact_type_rejected"
        else:
            fixture = _manifest_native_adoption_fixture(
                tmp_path,
                case_id=case_id,
                root_payload=_wheel_bytes(extra_files=extras, entry_modes=modes),
            )
            result = fixture.owner.adopt(fixture.request)
            assert result.disposition == "adopted"
            assert fixture.kernel.status(fixture.request.operation_id).phase == (
                "committed"
            )
        assert not sentinel.exists()
    elif case_id == "B-STATE-SECRETS":
        assert sys.platform.startswith("linux")
        secret = "state-secret-never-persist"
        fixture = _manifest_native_adoption_fixture(
            tmp_path,
            case_id=case_id,
            secret=secret,
        )

        result = fixture.owner.adopt(fixture.request)

        assert result.disposition == "adopted"
        assert secret not in repr(result)
        _assert_manifest_secret_absent(tmp_path, secret)
    elif case_id == "B-STATE-STATUS":
        secret = "status-secret-never-persist"
        (
            kernel,
            artifact_owner,
            journal,
            _evidence,
            _cleanup,
            _store,
            _source,
        ) = _b2_owner(
            tmp_path,
            case_id=case_id,
            secret=secret,
            payload=_wheel_bytes()[:-8],
        )
        classified = kernel.submit(_request())

        result = artifact_owner.execute(_artifact_execution(classified, secret=secret))
        replay = artifact_owner.execute(_artifact_execution(classified, secret=secret))

        assert replay.status == result.status
        assert result.status.failure is not None
        assert result.status.failure.code == "package_archive_malformed"
        assert (
            PackageLifecycleStatusV1.from_dict(result.status.to_dict()) == result.status
        )
        assert journal.status(classified.operation_id) == result.status
        assert secret not in repr((result, replay, journal.records()))
    elif case_id == "B-COMPAT-LEGACY":
        owner, journal = _owner(
            tmp_path,
            facts=_facts("existing_plugin_history"),
        )

        status = owner.submit(_request())

        _assert_classification(status, decision="plugin_bound", code=None)
        _assert_replay_is_single_owner(owner, journal)
        _assert_no_capability_side_effect(tmp_path)
    elif case_id == "B-COMPAT-ROLLFORWARD":
        owner, journal = _owner(
            tmp_path,
            facts=_facts("explicit_plugin_intent"),
        )
        current = owner.submit(_request())
        current = _advance_lifecycle(owner, current, "transaction_pinned")
        interrupted = owner.interrupt(
            current.operation_id,
            expected_phase=current.phase,
            expected_journal_revision=current.journal_revision,
            expected_attempt_epoch=current.attempt_epoch,
        )
        resumed = owner.retry(
            PackageLifecycleRetryRequestV1(
                operation_id=current.operation_id,
                request_fingerprint=current.request_fingerprint,
                expected_attempt_epoch=interrupted.attempt_epoch,
            )
        )
        committed = _advance_lifecycle(owner, resumed, "committed")
        before = journal.records()

        replay = owner.submit(_request())

        assert replay == committed
        assert replay.disposition == "committed"
        assert journal.records() == before
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
    elif case_id in {
        "B-ENTRY-CLI",
        "B-ENTRY-RPC",
        "B-ENTRY-SESSION",
        "B-ENTRY-STARTUP",
        "B-ENTRY-OPERATIONS",
    }:
        entrypoint: PackageProductEntrypoint = {
            "B-ENTRY-CLI": "cli",
            "B-ENTRY-RPC": "rpc",
            "B-ENTRY-SESSION": "session",
            "B-ENTRY-STARTUP": "startup",
            "B-ENTRY-OPERATIONS": "operations",
        }[case_id]  # type: ignore[assignment]
        owner, journal = _owner(
            tmp_path,
            facts=_facts("explicit_plugin_intent"),
        )
        transaction = _ManifestProductTransaction(owner)
        router = PackageProductLifecycleRouter(
            owner=owner,
            transaction=transaction,
        )
        route = PackageProductRouteRequestV1(
            entrypoint=entrypoint,
            ingress=_request(),
        )

        committed = router.route(route)
        before = journal.records()
        replay = router.route(route)

        assert replay == committed
        assert (committed.phase, committed.disposition) == (
            "committed",
            "committed",
        )
        assert transaction.calls == [entrypoint]
        assert journal.records() == before
        _assert_no_capability_side_effect(tmp_path)
    elif case_id == "B-ENTRY-MATERIALIZER":
        owner, journal = _owner(
            tmp_path,
            facts=_facts("explicit_plugin_intent"),
        )
        transaction = _ManifestProductTransaction(owner)
        router = PackageProductLifecycleRouter(
            owner=owner,
            transaction=transaction,
        )
        route = PackageProductRouteRequestV1(
            entrypoint="direct_materializer",
            ingress=_request(),
        )

        refused = router.route(route)
        before = journal.records()
        replay = router.route(route)

        assert replay == refused
        assert (refused.phase, refused.disposition) == ("classified", "rejected")
        assert refused.failure is not None
        assert refused.failure.code == "package_route_unavailable"
        assert transaction.calls == []
        assert journal.records() == before
        _assert_no_capability_side_effect(tmp_path)
    elif case_id == "B-ENTRY-PUBLISH":
        owner, journal = _owner(
            tmp_path,
            facts=_facts("explicit_plugin_intent"),
        )
        transaction = _ManifestProductTransaction(owner)
        router = PackageProductLifecycleRouter(
            owner=owner,
            transaction=transaction,
        )
        current = _advance_lifecycle(owner, owner.submit(_request()), "staging")
        before = journal.records()
        attempt = PackageProductPublishAttemptV1(status=current)

        refused = router.refuse_direct_publish(attempt)
        after = journal.records()
        replay = router.refuse_direct_publish(attempt)

        assert replay == refused
        assert (refused.phase, refused.disposition) == ("staging", "rejected")
        assert refused.failure is not None
        assert refused.failure.code == "package_route_unavailable"
        assert owner.status(current.operation_id) == refused
        assert transaction.calls == []
        assert len(after) == len(before) + 1
        assert journal.records() == after
        _assert_no_capability_side_effect(tmp_path)
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
    elif case_id in IMPLEMENTED_B4C4E_LINUX_ADOPTION_FAILURE_MANIFEST_CASES:
        assert sys.platform.startswith("linux")
        fixture = _manifest_native_adoption_fixture(tmp_path, case_id=case_id)
        legacy_before = fixture.legacy_state.capture()
        product_before = fixture.product_projections.capture()

        failed = fixture.owner.adopt(fixture.request)
        after_first = (
            fixture.lifecycle_journal.records(),
            fixture.evidence_journal.records(),
            fixture.resolution_journal.records(),
            fixture.pin_journal.records(),
            fixture.staging_journal.records(),
            fixture.committed_sets.records(),
            fixture.fence_journal.records(),
            fixture.root_settlements.records(),
        )
        replay = fixture.owner.adopt(fixture.request)

        expected = {
            "B-COMPAT-ADOPT-UNAUTHORIZED": (
                "package_source_unauthorized",
                "rejected",
            ),
            "B-COMPAT-ADOPT-UNAVAILABLE": (
                "package_operation_timed_out",
                "retryable_failure",
            ),
        }[case_id]
        assert failed == replay
        assert (failed.code, failed.disposition) == expected
        assert failed.failure is not None
        assert failed.failure.stage == "acquiring"
        assert fixture.source_authority.authorize_calls == 1
        if fixture.source_authority.stream is not None:
            assert fixture.source_authority.stream.requests_started == 1
            assert fixture.source_authority.stream.redirects_started == 0
        assert fixture.resolver.calls == 0
        assert fixture.retention.physical_acquisitions == 0
        assert fixture.pin_journal.records() == ()
        assert fixture.staging_journal.records() == ()
        assert fixture.committed_sets.records() == ()
        assert fixture.root_settlements.records() == ()
        assert fixture.root_staging.calls == 0
        assert fixture.quarantine.attempt_names() == ()
        assert fixture.quarantine.total_residue_bytes() == 0
        assert fixture.legacy_state.capture() == legacy_before
        assert fixture.product_projections.capture() == product_before
        assert after_first == (
            fixture.lifecycle_journal.records(),
            fixture.evidence_journal.records(),
            fixture.resolution_journal.records(),
            fixture.pin_journal.records(),
            fixture.staging_journal.records(),
            fixture.committed_sets.records(),
            fixture.fence_journal.records(),
            fixture.root_settlements.records(),
        )
        assert fixture.secret not in repr((fixture.request, failed, replay))
        _assert_manifest_secret_absent(tmp_path, fixture.secret)
    elif case_id in IMPLEMENTED_B4C4G_LINUX_ADOPTION_PRECOMMIT_CRASH_MANIFEST_CASES:
        assert sys.platform.startswith("linux")
        for phase in ADOPTION_PRECOMMIT_CRASH_PHASES:
            recovery_root = tmp_path / f"recover-{phase}"
            recovery_root.mkdir(mode=0o700)
            fixture = _manifest_native_adoption_fixture(
                recovery_root,
                case_id=case_id,
                crash_after_phase=phase,
            )
            with pytest.raises(_ManifestCrashEdge, match=phase):
                fixture.owner.adopt(fixture.request)
            crashed = fixture.kernel.status(fixture.request.operation_id)
            assert crashed is not None
            assert (crashed.phase, crashed.disposition) == (phase, "active")

            prior_owner = fixture.owner
            prior_kernel = fixture.kernel
            fixture = _restart_manifest_native_adoption_fixture(fixture)
            assert fixture.owner is not prior_owner
            assert fixture.kernel is not prior_kernel
            recovered = fixture.owner.adopt(fixture.request)
            after_recovery = (
                fixture.lifecycle_journal.records(),
                fixture.evidence_journal.records(),
                fixture.resolution_journal.records(),
                fixture.pin_journal.records(),
                fixture.staging_journal.records(),
                fixture.committed_sets.records(),
                fixture.fence_journal.records(),
                fixture.root_settlements.records(),
            )
            replay = fixture.owner.adopt(fixture.request)

            assert recovered == replay, phase
            assert recovered.disposition == "adopted", phase
            assert recovered.receipt is not None
            assert fixture.source_authority.authorize_calls == 1
            assert fixture.source_authority.stream is not None
            assert fixture.source_authority.stream.requests_started == 1
            assert fixture.retention.physical_acquisitions == 1
            assert fixture.root_staging.calls == 1
            assert len(fixture.pin_journal.records()) == 1
            assert len(fixture.staging_journal.records()) == 1
            assert len(fixture.committed_sets.records()) == 1
            assert len(fixture.root_settlements.records()) == 1
            assert len(fixture.quarantine.attempt_names()) == 1
            assert fixture.quarantine.total_residue_bytes() <= 256 * 1024
            assert fixture.legacy_state.capture().evidence_id == (
                fixture.request.legacy_state_evidence_id
            )
            assert fixture.product_projections.capture() == (
                fixture.product_projection_before
            )
            assert after_recovery == (
                fixture.lifecycle_journal.records(),
                fixture.evidence_journal.records(),
                fixture.resolution_journal.records(),
                fixture.pin_journal.records(),
                fixture.staging_journal.records(),
                fixture.committed_sets.records(),
                fixture.fence_journal.records(),
                fixture.root_settlements.records(),
            )
            _assert_manifest_secret_absent(recovery_root, fixture.secret)
    elif case_id in IMPLEMENTED_B4C4F_LINUX_ADOPTION_COMMITTED_CRASH_MANIFEST_CASES:
        assert sys.platform.startswith("linux")
        fixture = _manifest_native_adoption_fixture(
            tmp_path,
            case_id=case_id,
            crash_after_committed=True,
        )
        with pytest.raises(_ManifestCrashAfterCommitted):
            fixture.owner.adopt(fixture.request)
        committed = fixture.kernel.status(fixture.request.operation_id)
        assert committed is not None
        assert (committed.phase, committed.disposition) == ("committed", "committed")
        assert isinstance(fixture.commit, _ManifestCrashAfterCommittedCommitOwner)
        crashed_commit = fixture.commit
        assert crashed_commit.pre_crash_receipt is not None
        after_crash = (
            fixture.lifecycle_journal.records(),
            fixture.evidence_journal.records(),
            fixture.resolution_journal.records(),
            fixture.pin_journal.records(),
            fixture.staging_journal.records(),
            fixture.committed_sets.records(),
            fixture.fence_journal.records(),
            fixture.root_settlements.records(),
        )

        prior_owner = fixture.owner
        prior_kernel = fixture.kernel
        fixture = _restart_manifest_native_adoption_fixture(fixture)
        assert fixture.owner is not prior_owner
        assert fixture.kernel is not prior_kernel
        recovered = fixture.owner.adopt(fixture.request)
        replay = fixture.owner.adopt(fixture.request)

        assert recovered == replay
        assert recovered.disposition == "adopted"
        assert recovered.code == "ok"
        assert recovered.receipt is not None
        assert recovered.receipt.publication == crashed_commit.pre_crash_receipt
        assert recovered.receipt.publication.committed_set.root_ref.installation_id == (
            "manifest-installation"
        )
        assert fixture.source_authority.authorize_calls == 1
        assert fixture.source_authority.stream is not None
        assert fixture.source_authority.stream.requests_started == 1
        assert fixture.retention.physical_acquisitions == 1
        pin = fixture.pin_journal.current_for_operation(fixture.request.operation_id)
        assert pin is not None and pin.state == "acquired"
        assert fixture.retention.receipts[fixture.request.operation_id] == pin
        assert fixture.root_staging.calls == 1
        assert len(fixture.staging_journal.records()) == 1
        assert len(fixture.committed_sets.records()) == 1
        assert len(fixture.root_settlements.records()) == 1
        assert crashed_commit.calls == 1
        assert fixture.legacy_state.capture().evidence_id == (
            fixture.request.legacy_state_evidence_id
        )
        assert fixture.product_projections.capture() == (
            fixture.product_projection_before
        )
        assert after_crash == (
            fixture.lifecycle_journal.records(),
            fixture.evidence_journal.records(),
            fixture.resolution_journal.records(),
            fixture.pin_journal.records(),
            fixture.staging_journal.records(),
            fixture.committed_sets.records(),
            fixture.fence_journal.records(),
            fixture.root_settlements.records(),
        )
        assert fixture.secret not in repr((fixture.request, recovered, replay))
        _assert_manifest_secret_absent(tmp_path, fixture.secret)
    elif case_id in IMPLEMENTED_B4C4D_LINUX_ADOPTION_MANIFEST_CASES:
        assert sys.platform.startswith("linux")
        fixture = _manifest_native_adoption_fixture(tmp_path)

        adopted = fixture.owner.adopt(fixture.request)
        after_first = (
            fixture.lifecycle_journal.records(),
            fixture.evidence_journal.records(),
            fixture.resolution_journal.records(),
            fixture.pin_journal.records(),
            fixture.staging_journal.records(),
            fixture.committed_sets.records(),
            fixture.fence_journal.records(),
            fixture.root_settlements.records(),
        )
        product_projection_after_first = fixture.product_projections.capture()
        replay = fixture.owner.adopt(fixture.request)

        assert adopted == replay
        assert adopted.disposition == "adopted"
        assert adopted.code == "ok"
        assert adopted.receipt is not None
        publication = adopted.receipt.publication
        assert publication.operation_id == fixture.request.operation_id
        assert publication.committed_set.root_ref.plugin_id == "acme.plugin"
        assert publication.committed_set.root_ref.installation_id == (
            "manifest-installation"
        )
        committed = fixture.kernel.status(fixture.request.operation_id)
        assert committed is not None
        assert committed.phase == "committed"
        assert committed.disposition == "committed"
        pin = fixture.pin_journal.current_for_operation(fixture.request.operation_id)
        assert pin is not None and pin.state == "acquired"
        assert fixture.retention.receipts[fixture.request.operation_id] == pin
        assert fixture.retention.physical_acquisitions == 1
        assert len(fixture.retention.calls) == 1
        assert fixture.source_authority.authorize_calls == 1
        assert fixture.source_authority.stream is not None
        assert fixture.source_authority.stream.requests_started == 1
        assert fixture.source_authority.stream.redirects_started == 0
        assert fixture.resolver.calls == 0
        assert fixture.root_targets.calls == 2
        assert fixture.root_staging.calls == 1
        assert len(fixture.staging_journal.records()) == 1
        assert len(fixture.committed_sets.records()) == 1
        assert len(fixture.root_settlements.records()) == 1
        assert fixture.fence_reader.calls == 4
        assert fixture.legacy_state.calls == 4
        current_fence = fixture.fence_journal.current(fixture.request.store_id)
        assert current_fence is not None
        assert current_fence.fenced_root_identity == _manifest_directory_identity(
            fixture.current_root
        )
        assert fixture.legacy_state.capture().evidence_id == (
            fixture.request.legacy_state_evidence_id
        )
        for path, payload in fixture.product_files:
            assert path.read_bytes() == payload
        assert fixture.product_projection_before == product_projection_after_first
        assert fixture.product_projection_before == (
            fixture.product_projections.capture()
        )
        assert after_first == (
            fixture.lifecycle_journal.records(),
            fixture.evidence_journal.records(),
            fixture.resolution_journal.records(),
            fixture.pin_journal.records(),
            fixture.staging_journal.records(),
            fixture.committed_sets.records(),
            fixture.fence_journal.records(),
            fixture.root_settlements.records(),
        )
        assert fixture.secret not in repr((fixture.request, adopted, replay))
        _assert_manifest_secret_absent(tmp_path, fixture.secret)
    elif case_id in IMPLEMENTED_B4A_COMMIT_ADMISSION_MANIFEST_CASES:
        fixture = _manifest_commit_admission_fixture(tmp_path)
        current = fixture.kernel.status("manifest-operation")
        committed_record = fixture.committed_sets.current("manifest-operation")
        assert current is not None and current.phase == "set_published"
        assert committed_record is not None
        if case_id == "B-PUB-UNCOMMITTED":
            admission_request = PackageCommitAdmissionRequestV1.create(
                operation_id=current.operation_id,
                request_fingerprint=current.request_fingerprint,
                product_id="coding",
                scope_id="workspace:manifest",
                installation_id="manifest-installation",
                plugin_id="acme.plugin",
                claimed_root_ref=committed_record.committed_set.root_ref,
                committed_set_id=committed_record.committed_set.set_id,
                closure_lock_digest=committed_record.closure_lock.lock_digest,
                publication_receipt=None,
            )
        else:
            publication = fixture.commit_owner.commit("manifest-operation")
            if case_id == "B-ADMISSION-DEPENDENCY":
                changes: dict[str, object] = {
                    "claimed_root_ref": committed_record.committed_set.dependency_refs[
                        0
                    ]
                }
            elif case_id == "B-ADMISSION-WRONG-SET":
                other_root = PluginRevisionRefV1.create(
                    store_identity="manifest-plugin-store",
                    store_revision="manifest-plugin-revision:other",
                    installation_id="manifest-installation",
                    plugin_id="acme.plugin",
                    distribution="acme",
                    version="1.0",
                    artifact_digest="d" * 64,
                    extraction_tree_digest="e" * 64,
                )
                changes = {
                    "claimed_root_ref": other_root,
                    "committed_set_id": "0" * 64,
                }
            elif case_id == "B-ADMISSION-WRONG-REQUEST":
                changes = {"request_fingerprint": "0" * 64}
            elif case_id == "B-ADMISSION-WRONG-OPERATION":
                changes = {"operation_id": "manifest-operation-other"}
            elif case_id == "B-ADMISSION-WRONG-SCOPE":
                changes = {"scope_id": "workspace:other"}
            elif case_id == "B-ADMISSION-WRONG-PLUGIN":
                changes = {"plugin_id": "other.plugin"}
            else:
                assert case_id == "B-ADMISSION-DIGEST-TAMPER"
                changes = {"closure_lock_digest": "0" * 64}
            admission_request = _manifest_admission_request(
                publication,
                **changes,
            )
        lifecycle_before = fixture.kernel.journal.records()
        committed_before = fixture.committed_sets.records()
        pins_before = fixture.pin_journal.records()

        result = fixture.admission_owner.admit(admission_request)

        assert result.code == "package_commit_admission_denied"
        assert result.disposition == "rejected"
        assert result.receipt is None
        assert result.failure is not None
        assert fixture.kernel.journal.records() == lifecycle_before
        assert fixture.committed_sets.records() == committed_before
        assert fixture.pin_journal.records() == pins_before
        assert fixture.pin_journal.current_for_operation("manifest-operation") == (
            fixture.pin_receipt
        )
        assert not (tmp_path / "binding.json").exists()
        assert not (tmp_path / "desired.json").exists()
    elif case_id in IMPLEMENTED_B4B_RETENTION_HANDOFF_MANIFEST_CASES:
        fixture = _manifest_retention_handoff_fixture(
            tmp_path,
            desired_inventory_revision=(
                1 if case_id == "B-HANDOFF-DESIRED-REJECT" else 0
            ),
        )
        request = fixture.request
        if case_id == "B-HANDOFF-BEFORE-DESIRED":
            fixture.desired.interruptions = 1
            result = fixture.owner.execute(request)
            assert result.disposition == "retryable_failure"
            assert result.code == "package_retention_handoff_interrupted"
            assert result.receipt is not None
            assert result.receipt.state == "dependency_pinned"
            assert result.failure is not None and result.failure.retryable
            assert fixture.desired.physical_commits == 0
            assert (
                fixture.pin_journal.current_for_operation(request.operation_id)
                == request.transaction_pin_receipt
            )
            result = fixture.owner.execute(request)
            assert result.disposition == "settled"
        elif case_id == "B-HANDOFF-AFTER-DESIRED":
            fixture.retention.settle_interruptions = 1
            result = fixture.owner.execute(request)
            assert result.disposition == "retryable_failure"
            assert result.code == "package_retention_handoff_interrupted"
            assert result.receipt is not None
            assert result.receipt.state == "desired_committed"
            assert fixture.desired.physical_commits == 1
            dependency = fixture.retention.current(request)
            assert dependency is not None and dependency.dependency_pins_live
            assert (
                fixture.pin_journal.current_for_operation(request.operation_id)
                == request.transaction_pin_receipt
            )
            result = fixture.owner.execute(request)
            assert result.disposition == "settled"
        elif case_id == "B-HANDOFF-AFTER-SETTLEMENT":
            fixture.retention.settle_postcommit_crashes = 1
            with pytest.raises(_ManifestProcessCrash):
                fixture.owner.execute(request)
            interrupted_head = fixture.journal.current(request.handoff_id)
            assert interrupted_head is not None
            assert interrupted_head.state == "desired_committed"
            dependency = fixture.retention.current(request)
            assert dependency is not None and dependency.state == "settled"
            assert (
                fixture.pin_journal.current_for_operation(request.operation_id).state
                == "released"
            )  # type: ignore[union-attr]
            records_before = fixture.journal.records()
            result = fixture.owner.execute(request)
            assert result.disposition == "settled"
            assert len(fixture.journal.records()) == len(records_before) + 1
            settled_records = fixture.journal.records()
            calls_before = (
                fixture.retention.acquire_calls,
                fixture.retention.abort_calls,
                fixture.retention.settle_calls,
                fixture.desired.calls,
            )
            replay = fixture.owner.execute(request)
            assert replay == result
            assert fixture.journal.records() == settled_records
            assert (
                fixture.retention.acquire_calls,
                fixture.retention.abort_calls,
                fixture.retention.settle_calls,
                fixture.desired.calls,
            ) == calls_before
        elif case_id == "B-HANDOFF-DESIRED-REJECT":
            result = fixture.owner.execute(request)
            assert result.disposition == "rejected"
            assert result.code == "package_desired_revision_conflict"
            assert result.receipt is not None and result.receipt.state == "aborted"
            dependency = fixture.retention.current(request)
            assert dependency is not None
            assert dependency.state == "aborted"
            assert not dependency.dependency_pins_live
            assert dependency.transaction_pin_receipt == (
                request.transaction_pin_receipt
            )
            assert fixture.desired.physical_commits == 0
            assert fixture.retention.physical_aborts == 1
            records_before = fixture.journal.records()
            assert fixture.owner.execute(request) == result
            assert fixture.journal.records() == records_before
        elif case_id == "B-HANDOFF-STALE-RECEIPT":
            fixture.desired.interruptions = 1
            interrupted = fixture.owner.execute(request)
            assert interrupted.receipt is not None
            assert interrupted.receipt.state == "dependency_pinned"
            opened = next(
                record.receipt
                for record in fixture.journal.records()
                if record.receipt is not None and record.receipt.state == "opened"
            )
            assert isinstance(opened, PackageRetentionHandoffReceiptV1)
            records_before = fixture.journal.records()
            calls_before = (
                fixture.retention.acquire_calls,
                fixture.retention.abort_calls,
                fixture.retention.settle_calls,
                fixture.desired.calls,
            )
            result = fixture.owner.execute(request, expected_receipt=opened)
            assert result.disposition == "rejected"
            assert result.code == "package_retention_handoff_stale"
            assert result.receipt == interrupted.receipt
            assert fixture.journal.records() == records_before
            assert (
                fixture.retention.acquire_calls,
                fixture.retention.abort_calls,
                fixture.retention.settle_calls,
                fixture.desired.calls,
            ) == calls_before
        else:
            assert case_id == "B-HANDOFF-CONCURRENT-REPLAY"
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = tuple(
                    executor.map(
                        lambda _index: fixture.owner.execute(request), range(16)
                    )
                )
            assert len(set(results)) == 1
            result = results[0]
            assert result.disposition == "settled"
            assert fixture.retention.physical_acquisitions == 1
            assert fixture.retention.physical_settlements == 1
            assert fixture.desired.physical_commits == 1

        dependency = fixture.retention.current(request)
        assert dependency is not None
        assert dependency.request.target_ref_ids == (
            request.dependency_pin_request.target_ref_ids
        )
        assert len(dependency.pin_ids) == len(
            request.dependency_pin_request.target_ref_ids
        )
        assert not fixture.retention.zero_pin_observed
        assert PackageRetentionHandoffRequestV1.from_dict(request.to_dict()) == request
        assert PackageRetentionHandoffResultV1.from_dict(result.to_dict()) == result
        extended = request.to_dict()
        extended["reopenPath"] = "/tmp/forged"
        with pytest.raises(ValueError, match="versioned schema"):
            PackageRetentionHandoffRequestV1.from_dict(extended)
        forged = request.to_dict()
        forged["handoffId"] = "0" * 64
        with pytest.raises(ValueError, match="does not match"):
            PackageRetentionHandoffRequestV1.from_dict(forged)
        assert (
            PackageRetentionHandoffJournal(fixture.journal.path).records()
            == fixture.journal.records()
        )
        serialized = repr((result, fixture.journal.records())).lower()
        for forbidden in ("password", "credential", "token", "reopen", "handle"):
            assert forbidden not in serialized
        assert not (tmp_path / "binding.json").exists()
        assert not (tmp_path / "desired.json").exists()
    elif case_id in IMPLEMENTED_B4C3C_LINUX_OFFLINE_RESTORE_MANIFEST_CASES:
        assert sys.platform.startswith("linux")
        fixture = _manifest_linux_offline_restore_fixture(tmp_path)
        journal_before = fixture.journal.path.read_bytes()
        b_before = (fixture.current_b_root / "epoch-b.json").read_bytes()
        source_before = (fixture.source / "legacy-state.json").read_bytes()

        result = fixture.owner.restore(fixture.request)
        replay = fixture.owner.restore(fixture.request)

        assert result == replay
        assert result.disposition == "restored"
        assert result.code == "ok"
        assert result.failure is None
        assert result.materialization is not None
        assert result.activation is not None
        assert result.materialization.legacy_snapshot_exact is True
        assert result.materialization.b_namespace_unreachable is True
        assert result.activation.exclusive_old_runtime is True
        restored = (
            fixture.restore_root
            / fixture.request.restore_namespace_id
            / "payload"
            / "legacy-state.json"
        )
        assert restored.read_bytes() == source_before
        assert (fixture.activation_root / "active-runtime.json").is_file()
        assert fixture.journal.path.read_bytes() == journal_before
        assert (fixture.current_b_root / "epoch-b.json").read_bytes() == b_before
        assert fixture.coordination.calls == 2
        assert fixture.snapshots.calls == 2
        serialized = repr(result).lower()
        for forbidden in (
            "password",
            "credential",
            "token",
            "handle",
            str(tmp_path).lower(),
        ):
            assert forbidden not in serialized

        fixture.activation.deactivate(result.activation)
        fixture.materializer.discard(result.materialization)
        assert not (
            fixture.restore_root / fixture.request.restore_namespace_id
        ).exists()
        assert not (fixture.activation_root / "active-runtime.json").exists()
    elif case_id in IMPLEMENTED_B4C1_POSIX_EPOCH_CUTOVER_MANIFEST_CASES:
        assert os.name == "posix"
        pre_fence_live = case_id == "B-COMPAT-PREFENCE-LIVE-POSIX"
        fixture = _manifest_posix_epoch_cutover_fixture(
            tmp_path,
            pre_fence_live=pre_fence_live,
        )
        legacy_before = (fixture.legacy / "state.json").read_bytes()

        result = fixture.owner.cutover(fixture.request)

        if pre_fence_live:
            assert result.disposition == "rejected"
            assert result.code == "package_runtime_epoch_unsupported"
            assert result.failure is not None
            assert result.failure.barrier == "pre_fence"
            assert result.failure.operator_action == "upgrade_runtime"
            assert result.failure.evidence_ref == "f" * 64
            assert result.fence is None
            assert result.switch_receipt is None
            assert fixture.snapshots.calls == 0
            assert fixture.journal.records() == ()
            assert tuple(fixture.epochs.iterdir()) == ()
        else:
            assert result.disposition == "fenced"
            assert result.code == "ok"
            assert result.failure is None
            assert result.fence is not None
            assert result.switch_receipt is not None
            assert result.fence.request.namespace_id == fixture.request.namespace_id
            assert result.fence.request.root_switch_receipt_id == (
                result.switch_receipt.switch_receipt_id
            )
            assert result.fence == fixture.journal.current(fixture.request.store_id)
            assert len(fixture.journal.records()) == 1
            assert fixture.snapshots.calls == 1
            replay = fixture.owner.cutover(fixture.request)
            assert replay == result
            assert fixture.coordination.calls == 1
            assert fixture.snapshots.calls == 1
            assert (fixture.epochs / fixture.request.namespace_id).is_dir()
            assert not (fixture.authority / "active-root").exists()
            detached = tmp_path / "manifest-package-epoch-detached"
            fixture.authority.rename(detached)
            detached.rename(fixture.authority)
            detached_epoch = tmp_path / "manifest-detached-epoch"
            (fixture.epochs / fixture.request.namespace_id).rename(detached_epoch)
            detached_epoch.rmdir()
        assert fixture.coordination.calls == 1
        assert (fixture.legacy / "state.json").read_bytes() == legacy_before
        assert (
            PackagePosixEpochCutoverRequestV1.from_dict(fixture.request.to_dict())
            == fixture.request
        )
        assert PackagePosixEpochCutoverResultV1.from_dict(result.to_dict()) == result
        serialized = repr((fixture.request, result)).lower()
        for forbidden in (
            "password",
            "credential",
            "token",
            "handle",
            str(tmp_path).lower(),
        ):
            assert forbidden not in serialized
        assert not (tmp_path / "binding.json").exists()
        assert not (tmp_path / "desired.json").exists()
    elif case_id in IMPLEMENTED_B4C2_WINDOWS_EPOCH_CUTOVER_MANIFEST_CASES:
        assert os.name == "nt"
        pre_fence_live = case_id == "B-COMPAT-PREFENCE-LIVE-WINDOWS"
        fixture = _manifest_windows_epoch_cutover_fixture(
            tmp_path,
            pre_fence_live=pre_fence_live,
        )
        legacy_before = (fixture.legacy / "state.json").read_bytes()

        result = fixture.owner.cutover(fixture.request)

        if pre_fence_live:
            assert result.disposition == "rejected"
            assert result.code == "package_runtime_epoch_unsupported"
            assert result.failure is not None
            assert result.failure.barrier == "pre_fence"
            assert result.failure.operator_action == "upgrade_runtime"
            assert result.failure.evidence_ref == "f" * 64
            assert result.fence is None
            assert result.switch_receipt is None
            assert fixture.snapshots.calls == 0
            assert fixture.journal.records() == ()
            assert tuple(fixture.epochs.iterdir()) == ()
        else:
            assert result.disposition == "fenced"
            assert result.code == "ok"
            assert result.failure is None
            assert result.fence is not None
            assert result.switch_receipt is not None
            assert result.fence.request.namespace_id == fixture.request.namespace_id
            assert result.fence.request.root_switch_receipt_id == (
                result.switch_receipt.switch_receipt_id
            )
            assert result.fence == fixture.journal.current(fixture.request.store_id)
            assert len(fixture.journal.records()) == 1
            assert fixture.snapshots.calls == 1
            replay = fixture.owner.cutover(fixture.request)
            assert replay == result
            assert fixture.coordination.calls == 1
            assert fixture.snapshots.calls == 1
            assert (fixture.epochs / fixture.request.namespace_id).is_dir()
            assert not (fixture.authority / "active-root").exists()
            detached = tmp_path / "manifest-package-epoch-detached"
            fixture.authority.rename(detached)
            detached.rename(fixture.authority)
            detached_epoch = tmp_path / "manifest-detached-epoch"
            (fixture.epochs / fixture.request.namespace_id).rename(detached_epoch)
            detached_epoch.rmdir()
        assert fixture.coordination.calls == 1
        assert (fixture.legacy / "state.json").read_bytes() == legacy_before
        assert (
            PackageWindowsEpochCutoverRequestV1.from_dict(fixture.request.to_dict())
            == fixture.request
        )
        assert PackageWindowsEpochCutoverResultV1.from_dict(result.to_dict()) == result
        serialized = repr((fixture.request, result)).lower()
        for forbidden in (
            "password",
            "credential",
            "token",
            "handle",
            str(tmp_path).lower(),
        ):
            assert forbidden not in serialized
        assert not (tmp_path / "binding.json").exists()
        assert not (tmp_path / "desired.json").exists()
    elif case_id in IMPLEMENTED_B4C0_EPOCH_ADMISSION_MANIFEST_CASES:
        mixed_epoch = case_id == "B-COMPAT-MIXED"
        fixture = _manifest_epoch_admission_fixture(
            tmp_path,
            mixed_epoch=mixed_epoch,
        )
        records_before = fixture.journal.records()

        result = fixture.owner.admit(fixture.request)

        assert result.disposition == "rejected"
        assert result.code == "package_runtime_epoch_unsupported"
        assert result.receipt is None
        assert result.failure is not None
        assert result.failure.operator_action == (
            "offline_restore" if mixed_epoch else "upgrade_runtime"
        )
        assert fixture.leases.calls == (1 if mixed_epoch else 0)
        assert fixture.journal.records() == records_before
        assert (
            PackageEpochRuntimeAdmissionRequestV1.from_dict(fixture.request.to_dict())
            == fixture.request
        )
        assert PackageEpochRuntimeAdmissionResultV1.from_dict(result.to_dict()) == (
            result
        )
        serialized = repr((fixture.request, result, records_before)).lower()
        for forbidden in ("password", "credential", "token", "path", "handle"):
            assert forbidden not in serialized
        assert not (tmp_path / "binding.json").exists()
        assert not (tmp_path / "desired.json").exists()
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
    elif case_id in IMPLEMENTED_B3E_PIN_MANIFEST_CASES:
        secret = f"manifest-secret-{case_id.lower()}"
        environment = _closure_environment()
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
        closure_execution = PackageClosureExecutionRequestV2(
            artifact=_artifact_execution(classified, secret=secret),
            resolution_environment=environment,
            budgets=PackageClosureBudgetV1(),
        )
        closure_result = closure_owner.execute(closure_execution)
        assert closure_result.candidate is not None
        assert closure_result.status.phase == "closure_verified"
        retention = _TransactionPinRetentionOwner()
        pin_journal = PackageTransactionPinJournal(
            tmp_path / "package-transaction-pins.jsonl"
        )
        pin_owner = PackageTransactionPinLifecycleOwner(
            kernel=kernel,
            closure_plans=resolution_journal,
            retention=retention,
            pin_journal=pin_journal,
        )
        recovery_identity = "manifest-recovery-transaction-pinned"

        pinned = pin_owner.pin(
            closure_result.candidate,
            recovery_identity=recovery_identity,
        )

        assert pinned.status.phase == "transaction_pinned"
        assert pinned.status.disposition == "active"
        assert pinned.receipt is not None
        closure_result.candidate.suspend_for_recovery()
        evidence_before = evidence_journal.records()
        resolution_before = resolution_journal.records()
        lifecycle_before = journal.records()
        source_calls = source_authority.authorize_calls
        interrupted = kernel.interrupt(
            pinned.status.operation_id,
            expected_phase="transaction_pinned",
            expected_journal_revision=pinned.status.journal_revision,
            expected_attempt_epoch=pinned.status.attempt_epoch,
        )
        restarted_kernel = PackageLifecycleOwner(
            journal=PackageLifecycleJournal(journal.path),
            classification_authority=_Authority(_facts("explicit_plugin_intent")),
            enabled=True,
        )
        restarted_owner = PackageTransactionPinLifecycleOwner(
            kernel=restarted_kernel,
            closure_plans=PackageClosureResolutionJournal(resolution_journal.path),
            retention=retention,
            pin_journal=PackageTransactionPinJournal(pin_journal.path),
        )

        recovered = restarted_owner.recover(
            pinned.status.operation_id,
            recovery_identity=recovery_identity,
        )

        assert interrupted.phase == "transaction_pinned"
        assert interrupted.disposition == "retryable_failure"
        assert interrupted.failure is not None
        assert interrupted.failure.code == "package_operation_interrupted"
        assert recovered.status == interrupted
        assert recovered.receipt == pinned.receipt
        assert recovered.candidate is None
        assert retention.receipts[pinned.status.operation_id] == pinned.receipt
        assert retention.physical_acquisitions == 1
        assert len(retention.calls) == 2
        assert len(pin_journal.records()) == 1
        assert len(journal.records()) == len(lifecycle_before) + 1
        assert evidence_journal.records() == evidence_before
        assert resolution_journal.records() == resolution_before
        assert source_authority.authorize_calls == source_calls == 1
        assert resolver.calls == 0
        assert cleanup_journal.records() == ()
        assert len(store.attempt_names()) == 1
        assert not (tmp_path / "published").exists()
        assert not (tmp_path / "binding.json").exists()
        assert not (tmp_path / "desired.json").exists()
        assert secret not in repr(recovered)
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert secret.encode() not in path.read_bytes()
    elif case_id in IMPLEMENTED_B3E_STAGING_SET_MANIFEST_CASES:
        secret = f"manifest-secret-{case_id.lower()}"
        environment = _closure_environment()
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
        closure_result = closure_owner.execute(
            PackageClosureExecutionRequestV2(
                artifact=_artifact_execution(classified, secret=secret),
                resolution_environment=environment,
                budgets=PackageClosureBudgetV1(),
            )
        )
        assert closure_result.candidate is not None
        retention = _TransactionPinRetentionOwner()
        pin_journal = PackageTransactionPinJournal(
            tmp_path / "package-transaction-pins.jsonl"
        )
        pin_owner = PackageTransactionPinLifecycleOwner(
            kernel=kernel,
            closure_plans=resolution_journal,
            retention=retention,
            pin_journal=pin_journal,
        )
        pinned = pin_owner.pin(
            closure_result.candidate,
            recovery_identity="manifest-recovery-staging-set",
        )
        assert pinned.status.phase == "transaction_pinned"
        assert pinned.receipt is not None
        lifecycle_before = journal.records()
        evidence_before = evidence_journal.records()
        resolution_before = resolution_journal.records()
        source_calls = source_authority.authorize_calls
        staging_journal = PackageArtifactStagingJournal(
            tmp_path / "package-artifact-staging.jsonl"
        )
        committed_sets = PackageCommittedSetJournal(
            tmp_path / "package-committed-sets.jsonl"
        )
        dependency_staging = _ManifestDependencyStagingOwner()
        root_staging = _ManifestRootStagingOwner()
        root_targets = _ManifestRootTargetAuthority()
        crash_phase: PackageLifecyclePhase = (
            "staging" if case_id == "B-CRASH-STAGING" else "set_published"
        )
        crash_kernel = _CrashAfterPhasePackageOwner(
            journal=PackageLifecycleJournal(journal.path),
            facts=_facts("explicit_plugin_intent"),
            crash_after=crash_phase,
        )
        staging_owner = PackageStagingSetLifecycleOwner(
            kernel=crash_kernel,
            classification_recheck=_StableClassificationRecheck(),
            closure_plans=PackageClosureResolutionJournal(resolution_journal.path),
            pin_journal=PackageTransactionPinJournal(pin_journal.path),
            root_targets=root_targets,
            dependency_staging=dependency_staging,
            root_staging=root_staging,
            staging_journal=staging_journal,
            committed_sets=committed_sets,
        )

        with pytest.raises(_ManifestCrashEdge, match=crash_phase):
            staging_owner.stage_and_publish(closure_result.candidate)

        crashed = crash_kernel.status(classified.operation_id)
        assert crashed is not None and crashed.phase == crash_phase
        interrupted = crash_kernel.interrupt(
            crashed.operation_id,
            expected_phase=crashed.phase,
            expected_journal_revision=crashed.journal_revision,
            expected_attempt_epoch=crashed.attempt_epoch,
        )
        restarted_kernel = PackageLifecycleOwner(
            journal=PackageLifecycleJournal(journal.path),
            classification_authority=_Authority(_facts("explicit_plugin_intent")),
            enabled=True,
        )
        restarted_owner = PackageStagingSetLifecycleOwner(
            kernel=restarted_kernel,
            classification_recheck=_StableClassificationRecheck(),
            closure_plans=PackageClosureResolutionJournal(resolution_journal.path),
            pin_journal=PackageTransactionPinJournal(pin_journal.path),
            root_targets=root_targets,
            dependency_staging=dependency_staging,
            root_staging=root_staging,
            staging_journal=PackageArtifactStagingJournal(staging_journal.path),
            committed_sets=PackageCommittedSetJournal(committed_sets.path),
        )
        recovered = restarted_owner.recover(classified.operation_id)

        assert interrupted.phase == crash_phase
        assert interrupted.disposition == "retryable_failure"
        assert interrupted.failure is not None
        assert interrupted.failure.code == "package_operation_interrupted"
        assert recovered.status == interrupted
        assert len(recovered.staging_receipts) == 1
        assert recovered.staging_receipts == staging_journal.receipts(
            classified.operation_id
        )
        if case_id == "B-CRASH-STAGING":
            assert recovered.committed_set is None
            assert committed_sets.records() == ()
        else:
            assert recovered.committed_set is not None
            assert recovered.committed_set == committed_sets.records()[0].committed_set
        assert root_targets.calls == 1
        assert root_staging.physical_stages == 1
        assert dependency_staging.physical_stages == 0
        assert retention.receipts[classified.operation_id] == pinned.receipt
        assert retention.physical_acquisitions == 1
        assert len(pin_journal.records()) == 1
        expected_lifecycle_growth = 2 if case_id == "B-CRASH-STAGING" else 3
        assert (
            len(journal.records()) == len(lifecycle_before) + expected_lifecycle_growth
        )
        assert evidence_journal.records() == evidence_before
        assert resolution_journal.records() == resolution_before
        assert source_authority.authorize_calls == source_calls == 1
        assert resolver.calls == 0
        assert cleanup_journal.records() == ()
        assert len(store.attempt_names()) == 1
        assert not (tmp_path / "published").exists()
        assert not (tmp_path / "binding.json").exists()
        assert not (tmp_path / "desired.json").exists()
        assert secret not in repr(recovered)
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert secret.encode() not in path.read_bytes()
    elif case_id in (
        IMPLEMENTED_B3E3C1_POSIX_MANIFEST_CASES
        + IMPLEMENTED_B3E3C2_WINDOWS_MANIFEST_CASES
        + IMPLEMENTED_B3E3C3_SETTLEMENT_MANIFEST_CASES
    ):
        windows_case = case_id in IMPLEMENTED_B3E3C2_WINDOWS_MANIFEST_CASES
        assert os.name == ("nt" if windows_case else "posix")
        secret = f"manifest-secret-{case_id.lower()}"
        environment = _closure_environment()
        (
            kernel,
            _artifact_owner,
            journal,
            evidence_journal,
            cleanup_journal,
            quarantine,
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
        closure_result = closure_owner.execute(
            PackageClosureExecutionRequestV2(
                artifact=_artifact_execution(classified, secret=secret),
                resolution_environment=environment,
                budgets=PackageClosureBudgetV1(),
            )
        )
        assert closure_result.candidate is not None
        retention = _TransactionPinRetentionOwner()
        pin_journal = PackageTransactionPinJournal(
            tmp_path / "package-transaction-pins.jsonl"
        )
        pin_owner = PackageTransactionPinLifecycleOwner(
            kernel=kernel,
            closure_plans=resolution_journal,
            retention=retention,
            pin_journal=pin_journal,
        )
        pinned = pin_owner.pin(
            closure_result.candidate,
            recovery_identity="manifest-recovery-native-materialization",
        )
        assert pinned.receipt is not None
        assert pinned.status.classification is not None

        dependency_root = tmp_path / "dependency-publication-store"
        plugin_authority = tmp_path / "plugin-publication-authority"
        plugin_root = plugin_authority / "plugin-revision-store"
        dependency_root.mkdir(mode=0o700)
        plugin_root.mkdir(parents=True, mode=0o700)
        outside = tmp_path / "outside-publication-sentinel"
        outside.write_bytes(b"preserve")
        outside_target = tmp_path / "outside-publication-target"
        outside_target.mkdir()
        outside_target_sentinel = outside_target / "sentinel"
        outside_target_sentinel.write_bytes(b"preserve")
        root_targets = _ManifestRootTargetAuthority()
        request = kernel.journal.request(classified.operation_id)
        assert request is not None
        target = root_targets.issue_target(request, pinned.status.classification)
        root_staging_request = PackageArtifactStagingRequestV1.create(
            closure_result.candidate.plan,
            node_id=closure_result.candidate.plan.root_node_id,
            request_fingerprint=pinned.status.request_fingerprint,
            classification_fingerprint=pinned.status.classification.evidence_ref,
            pin_receipt=pinned.receipt,
            root_target=target,
        )
        precreated: Path | None = None
        staging_path = plugin_root / (
            f"staging-{root_staging_request.staging_request_id}"
        )
        detached_root = plugin_authority / "plugin-revision-store-detached"
        detached_authority = tmp_path / "plugin-publication-authority-detached"
        detached_entry = staging_path / "root_plugin-detached"
        detached_staging = plugin_root / "staging-detached"
        root_swapped = False
        ancestor_swapped = False
        entry_swapped = False
        staging_swapped = False

        if case_id == "B-PUB-PRECREATE":
            precreated = plugin_root / (
                f"staging-{root_staging_request.staging_request_id}"
            )
            precreated.mkdir(mode=0o700)
            (precreated / "attacker-link").symlink_to(outside)

        def commit_probe() -> None:
            nonlocal root_swapped, ancestor_swapped, entry_swapped, staging_swapped
            if case_id == "B-PUB-POSIX-ROOT-SWAP":
                plugin_root.rename(detached_root)
                plugin_root.mkdir(mode=0o700)
                root_swapped = True
            elif case_id == "B-PUB-POSIX-ANCESTOR-SWAP":
                plugin_authority.rename(detached_authority)
                plugin_root.mkdir(parents=True, mode=0o700)
                ancestor_swapped = True
            elif case_id == "B-PUB-POSIX-HANDLE-REJECT":
                plugin_root.chmod(0o755)
            elif case_id == "B-PUB-SWAP-WINDOWS":
                (staging_path / "root_plugin").rename(detached_entry)
                entry_swapped = True
                (staging_path / "root_plugin").symlink_to(
                    outside_target,
                    target_is_directory=True,
                )
            elif case_id == "B-PUB-WIN-ROOT-ABA":
                plugin_root.rename(detached_root)
                root_swapped = True
                shutil.copytree(detached_root, plugin_root)
            elif case_id == "B-PUB-WIN-ANCESTOR-ABA":
                plugin_authority.rename(detached_authority)
                ancestor_swapped = True
                plugin_authority.symlink_to(
                    outside_target,
                    target_is_directory=True,
                )
            elif case_id == "B-PUB-WIN-HANDLE-REJECT":
                staging_path.rename(detached_staging)
                staging_swapped = True
                staging_path.symlink_to(outside_target, target_is_directory=True)

        handle_success = case_id in {
            "B-PUB-POSIX-HANDLE-SUCCESS",
            "B-PUB-WIN-HANDLE-SUCCESS",
            "B-PUB-REUSE",
        }
        active_probe = (
            None if case_id == "B-PUB-PRECREATE" or handle_success else commit_probe
        )
        dependency_settlements = PackageStoreSettlementJournal(
            tmp_path / "dependency-store-settlements.jsonl"
        )
        plugin_settlements = PackageStoreSettlementJournal(
            tmp_path / "plugin-store-settlements.jsonl"
        )
        if windows_case:
            dependency_staging = WindowsPackageDependencyMaterializationStore(
                dependency_root,
                store_identity="manifest-dependency-store",
                settlement_journal=dependency_settlements,
            )
            native_root_store = WindowsPackagePluginRootMaterializationStore(
                plugin_root,
                store_identity="manifest-plugin-revision-store",
                settlement_journal=plugin_settlements,
                commit_probe=active_probe,
            )
        else:
            dependency_staging = PosixPackageDependencyMaterializationStore(
                dependency_root,
                store_identity="manifest-dependency-store",
                settlement_journal=dependency_settlements,
            )
            native_root_store = PosixPackagePluginRootMaterializationStore(
                plugin_root,
                store_identity="manifest-plugin-revision-store",
                settlement_journal=plugin_settlements,
                commit_probe=active_probe,
            )
        preexisting_receipt: PackageArtifactStagingReceiptV1 | None = None
        if case_id in IMPLEMENTED_B3E3C3_SETTLEMENT_MANIFEST_CASES:
            assert not windows_case
            root_candidate = next(
                candidate
                for candidate in closure_result.candidate.candidates
                if candidate.evidence.node_id
                == closure_result.candidate.plan.root_node_id
            )
            preexisting_receipt = native_root_store.stage_root(
                root_staging_request,
                root_candidate,
            )
            if case_id == "B-PUB-COLLISION":
                published = plugin_root / (
                    f"revision-{preexisting_receipt.stable_ref.ref_id}"
                )
                detached = tmp_path / "detached-published-revision"
                published.rename(detached)
                shutil.copytree(detached, published)
            native_root_store = PosixPackagePluginRootMaterializationStore(
                plugin_root,
                store_identity="manifest-plugin-revision-store",
                settlement_journal=PackageStoreSettlementJournal(
                    plugin_settlements.path
                ),
            )
        root_staging = _ManifestNativeRootStagingOwner(
            native_root_store,
            verify_reuse=handle_success,
        )
        staging_journal = PackageArtifactStagingJournal(
            tmp_path / "package-artifact-staging.jsonl"
        )
        committed_sets = PackageCommittedSetJournal(
            tmp_path / "package-committed-sets.jsonl"
        )
        staging_owner = PackageStagingSetLifecycleOwner(
            kernel=kernel,
            classification_recheck=_StableClassificationRecheck(),
            closure_plans=resolution_journal,
            pin_journal=pin_journal,
            root_targets=root_targets,
            dependency_staging=dependency_staging,
            root_staging=root_staging,
            staging_journal=staging_journal,
            committed_sets=committed_sets,
        )

        result = staging_owner.stage_and_publish(closure_result.candidate)

        if root_swapped:
            if windows_case:
                if plugin_root.exists():
                    shutil.rmtree(plugin_root)
                detached_root.rename(plugin_root)
            else:
                replacement = plugin_authority / "plugin-revision-store-replacement"
                plugin_root.rename(replacement)
                detached_root.rename(plugin_root)
                replacement.rmdir()
        if ancestor_swapped:
            if windows_case:
                if plugin_authority.is_symlink():
                    plugin_authority.unlink()
                detached_authority.rename(plugin_authority)
            else:
                replacement_authority = (
                    tmp_path / "plugin-publication-authority-replacement"
                )
                plugin_authority.rename(replacement_authority)
                detached_authority.rename(plugin_authority)
                (replacement_authority / "plugin-revision-store").rmdir()
                replacement_authority.rmdir()
        if entry_swapped:
            if (staging_path / "root_plugin").is_symlink():
                (staging_path / "root_plugin").unlink()
            shutil.rmtree(staging_path)
        if staging_swapped:
            if staging_path.is_symlink():
                staging_path.unlink()
            shutil.rmtree(detached_staging)
        if case_id == "B-PUB-POSIX-HANDLE-REJECT":
            plugin_root.chmod(0o700)

        if handle_success:
            assert result.status.phase == "set_published"
            assert result.status.disposition == "active"
            assert result.committed_set is not None
            assert len(result.staging_receipts) == 1
            assert root_staging.same_receipt is True
            if preexisting_receipt is not None:
                assert result.staging_receipts == (preexisting_receipt,)
                assert len(plugin_settlements.records()) == 1
            committed = kernel.advance(
                result.status.operation_id,
                next_phase="committed",
                expected_phase="set_published",
                expected_journal_revision=result.status.journal_revision,
                expected_attempt_epoch=result.status.attempt_epoch,
            )
            assert committed.phase == "committed"
            assert committed.disposition == "committed"
            assert len(committed_sets.records()) == 1
            assert len(staging_journal.records()) == 1
            if case_id == "B-PUB-REUSE":
                assert preexisting_receipt is not None
                restarted_store = PosixPackagePluginRootMaterializationStore(
                    plugin_root,
                    store_identity="manifest-plugin-revision-store",
                    settlement_journal=PackageStoreSettlementJournal(
                        plugin_settlements.path
                    ),
                )
                settlement_count = len(plugin_settlements.records())
                assert (
                    restarted_store.validate_root_receipt(preexisting_receipt)
                    == preexisting_receipt
                )
                assert len(plugin_settlements.records()) == settlement_count == 1
            assert (
                len(
                    tuple(
                        entry
                        for entry in plugin_root.iterdir()
                        if entry.name.startswith("revision-")
                    )
                )
                == 1
            )
        else:
            assert result.status.phase == "staging"
            assert result.status.disposition == "rejected"
            assert result.status.failure is not None
            expected_failure = (
                "package_publication_collision"
                if case_id == "B-PUB-COLLISION"
                else "package_publication_root_untrusted"
            )
            assert result.status.failure.code == expected_failure
            assert result.staging_receipts == ()
            assert staging_journal.records() == ()
            assert committed_sets.records() == ()
            if case_id == "B-PUB-COLLISION":
                assert preexisting_receipt is not None
                assert len(plugin_settlements.records()) == 1
            else:
                assert not any(
                    entry.name.startswith("revision-")
                    for entry in plugin_root.iterdir()
                )

        assert (
            pin_journal.current_for_operation(classified.operation_id) == pinned.receipt
        )
        assert retention.receipts[classified.operation_id] == pinned.receipt
        assert source_authority.authorize_calls == 1
        assert resolver.calls == 0
        assert cleanup_journal.records() == ()
        assert len(quarantine.attempt_names()) == 1
        assert outside.read_bytes() == b"preserve"
        assert outside_target_sentinel.read_bytes() == b"preserve"
        assert not (tmp_path / "binding.json").exists()
        assert not (tmp_path / "desired.json").exists()
        moved_root = plugin_authority / "plugin-revision-store-moved"
        plugin_root.rename(moved_root)
        moved_root.rename(plugin_root)
        if precreated is not None:
            (precreated / "attacker-link").unlink()
            precreated.rmdir()
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
