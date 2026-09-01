from __future__ import annotations

import base64
import csv
import io
import os
import stat
import struct
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionSinkPort,
    PackageAcquisitionBudgetV1,
    PackageAcquisitionOwner,
    PackageAcquisitionRequestV1,
    PackageQuarantineStore,
    SourceAdapterResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    PackageWheelVerificationError,
    PackageWheelVerifier,
    VerifiedWheelArtifactV1,
)

WHEEL_FILENAME = "acme_plugin-1.0-py3-none-any.whl"
DIST_INFO = "acme_plugin-1.0.dist-info"


@dataclass
class _Stream:
    envelope: AuthenticatedSourceEnvelopeV1
    payload: bytes

    def transfer_to(self, sink: BoundedAcquisitionSinkPort) -> SourceAdapterResultV1:
        sink.begin_request()
        for offset in range(0, len(self.payload), 13):
            sink.write(self.payload[offset : offset + 13])
        return SourceAdapterResultV1(disposition="complete")


@dataclass
class _Authority:
    stream: _Stream

    def authorize(self, _request: PackageAcquisitionRequestV1) -> _Stream:
        return self.stream


@dataclass
class _AdvancingClock:
    now: float = 100.0

    def __call__(self) -> float:
        self.now += 0.002
        return self.now


def _request() -> PackageAcquisitionRequestV1:
    return PackageAcquisitionRequestV1(
        operation_id="operation-wheel-1",
        attempt_epoch=1,
        node_id="root",
        canonical_source_identity=(
            "https://packages.example.test/acme_plugin-1.0-py3-none-any.whl"
        ),
        request_fingerprint="a" * 64,
        requested_locator_digest="b" * 64,
        policy_revision="source-policy:1",
    )


def _candidate(tmp_path: Path, payload: bytes):
    request = _request()
    envelope = AuthenticatedSourceEnvelopeV1(
        operation_id=request.operation_id,
        node_id=request.node_id,
        canonical_source_identity=request.canonical_source_identity,
        origin_kind="https",
        authentication_decision="authorized",
        authority_id="source-authority:registry",
        requested_locator_digest=request.requested_locator_digest,
        expected_artifact_digest=sha256(payload).hexdigest(),
        redirect_policy_revision="redirect-policy:1",
        policy_revision=request.policy_revision,
        capture_epoch=1,
    )
    stream = _Stream(envelope=envelope, payload=payload)
    store = PackageQuarantineStore(tmp_path / "quarantine")
    owner = PackageAcquisitionOwner(
        source_authority=_Authority(stream),
        quarantine_store=store,
    )
    candidate = owner.acquire(
        request,
        budgets=PackageAcquisitionBudgetV1(
            max_transport_bytes=128 * 1024,
            max_requests=1,
            max_redirects=0,
            max_wall_time_ms=1000,
        ),
    )
    return candidate, store


