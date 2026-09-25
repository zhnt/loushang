from __future__ import annotations

import os
import stat
import zipfile
from hashlib import sha256

import pytest

from loushang.coding.package_builtin_wheel import (
    CODING_BASE_PRODUCT_WHEEL_FILENAME,
    build_coding_base_product_wheel,
    build_coding_capability_product_wheel,
    coding_builtin_product_local_wheel_policy,
    prepare_posix_coding_base_product_wheel,
    prepare_posix_coding_capability_product_wheels,
)
from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    PackageAcquisitionBudgetV1,
    PackageAcquisitionOwner,
    PackageAcquisitionRequestV1,
    PackageQuarantineStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    PackageWheelVerifier,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source owner")
def test_coding_base_product_wheel_is_private_repeatable_and_pinned(tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir(mode=0o700)

    prepared = prepare_posix_coding_base_product_wheel(source_root)

    assert prepared.path == source_root / CODING_BASE_PRODUCT_WHEEL_FILENAME
    assert prepared.path.read_bytes() == build_coding_base_product_wheel()
    assert prepared.artifact_digest == sha256(prepared.path.read_bytes()).hexdigest()
    assert stat.S_IMODE(prepared.path.stat().st_mode) == 0o600
    assert prepare_posix_coding_base_product_wheel(source_root) == prepared


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source owner")
def test_coding_base_product_wheel_refuses_changed_or_linked_existing_artifact(tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir(mode=0o700)
    prepared = prepare_posix_coding_base_product_wheel(source_root)
    prepared.path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed on disk"):
        prepare_posix_coding_base_product_wheel(source_root)
    assert prepared.path.read_bytes() == b"changed"

    target = tmp_path / "target"
    target.write_bytes(b"outside")
    prepared.path.unlink()
    prepared.path.symlink_to(target)
    with pytest.raises(OSError):
        prepare_posix_coding_base_product_wheel(source_root)
    assert target.read_bytes() == b"outside"


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source owner")
def test_coding_base_product_wheel_refuses_group_writable_source_root(tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir(mode=0o700)
    source_root.chmod(0o770)

    with pytest.raises(ValueError, match="not private"):
        prepare_posix_coding_base_product_wheel(source_root)
    assert not (source_root / CODING_BASE_PRODUCT_WHEEL_FILENAME).exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source owner")
def test_coding_capability_product_wheels_bind_exact_store_inputs(tmp_path):
    source_root = tmp_path / "sources"
    source_root.mkdir(mode=0o700)
    base = prepare_posix_coding_base_product_wheel(source_root)

    capabilities = prepare_posix_coding_capability_product_wheels(source_root)

    assert tuple(item.plugin_id for item in capabilities) == (
        "coding.arch.default",
        "coding.lsp.default",
    )
    assert capabilities == prepare_posix_coding_capability_product_wheels(source_root)
    policy = coding_builtin_product_local_wheel_policy(
        base,
        capabilities,
        project_scope_id="workspace:manifest",
        resolution_environment_fingerprint="a" * 64,
        policy_revision="coding-builtin:1",
        quota_profile_revision="quota:1",
        authority_id="coding-builtin-source",
    )
    assert tuple(item.plugin_id for item in policy.bindings) == (
        "coding.arch.default",
        "coding.base",
        "coding.lsp.default",
    )
    assert all(
        item.source_trust_class == "host-equivalent-local"
        and item.plugin_manifest_path is not None
        for item in policy.bindings
    )
    for artifact in capabilities:
        assert artifact.path.read_bytes() == build_coding_capability_product_wheel(
            artifact.plugin_id
        )
        assert artifact.artifact_digest == sha256(artifact.path.read_bytes()).hexdigest()
        assert stat.S_IMODE(artifact.path.stat().st_mode) == 0o600
        with zipfile.ZipFile(artifact.path) as wheel:
            files = {
                name: wheel.read(name)
                for name in wheel.namelist()
                if ".dist-info/" not in name
            }
        package_root = artifact.path.name.split("-1-")[0]
        assert f"{package_root}/definition.py" in files
        manifest = PluginManifestParser().parse_file_set(
            files,
            manifest_logical_path=f"{package_root}/plugin.json",
        )
        assert manifest.name == artifact.plugin_id
        assert any(
            item.contribution_execution_model == "in_process"
            for item in manifest.contribution_index.items
        )
        source_identity = str(artifact.path)
        candidate = PackageAcquisitionOwner(
            source_authority=policy.source_authority(),
            quarantine_store=PackageQuarantineStore(
                tmp_path / f"quarantine-{artifact.plugin_id}"
            ),
        ).acquire(
            PackageAcquisitionRequestV1(
                operation_id=f"operation:{artifact.plugin_id}",
                attempt_epoch=1,
                node_id="root",
                canonical_source_identity=source_identity,
                request_fingerprint="b" * 64,
                requested_locator_digest=sha256(source_identity.encode()).hexdigest(),
                policy_revision=policy.policy_revision,
            ),
            budgets=PackageAcquisitionBudgetV1(
                max_transport_bytes=2 * 1024 * 1024,
                max_requests=1,
                max_redirects=0,
                max_wall_time_ms=30_000,
            ),
        )
        verified = PackageWheelVerifier().verify(
            candidate,
            wheel_filename=artifact.path.name,
            supported_tags=frozenset({"py3-none-any"}),
            budgets=PackageInspectionBudgetV1(),
        )
        assert verified.evidence.artifact_digest == artifact.artifact_digest
        assert verified.evidence.record_verified
        verified.cleanup()
    capabilities[0].path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed on disk"):
        prepare_posix_coding_capability_product_wheels(source_root)
    assert capabilities[0].path.read_bytes() == b"changed"
