from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.coding.package_legacy_local_wheel import (
    reacquire_coding_legacy_local_plugin_wheel,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
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
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelPolicy,
)
from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.revisions import PluginRevisionStore


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "original-source"
    (root / "resources" / "prompts").mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"name": "review-pack", "version": "1", "packageRoot": "resources"})
    )
    (root / "resources" / "prompts" / "review.md").write_text("review v1")
    return root


def _evidence(
    tmp_path: Path, source: Path
) -> tuple[str, str, PluginDependencyClosureLock]:
    published = PluginRevisionStore(tmp_path / "old-revisions").publish(
        PluginManifestParser().parse(source)
    )
    published.revision_handle.close()
    assert published.manifest_digest is not None
    return (
        published.content_digest,
        published.manifest_digest,
        PluginDependencyClosureLock(
            package_content_digest=published.content_digest,
            python_distributions=(),
        ),
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX Source reacquisition")
def test_reacquired_local_tree_becomes_product_verified_wheel(tmp_path: Path) -> None:
    source = _source(tmp_path)
    digest, manifest_digest, dependency_lock = _evidence(tmp_path, source)
    old_package = tmp_path / "old-package"
    old_package.mkdir(mode=0o700)
    staging = tmp_path / "private-staging"
    staging.mkdir(mode=0o700)
    kwargs = dict(
        legacy_package_root=old_package,
        staging_parent=staging,
        plugin_id="review-pack",
        expected_content_digest=digest,
        expected_manifest_digest=manifest_digest,
        expected_dependency_lock=dependency_lock,
    )

    candidate = reacquire_coding_legacy_local_plugin_wheel(source, **kwargs)
    assert candidate == reacquire_coding_legacy_local_plugin_wheel(source, **kwargs)
    assert candidate.source_content_digest == digest
    assert candidate.manifest_digest == manifest_digest
    assert candidate.artifact_digest == sha256(candidate.wheel_bytes).hexdigest()
    assert list(staging.iterdir()) == []

    product_sources = tmp_path / "product-sources"
    product_sources.mkdir(mode=0o700)
    wheel_path = product_sources / candidate.filename
    wheel_path.write_bytes(candidate.wheel_bytes)
    wheel_path.chmod(0o600)
    policy = PackageProductLocalWheelPolicy(
        product_id="coding",
        project_scope_id="workspace:legacy",
        source_root=product_sources,
        bindings=(
            PackageProductLocalWheelBindingV1(
                source_identity=str(wheel_path),
                requested_package=candidate.requested_package,
                plugin_id=candidate.plugin_id,
                artifact_digest=candidate.artifact_digest,
                plugin_manifest_path=candidate.plugin_manifest_path,
            ),
        ),
        policy_revision="coding-legacy-local:1",
        quota_profile_revision="quota:1",
        resolution_environment_fingerprint="a" * 64,
        authority_id="coding-legacy-local-source",
    )
    source_identity = str(wheel_path)
    acquired = PackageAcquisitionOwner(
        source_authority=policy.source_authority(),
        quarantine_store=PackageQuarantineStore(tmp_path / "quarantine"),
    ).acquire(
        PackageAcquisitionRequestV1(
            operation_id="legacy-local-reacquisition",
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
        acquired,
        wheel_filename=candidate.filename,
        supported_tags=frozenset({"py3-none-any"}),
        budgets=PackageInspectionBudgetV1(),
    )
    try:
        assert verified.evidence.artifact_digest == candidate.artifact_digest
        assert verified.evidence.record_verified
    finally:
        verified.cleanup()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Source reacquisition")
def test_reacquisition_matches_real_pre_b_local_binding(tmp_path: Path) -> None:
    source = _source(tmp_path)
    old_package = tmp_path / "old-package"
    materializer = PackageMaterializer(install_root=old_package / "installed")
    published = materializer.publish_plugin_packages(
        (PluginManifestParser().parse(source),)
    )
    try:
        [binding] = materializer.bind_plugin_packages(published)
    finally:
        published[0].revision_handle.close()
    assert binding.content_digest is not None
    assert binding.manifest_digest is not None
    assert binding.dependency_lock is not None
    staging = tmp_path / "private-staging"
    staging.mkdir(mode=0o700)

    candidate = reacquire_coding_legacy_local_plugin_wheel(
        source,
        legacy_package_root=old_package,
        staging_parent=staging,
        plugin_id=binding.plugin_id,
        expected_content_digest=binding.content_digest,
        expected_manifest_digest=binding.manifest_digest,
        expected_dependency_lock=binding.dependency_lock,
    )

    assert candidate.plugin_id == binding.plugin_id
    assert candidate.source_content_digest == binding.content_digest
    assert candidate.manifest_digest == binding.manifest_digest
    assert list(staging.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX Source reacquisition")
def test_reacquisition_refuses_changed_source_and_old_store_as_source(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    digest, manifest_digest, dependency_lock = _evidence(tmp_path, source)
    old_package = tmp_path / "old-package"
    old_package.mkdir(mode=0o700)
    staging = tmp_path / "private-staging"
    staging.mkdir(mode=0o700)
    kwargs = dict(
        legacy_package_root=old_package,
        staging_parent=staging,
        plugin_id="review-pack",
        expected_content_digest=digest,
        expected_manifest_digest=manifest_digest,
        expected_dependency_lock=dependency_lock,
    )

    (source / "resources" / "prompts" / "review.md").write_text("changed")
    with pytest.raises(ValueError, match="revision changed"):
        reacquire_coding_legacy_local_plugin_wheel(source, **kwargs)
    assert list(staging.iterdir()) == []

    with pytest.raises(ValueError, match="Store bytes"):
        reacquire_coding_legacy_local_plugin_wheel(old_package, **kwargs)
    assert list(staging.iterdir()) == []

    with pytest.raises(ValueError, match="overlaps protected inputs"):
        reacquire_coding_legacy_local_plugin_wheel(
            source, **{**kwargs, "staging_parent": old_package}
        )
    assert list(old_package.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX Source reacquisition")
def test_reacquisition_refuses_dependency_and_unsafe_stage(tmp_path: Path) -> None:
    source = _source(tmp_path)
    digest, manifest_digest, _dependency_lock = _evidence(tmp_path, source)
    old_package = tmp_path / "old-package"
    old_package.mkdir(mode=0o700)
    staging = tmp_path / "private-staging"
    staging.mkdir(mode=0o700)
    lock_with_dependency = PluginDependencyClosureLock.from_dict(
        {
            "format": "loushang.plugin-dependency-lock/v1",
            "packageContentDigest": digest,
            "pythonDistributions": [{"name": "requests", "version": "2.0"}],
        }
    )

    with pytest.raises(ValueError, match="dependency closure"):
        reacquire_coding_legacy_local_plugin_wheel(
            source,
            legacy_package_root=old_package,
            staging_parent=staging,
            plugin_id="review-pack",
            expected_content_digest=digest,
            expected_manifest_digest=manifest_digest,
            expected_dependency_lock=lock_with_dependency,
        )
    staging.chmod(0o770)
    with pytest.raises(ValueError, match="not private"):
        reacquire_coding_legacy_local_plugin_wheel(
            source,
            legacy_package_root=old_package,
            staging_parent=staging,
            plugin_id="review-pack",
            expected_content_digest=digest,
            expected_manifest_digest=manifest_digest,
            expected_dependency_lock=PluginDependencyClosureLock(digest, ()),
        )
    assert list(staging.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX Source reacquisition")
@pytest.mark.parametrize(
    ("variant", "message"),
    (
        ("empty_directory", "empty directory"),
        ("wheel_metadata", "Wheel metadata"),
        ("oversized_file", "file budget"),
    ),
)
def test_reacquisition_refuses_unrepresentable_or_unbounded_tree(
    tmp_path: Path, variant: str, message: str
) -> None:
    source = _source(tmp_path)
    if variant == "empty_directory":
        (source / "empty").mkdir()
    elif variant == "wheel_metadata":
        metadata = source / "other-1.dist-info"
        metadata.mkdir()
        (metadata / "METADATA").write_text("unrelated")
    else:
        (source / "huge.bin").write_bytes(b"x" * (256 * 1024 + 1))
    digest, manifest_digest, dependency_lock = _evidence(tmp_path, source)
    old_package = tmp_path / "old-package"
    old_package.mkdir(mode=0o700)
    staging = tmp_path / "private-staging"
    staging.mkdir(mode=0o700)

    with pytest.raises(ValueError, match=message):
        reacquire_coding_legacy_local_plugin_wheel(
            source,
            legacy_package_root=old_package,
            staging_parent=staging,
            plugin_id="review-pack",
            expected_content_digest=digest,
            expected_manifest_digest=manifest_digest,
            expected_dependency_lock=dependency_lock,
        )
    assert list(staging.iterdir()) == []