def _record_digest(payload: bytes, algorithm: str = "sha256") -> str:
    digest = sha256(payload).digest()
    if algorithm != "sha256":
        return f"{algorithm}=unsupported"
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _wheel_bytes(
    *,
    extra_files: dict[str, bytes] | None = None,
    record_rows: list[tuple[str, str, str]] | None = None,
    wheel_metadata: bytes | None = None,
    package_metadata: bytes | None = None,
    symlink_name: str | None = None,
) -> bytes:
    files = {
        "acme_plugin/__init__.py": b"VALUE = 1\n",
        f"{DIST_INFO}/WHEEL": wheel_metadata
        or (
            b"Wheel-Version: 1.0\n"
            b"Generator: plc9b-test\n"
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
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(record_rows)
    files[f"{DIST_INFO}/RECORD"] = output.getvalue().encode()

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
        for name, payload in files.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = stat.S_IFREG << 16 | 0o644 << 16
            if name == symlink_name:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            wheel.writestr(info, payload)
    return archive.getvalue()


def _verify(tmp_path: Path, payload: bytes, **overrides: object):
    candidate, store = _candidate(tmp_path, payload)
    arguments: dict[str, object] = {
        "wheel_filename": WHEEL_FILENAME,
        "supported_tags": frozenset({"py3-none-any"}),
        "budgets": PackageInspectionBudgetV1(
            max_entries=32,
            max_total_expanded_bytes=128 * 1024,
            max_entry_expanded_bytes=64 * 1024,
            max_path_length=240,
            max_path_components=16,
            max_metadata_bytes=32 * 1024,
            max_wall_time_ms=1000,
        ),
    }
    arguments.update(overrides)
    return PackageWheelVerifier().verify(candidate, **arguments), store


def test_valid_wheel_is_fully_verified_before_controlled_extraction(
    tmp_path: Path,
) -> None:
    payload = _wheel_bytes()

    verified, store = _verify(tmp_path, payload)

    assert isinstance(verified.evidence, VerifiedWheelArtifactV1)
    assert verified.evidence.distribution == "acme-plugin"
    assert verified.evidence.version == "1.0"
    assert verified.evidence.wheel_filename == WHEEL_FILENAME
    assert verified.evidence.compatible_tags == ("py3-none-any",)
    assert verified.evidence.artifact_digest == sha256(payload).hexdigest()
    assert verified.evidence.artifact_size == len(payload)
    assert verified.evidence.record_verified is True
    assert verified.evidence.entry_count == 4
    assert verified.requires_dist == ()
    assert len(verified.evidence.extraction_tree_digest) == 64
    assert verified.transfer_manifest.extraction_tree_digest == (
        verified.evidence.extraction_tree_digest
    )
    assert verified.transfer_manifest.wheel_evidence_fingerprint == (
        verified.evidence.fingerprint
    )
    assert tuple(
        entry.logical_path for entry in verified.transfer_manifest.entries
    ) == (
        "acme_plugin/__init__.py",
        "acme_plugin-1.0.dist-info/METADATA",
        "acme_plugin-1.0.dist-info/RECORD",
        "acme_plugin-1.0.dist-info/WHEEL",
    )
    assert "path" not in str(verified.evidence.to_dict()).lower()
    assert (
        VerifiedWheelArtifactV1.from_dict(verified.evidence.to_dict())
        == verified.evidence
    )
    assert len(store.attempt_names()) == 1
    verified.cleanup()
    assert store.attempt_names() == ()


def test_verified_candidate_captures_requires_dist_without_changing_v1_evidence(
    tmp_path: Path,
) -> None:
    payload = _wheel_bytes(
        package_metadata=(
            b"Metadata-Version: 2.1\n"
            b"Name: acme-plugin\n"
            b"Version: 1.0\n"
            b"Requires-Python: >=3.11\n"
            b"Provides-Extra: Fast\n"
            b"Requires-Dist: zeta>=2; python_version >= '3.11'\n"
            b"Requires-Dist: beta>=1;\n python_version < '4'\n"
            b"Requires-Dist: alpha[fast]==1\n\n"
        )
    )

    verified, _store = _verify(tmp_path, payload)

    assert verified.requires_dist == (
        "alpha[fast]==1",
        "beta>=1; python_version < '4'",
        "zeta>=2; python_version >= '3.11'",
    )
    assert verified.requires_python == ">=3.11"
    assert verified.provides_extra == ("fast",)
    assert "requiresDist" not in verified.evidence.to_dict()
    assert "requiresPython" not in verified.evidence.to_dict()
    assert "providesExtra" not in verified.evidence.to_dict()
    verified.cleanup()


def test_inspection_budget_wire_schema_is_exact_and_versioned() -> None:
    budgets = PackageInspectionBudgetV1()

    assert PackageInspectionBudgetV1.from_dict(budgets.to_dict()) == budgets
    invalid = budgets.to_dict()
    invalid["unexpected"] = 1
    with pytest.raises(ValueError, match="versioned schema"):
        PackageInspectionBudgetV1.from_dict(invalid)


def test_verified_tree_cleanup_rechecks_exact_owner_identity(tmp_path: Path) -> None:
    verified, store = _verify(tmp_path, _wheel_bytes())
    attempt = store.root / store.attempt_names()[0]
    tree = attempt / "tree"
    displaced = attempt / "tree-displaced"
    tree.rename(displaced)
    tree.mkdir(mode=0o700)

    with pytest.raises(OSError, match="identity changed"):
        verified.cleanup()

    tree.rmdir()
    displaced.rename(tree)
    verified.cleanup()
    assert store.attempt_names() == ()


def test_verified_tree_reader_opens_only_recorded_rooted_file_identities(
    tmp_path: Path,
) -> None:
    payload = _wheel_bytes()
    verified, store = _verify(tmp_path, payload)
    expected: dict[str, bytes]
    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        expected = {
            entry.logical_path: archive.read(entry.logical_path)
            for entry in verified.transfer_manifest.entries
        }

    for entry in verified.transfer_manifest.entries:
        with verified._open_verified_tree_file(entry) as source:
            assert source.read() == expected[entry.logical_path]

    first = verified.transfer_manifest.entries[0]
    tree = store.root / store.attempt_names()[0] / "tree"
    original = tree / first.logical_path
    if os.name == "posix":
        outside_alias = tmp_path / "source-hardlink-alias"
        os.link(original, outside_alias)
        with pytest.raises(OSError, match="identity changed"):
            verified._open_verified_tree_file(first)
        outside_alias.unlink()
    displaced = original.with_name(original.name + "-displaced")
    original.rename(displaced)
    original.write_bytes(expected[first.logical_path])
    with pytest.raises(OSError, match="identity changed"):
        verified._open_verified_tree_file(first)
    original.unlink()
    displaced.rename(original)
    verified.cleanup()
    assert store.attempt_names() == ()


@pytest.mark.parametrize(
    "name",
    [
        "/absolute.py",
        "../escape.py",
        "pkg/../escape.py",
        "C:/escape.py",
        "//server/share.py",
        "pkg/file:stream",
        "pkg/CON",
        "pkg/trailing. ",
        "pkg\\ambiguous.py",
        "pkg//empty.py",
    ],
)
def test_rejected_archive_paths_leave_no_quarantine_residue(
    tmp_path: Path,
    name: str,
) -> None:
    payload = _wheel_bytes(extra_files={name: b"hostile"})
    candidate, store = _candidate(tmp_path, payload)

    with pytest.raises(PackageWheelVerificationError) as rejected:
        PackageWheelVerifier().verify(
            candidate,
            wheel_filename=WHEEL_FILENAME,
            supported_tags=frozenset({"py3-none-any"}),
            budgets=PackageInspectionBudgetV1(),
        )

    assert rejected.value.code == "package_archive_path_rejected"
    assert store.attempt_names() == ()


def test_case_and_unicode_normalization_collisions_are_rejected(
    tmp_path: Path,
) -> None:
    payload = _wheel_bytes(
        extra_files={
            "pkg/Name.py": b"one",
            "pkg/name.py": b"two",
            "pkg/caf\N{LATIN SMALL LETTER E WITH ACUTE}.py": b"three",
            "pkg/cafe\N{COMBINING ACUTE ACCENT}.py": b"four",
        }
    )
    candidate, store = _candidate(tmp_path, payload)

    with pytest.raises(PackageWheelVerificationError) as rejected:
        PackageWheelVerifier().verify(
            candidate,
            wheel_filename=WHEEL_FILENAME,
            supported_tags=frozenset({"py3-none-any"}),
            budgets=PackageInspectionBudgetV1(),
        )

    assert rejected.value.code == "package_archive_name_collision"
    assert store.attempt_names() == ()


def test_archive_link_metadata_is_rejected_without_materialization(
    tmp_path: Path,
) -> None:
    payload = _wheel_bytes(
        extra_files={"pkg/link": b"../../outside"},
        symlink_name="pkg/link",
    )
    candidate, store = _candidate(tmp_path, payload)

    with pytest.raises(PackageWheelVerificationError) as rejected:
        PackageWheelVerifier().verify(
            candidate,
            wheel_filename=WHEEL_FILENAME,
            supported_tags=frozenset({"py3-none-any"}),
            budgets=PackageInspectionBudgetV1(),
        )

    assert rejected.value.code == "package_archive_entry_type_rejected"
    assert store.attempt_names() == ()


def test_trailing_payload_and_local_central_mismatch_are_rejected(
    tmp_path: Path,
) -> None:
    trailing = _wheel_bytes() + b"attacker-payload"
    candidate, store = _candidate(tmp_path / "trailing", trailing)
    with pytest.raises(PackageWheelVerificationError) as rejected:
        PackageWheelVerifier().verify(
            candidate,
            wheel_filename=WHEEL_FILENAME,
            supported_tags=frozenset({"py3-none-any"}),
            budgets=PackageInspectionBudgetV1(),
        )
    assert rejected.value.code == "package_archive_malformed"
    assert store.attempt_names() == ()

    mismatched = bytearray(_wheel_bytes())
    central = mismatched.index(b"PK\x01\x02")
    local_offset = struct.unpack_from("<L", mismatched, central + 42)[0]
    mismatched[local_offset + 8 : local_offset + 10] = struct.pack("<H", 0)
    candidate, store = _candidate(tmp_path / "mismatch", bytes(mismatched))
    with pytest.raises(PackageWheelVerificationError) as rejected:
        PackageWheelVerifier().verify(
            candidate,
            wheel_filename=WHEEL_FILENAME,
            supported_tags=frozenset({"py3-none-any"}),
            budgets=PackageInspectionBudgetV1(),
        )
    assert rejected.value.code == "package_archive_malformed"
    assert store.attempt_names() == ()


@pytest.mark.parametrize(
    ("filename", "tags"),
    [
        ("acme_plugin-1.0.tar.gz", frozenset({"py3-none-any"})),
        ("acme_plugin-1.0.zip", frozenset({"py3-none-any"})),
        (WHEEL_FILENAME, frozenset({"cp313-cp313-win_amd64"})),
    ],
)
def test_only_compatible_wheels_are_accepted(
    tmp_path: Path,
    filename: str,
    tags: frozenset[str],
) -> None:
    candidate, store = _candidate(tmp_path, _wheel_bytes())

    with pytest.raises(PackageWheelVerificationError) as rejected:
        PackageWheelVerifier().verify(
            candidate,
            wheel_filename=filename,
            supported_tags=tags,
            budgets=PackageInspectionBudgetV1(),
        )

    assert rejected.value.code == "package_artifact_type_rejected"
    assert store.attempt_names() == ()


def test_wheel_and_package_metadata_are_bound_to_filename(tmp_path: Path) -> None:
    payload = _wheel_bytes(
        package_metadata=(
            b"Metadata-Version: 2.1\nName: another-project\nVersion: 9\n\n"
        )
    )
    candidate, store = _candidate(tmp_path, payload)

    with pytest.raises(PackageWheelVerificationError) as rejected:
        PackageWheelVerifier().verify(
            candidate,
            wheel_filename=WHEEL_FILENAME,
            supported_tags=frozenset({"py3-none-any"}),
            budgets=PackageInspectionBudgetV1(),
        )

    assert rejected.value.code == "package_wheel_metadata_invalid"
    assert store.attempt_names() == ()


@pytest.mark.parametrize("defect", ["hash", "size", "missing", "unlisted", "weak"])
def test_complete_record_relation_is_verified(tmp_path: Path, defect: str) -> None:
    files = {
        "acme_plugin/__init__.py": b"VALUE = 1\n",
        f"{DIST_INFO}/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n"
        ),
        f"{DIST_INFO}/METADATA": (
            b"Metadata-Version: 2.1\nName: acme-plugin\nVersion: 1.0\n\n"
        ),
    }
    rows = [
        (name, _record_digest(value), str(len(value))) for name, value in files.items()
    ]
    rows.append((f"{DIST_INFO}/RECORD", "", ""))
    extras: dict[str, bytes] = {}
    if defect == "hash":
        rows[0] = (rows[0][0], "sha256=" + "A" * 43, rows[0][2])
    elif defect == "size":
        rows[0] = (rows[0][0], rows[0][1], "999")
    elif defect == "missing":
        rows.pop(0)
    elif defect == "unlisted":
        extras["acme_plugin/unlisted.py"] = b"unlisted"
    elif defect == "weak":
        rows[0] = (rows[0][0], "md5=deadbeef", rows[0][2])
    payload = _wheel_bytes(extra_files=extras, record_rows=rows)
    candidate, store = _candidate(tmp_path, payload)

    with pytest.raises(PackageWheelVerificationError) as rejected:
        PackageWheelVerifier().verify(
            candidate,
            wheel_filename=WHEEL_FILENAME,
            supported_tags=frozenset({"py3-none-any"}),
            budgets=PackageInspectionBudgetV1(),
        )

    assert rejected.value.code == "package_wheel_record_invalid"
    assert store.attempt_names() == ()


def test_entry_and_expansion_budgets_fail_before_extraction(tmp_path: Path) -> None:
    payload = _wheel_bytes(extra_files={"pkg/large.bin": b"x" * 200})
    candidate, store = _candidate(tmp_path, payload)

    with pytest.raises(PackageWheelVerificationError) as rejected:
        PackageWheelVerifier().verify(
            candidate,
            wheel_filename=WHEEL_FILENAME,
            supported_tags=frozenset({"py3-none-any"}),
            budgets=PackageInspectionBudgetV1(
                max_entries=4,
                max_total_expanded_bytes=128,
                max_entry_expanded_bytes=64,
            ),
        )

    assert rejected.value.code == "package_resource_limit_exceeded"
    assert store.attempt_names() == ()


def test_component_and_wall_clock_budgets_are_hard_limits(tmp_path: Path) -> None:
    long_name = "x" * 40 + ".py"
    payload = _wheel_bytes(extra_files={f"pkg/{long_name}": b"bounded"})
    candidate, store = _candidate(tmp_path / "component", payload)
    with pytest.raises(PackageWheelVerificationError) as rejected:
        PackageWheelVerifier().verify(
            candidate,
            wheel_filename=WHEEL_FILENAME,
            supported_tags=frozenset({"py3-none-any"}),
            budgets=PackageInspectionBudgetV1(max_path_component_length=32),
        )
    assert rejected.value.code == "package_resource_limit_exceeded"
    assert store.attempt_names() == ()

    candidate, store = _candidate(tmp_path / "clock", _wheel_bytes())
    with pytest.raises(PackageWheelVerificationError) as rejected:
        PackageWheelVerifier(clock=_AdvancingClock()).verify(
            candidate,
            wheel_filename=WHEEL_FILENAME,
            supported_tags=frozenset({"py3-none-any"}),
            budgets=PackageInspectionBudgetV1(max_wall_time_ms=1),
        )
    assert rejected.value.code == "package_resource_limit_exceeded"
    assert store.attempt_names() == ()
