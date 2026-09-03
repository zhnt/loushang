from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackageDependencyMaterializationRootPort,
    PackagePluginRootMaterializationRootPort,
    PackageVerifiedTreeEntryV1,
    PackageVerifiedTreeFileSinkPort,
    PackageVerifiedTreeManifestV1,
    PackageVerifiedTreeSinkPort,
    PackageVerifiedTreeTransferPort,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    VerifiedWheelArtifactV1,
)


def _entry(path: str, payload: bytes) -> PackageVerifiedTreeEntryV1:
    return PackageVerifiedTreeEntryV1(
        logical_path=path,
        content_digest=sha256(payload).hexdigest(),
        byte_count=len(payload),
    )


def _tree_digest(entries: tuple[PackageVerifiedTreeEntryV1, ...]) -> str:
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


def _evidence(
    entries: tuple[PackageVerifiedTreeEntryV1, ...],
) -> VerifiedWheelArtifactV1:
    return VerifiedWheelArtifactV1(
        operation_id="operation-transfer-1",
        attempt_epoch=2,
        node_id="dependency-a",
        distribution="acme-dependency",
        version="1.2.3",
        wheel_filename="acme_dependency-1.2.3-py3-none-any.whl",
        compatible_tags=("py3-none-any",),
        artifact_digest="a" * 64,
        artifact_size=123,
        wheel_metadata_digest="b" * 64,
        package_metadata_digest="c" * 64,
        record_digest="d" * 64,
        record_verified=True,
        entry_count=len(entries),
        expanded_byte_count=sum(entry.byte_count for entry in entries),
        extraction_tree_digest=_tree_digest(entries),
    )


def test_manifest_binds_canonical_files_to_verified_wheel_evidence() -> None:
    entries = (
        _entry("acme_dependency/__init__.py", b"VALUE = 1\n"),
        _entry("acme_dependency-1.2.3.dist-info/METADATA", b"Name: acme\n"),
    )
    evidence = _evidence(entries)

    manifest = PackageVerifiedTreeManifestV1.create(evidence, entries=entries)

    assert manifest.operation_id == evidence.operation_id
    assert manifest.attempt_epoch == evidence.attempt_epoch
    assert manifest.node_id == evidence.node_id
    assert manifest.distribution == evidence.distribution
    assert manifest.version == evidence.version
    assert manifest.wheel_evidence_fingerprint == evidence.fingerprint
    assert manifest.artifact_digest == evidence.artifact_digest
    assert manifest.extraction_tree_digest == evidence.extraction_tree_digest
    assert manifest.total_byte_count == evidence.expanded_byte_count
    assert manifest.entries == entries
    assert _tree_digest(manifest.entries) == evidence.extraction_tree_digest
    assert PackageVerifiedTreeManifestV1.from_dict(manifest.to_dict()) == manifest


@pytest.mark.parametrize(
    "logical_path",
    (
        "/absolute.py",
        "../escape.py",
        "pkg/../escape.py",
        r"pkg\escape.py",
        "pkg//ambiguous.py",
        "pkg/trailing. ",
        "pkg/con.py",
        "pkg/not-normalized-e\u0301.py",
    ),
)
def test_entry_rejects_nonportable_or_ambiguous_logical_paths(
    logical_path: str,
) -> None:
    with pytest.raises(ValueError):
        _entry(logical_path, b"payload")


def test_manifest_rejects_order_tree_or_evidence_drift() -> None:
    entries = (
        _entry("acme/a.py", b"a"),
        _entry("acme/b.py", b"b"),
    )
    evidence = _evidence(entries)

    with pytest.raises(ValueError, match="canonical"):
        PackageVerifiedTreeManifestV1.create(evidence, entries=tuple(reversed(entries)))

    with pytest.raises(TypeError, match="typed entry tuple"):
        PackageVerifiedTreeManifestV1.create(
            evidence,
            entries=(object(),),  # type: ignore[arg-type]
        )

    changed = replace(evidence, extraction_tree_digest="f" * 64)
    with pytest.raises(ValueError, match="tree digest"):
        PackageVerifiedTreeManifestV1.create(changed, entries=entries)

    manifest = PackageVerifiedTreeManifestV1.create(evidence, entries=entries)
    wire = manifest.to_dict()
    wire["manifestId"] = "0" * 64
    with pytest.raises(ValueError, match="manifest id"):
        PackageVerifiedTreeManifestV1.from_dict(wire)


def test_manifest_wire_is_strict_and_contains_no_physical_authority() -> None:
    entries = (_entry("acme/__init__.py", b"payload"),)
    manifest = PackageVerifiedTreeManifestV1.create(
        _evidence(entries),
        entries=entries,
    )
    wire = manifest.to_dict()

    assert set(wire) == {
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
    }
    assert set(wire["entries"][0]) == {
        "byteCount",
        "contentDigest",
        "entryVersion",
        "logicalPath",
    }
    serialized = str(wire).lower()
    for forbidden in (
        "/tmp/",
        "physicalpath",
        "rootpath",
        "quarantinepath",
        "handle",
        "credential",
        "secret",
    ):
        assert forbidden not in serialized

    wire["physicalPath"] = "/tmp/escape"
    with pytest.raises(ValueError, match="fields"):
        PackageVerifiedTreeManifestV1.from_dict(wire)


def test_transfer_contracts_keep_source_store_and_root_roles_separate() -> None:
    assert _public_methods(PackageVerifiedTreeFileSinkPort) == {
        "abort",
        "finish",
        "write",
    }
    assert _public_methods(PackageVerifiedTreeSinkPort) == {
        "abort",
        "finish",
        "open_file",
    }
    assert _public_methods(PackageVerifiedTreeTransferPort) == {"transfer"}
    assert _public_methods(PackageDependencyMaterializationRootPort) == {
        "open_dependency_sink"
    }
    assert _public_methods(PackagePluginRootMaterializationRootPort) == {
        "open_root_sink"
    }


def _public_methods(protocol: type[object]) -> set[str]:
    return {
        name
        for name, value in protocol.__dict__.items()
        if not name.startswith("_") and callable(value)
    }
