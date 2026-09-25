from __future__ import annotations

import os
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.coding.package_legacy_binding_catalog import (
    CodingLegacyBindingError,
    CodingLegacyLocalBindingCatalog,
)
from loushang.coding.package_legacy_local_wheel import (
    CodingLegacyLocalWheelCandidateV1,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelPolicy,
)


def _candidate() -> CodingLegacyLocalWheelCandidateV1:
    token = "a" * 24
    body = b"Product-verified Wheel bytes"
    return CodingLegacyLocalWheelCandidateV1(
        plugin_id="review-pack",
        original_source_identity="local:/approved/review-pack",
        source_content_digest="b" * 64,
        manifest_digest="c" * 64,
        requested_package=f"loushang-legacy-{token}==1",
        plugin_manifest_path=f"loushang_legacy_{token}/plugin.json",
        filename=f"loushang_legacy_{token}-1-py3-none-any.whl",
        artifact_digest=sha256(body).hexdigest(),
        wheel_bytes=body,
    )


def _catalog(tmp_path: Path) -> CodingLegacyLocalBindingCatalog:
    state = tmp_path / "product-state"
    state.mkdir(mode=0o700, exist_ok=True)
    sources = tmp_path / "product-sources"
    sources.mkdir(mode=0o700, exist_ok=True)
    return CodingLegacyLocalBindingCatalog(
        state / "legacy-local-bindings.jsonl",
        source_root=sources,
        store_id="coding-store",
        namespace_id="d" * 64,
        scope_id="workspace:legacy",
        policy_revision="coding-product-package-policy:1",
    )


def _base_policy(
    catalog: CodingLegacyLocalBindingCatalog,
) -> PackageProductLocalWheelPolicy:
    return PackageProductLocalWheelPolicy(
        product_id="coding",
        project_scope_id=catalog.scope_id,
        source_root=catalog.source_root,
        bindings=(
            PackageProductLocalWheelBindingV1(
                source_identity=str(
                    catalog.source_root / "coding_base-1-py3-none-any.whl"
                ),
                requested_package="coding-base==1",
                plugin_id="coding.base",
                artifact_digest="f" * 64,
                plugin_manifest_path="coding_base/plugin.json",
            ),
        ),
        policy_revision=catalog.policy_revision,
        quota_profile_revision="quota:1",
        resolution_environment_fingerprint="e" * 64,
        authority_id="coding-product-local-source",
    )


def _append(
    catalog: CodingLegacyLocalBindingCatalog,
    candidate: CodingLegacyLocalWheelCandidateV1,
    *,
    approval_id: str = "approval:1",
):
    return catalog.append(
        candidate,
        legacy_source_identity="local:/approved/review-pack",
        legacy_binding_digest="1" * 64,
        dependency_lock_digest="2" * 64,
        approval_id=approval_id,
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_catalog_replays_exact_binding_into_product_policy(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    candidate = _candidate()
    artifact = catalog.source_root / candidate.filename
    artifact.write_bytes(candidate.wheel_bytes)
    artifact.chmod(0o600)
    base = _base_policy(catalog)

    recorded = _append(catalog, candidate)
    assert _append(catalog, candidate) == recorded
    assert recorded == type(recorded).from_dict(recorded.to_dict())
    reopened = _catalog(tmp_path)
    assert reopened.records() == (recorded,)
    extended = reopened.extend_policy(base)
    assert extended.authority_revision != base.authority_revision
    assert {item.plugin_id for item in extended.bindings} == {
        "coding.base",
        "review-pack",
    }
    assert extended.bindings[-1].source_trust_class == "legacy-local-reacquired"


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_catalog_refuses_conflict_changed_wheel_and_namespace(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    candidate = _candidate()
    artifact = catalog.source_root / candidate.filename
    with pytest.raises(CodingLegacyBindingError, match="unavailable"):
        _append(catalog, candidate)
    assert not catalog.path.exists()
    artifact.write_bytes(candidate.wheel_bytes)
    artifact.chmod(0o600)
    _append(catalog, candidate)

    with pytest.raises(ValueError, match="original Source identity changed"):
        catalog.append(
            candidate,
            legacy_source_identity="local:/other/source",
            legacy_binding_digest="1" * 64,
            dependency_lock_digest="2" * 64,
            approval_id="approval:1",
        )

    with pytest.raises(CodingLegacyBindingError, match="conflicts"):
        _append(catalog, candidate, approval_id="approval:2")
    wrong_namespace = CodingLegacyLocalBindingCatalog(
        catalog.path,
        source_root=catalog.source_root,
        store_id=catalog.store_id,
        namespace_id="e" * 64,
        scope_id=catalog.scope_id,
        policy_revision=catalog.policy_revision,
    )
    with pytest.raises(CodingLegacyBindingError, match="corrupt"):
        wrong_namespace.records()

    artifact.write_bytes(b"changed")
    with pytest.raises(CodingLegacyBindingError, match="changed on disk"):
        catalog.extend_policy(_base_policy(catalog))


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_catalog_refuses_duplicate_wire_keys(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    candidate = _candidate()
    artifact = catalog.source_root / candidate.filename
    artifact.write_bytes(candidate.wheel_bytes)
    artifact.chmod(0o600)
    _append(catalog, candidate)
    original = catalog.path.read_text()
    needle = '"recordVersion": 1'
    assert needle in original
    catalog.path.write_text(original.replace(needle, f"{needle}, {needle}", 1))

    with pytest.raises(CodingLegacyBindingError, match="corrupt"):
        catalog.records()


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_catalog_refuses_builtin_plugin_replacement(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    candidate = _candidate()
    artifact = catalog.source_root / candidate.filename
    artifact.write_bytes(candidate.wheel_bytes)
    artifact.chmod(0o600)

    with pytest.raises(ValueError, match="cannot replace a builtin"):
        _append(catalog, replace(candidate, plugin_id="coding.base"))
    assert catalog.records() == ()
