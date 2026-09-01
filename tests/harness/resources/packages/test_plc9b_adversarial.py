from __future__ import annotations

import base64
import csv
import inspect
import io
import stat
import struct
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
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
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionSinkPort,
    PackageAcquisitionBudgetV1,
    PackageAcquisitionError,
    PackageAcquisitionOwner,
    PackageAcquisitionRequestV1,
    PackageQuarantineStore,
    SourceAdapterResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.cleanup import (
    PackageQuarantineCleanupJournal,
    PackageQuarantineCleanupOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.phase_evidence import (
    PackageArtifactEvidenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRequestV1,
    PluginBoundPackageClassificationV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.runtime import (
    PackageArtifactExecutionRequestV1,
    PackageArtifactLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    PackageWheelVerifier,
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

EXECUTABLE_MANIFEST_CASES = (
    IMPLEMENTED_B1_MANIFEST_CASES
    + IMPLEMENTED_B2_MANIFEST_CASES
    + IMPLEMENTED_B2H_MANIFEST_CASES
    + IMPLEMENTED_B2I_WINDOWS_MANIFEST_CASES
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
                info.external_attr = (
                    (entry_modes or {}).get(name, stat.S_IFREG | 0o644) << 16
                )
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
            payload=_wheel_bytes(
                extra_files={windows_paths[case_id]: b"hostile"}
            )
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

        chunks = (self.payload if self.payload is not None else b"wheel",)
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
        resolution_environment_fingerprint="e" * 64,
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
    inspection_budgets: PackageInspectionBudgetV1 | None = None,
    wheel_verifier: PackageWheelVerifier | None = None,
    supported_tags: frozenset[str] | None = None,
):
    lifecycle_journal = PackageLifecycleJournal(
        tmp_path / "package-lifecycle.jsonl"
    )
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
        wheel_verifier=wheel_verifier or PackageWheelVerifier(),
        acquisition_budgets=PackageAcquisitionBudgetV1(
            max_transport_bytes=(
                8 if case_id == "B-ACQ-BYTES" else 256 * 1024
            ),
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
        assert "plugin_bound" not in inspect.signature(
            PackageLifecycleIngressRequestV1
        ).parameters
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
        assert evidence_journal.records() == ()
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
    elif case_id in (
        IMPLEMENTED_B2H_MANIFEST_CASES
        + IMPLEMENTED_B2I_WINDOWS_MANIFEST_CASES
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
        assert len(evidence) == 1
        assert evidence[0].evidence_kind == "bounded_acquisition"
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
