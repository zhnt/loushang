from __future__ import annotations

import os
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Literal

import pytest

from loushang.coding.package_legacy_binding_catalog import (
    CodingLegacyBindingError,
    CodingLegacyLocalBindingCatalog,
    CodingLegacyLocalBindingV1,
)
from loushang.coding.package_legacy_local_acceptance import (
    CodingLegacyLocalAcceptanceV1,
)
from loushang.coding.package_legacy_local_wheel import (
    CodingLegacyLocalWheelCandidateV1,
)
from loushang.coding.package_legacy_review import CodingLegacyLocalAdoptionReviewV1
from loushang.harness.journal import JournalCodecError, journal_file_lock
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


def _accepted_review(
    resource_kind: Literal["skill", "prompt"] = "skill",
) -> CodingLegacyLocalAcceptanceV1:
    candidate = _candidate()
    return CodingLegacyLocalAcceptanceV1.create(
        CodingLegacyLocalAdoptionReviewV1(
            store_id="coding-store",
            namespace_id="d" * 64,
            scope_id="workspace:legacy",
            first_fence_id="3" * 64,
            snapshot_receipt_id="4" * 64,
            legacy_root_identity="5" * 64,
            legacy_state_evidence_id="6" * 64,
            legacy_state_digest="7" * 64,
            legacy_entry_count=1,
            legacy_byte_count=1,
            plugin_id=candidate.plugin_id,
            desired_state="installed_enabled",
            legacy_source_identity=candidate.original_source_identity,
            legacy_binding_digest="1" * 64,
            legacy_lockfile_digest="8" * 64,
            legacy_desired_journal_digest="9" * 64,
            source_content_digest=candidate.source_content_digest,
            manifest_digest=candidate.manifest_digest,
            dependency_lock_digest="2" * 64,
            wheel_filename=candidate.filename,
            wheel_artifact_digest=candidate.artifact_digest,
            policy_revision="coding-product-package-policy:1",
        ),
        resource_kind=resource_kind,
    )


def _catalog(
    tmp_path: Path,
    *,
    with_acceptance: bool = True,
    resource_kind: Literal["skill", "prompt"] = "skill",
) -> CodingLegacyLocalBindingCatalog:
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
        acceptance_reader=(
            lambda plugin_id: (
                _accepted_review(resource_kind) if plugin_id == "review-pack" else None
            )
        )
        if with_acceptance
        else None,
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
    approval_id: str | None = None,
):
    return catalog.append(
        candidate,
        legacy_source_identity="local:/approved/review-pack",
        legacy_binding_digest="1" * 64,
        dependency_lock_digest="2" * 64,
        approval_id=approval_id or _accepted_review().acceptance_id,
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
    assert reopened.read_extend_policy(base) == extended
    assert extended.authority_revision != base.authority_revision
    assert {item.plugin_id for item in extended.bindings} == {
        "coding.base",
        "review-pack",
    }
    assert extended.bindings[-1].source_trust_class == "legacy-local-reacquired"
    assert "resourceKind" not in recorded.to_dict()
    with pytest.raises(CodingLegacyBindingError, match="no acceptance owner"):
        _catalog(tmp_path, with_acceptance=False).extend_policy(base)


@pytest.mark.skipif(os.name != "posix", reason="POSIX Product Source")
def test_prompt_binding_is_typed_and_remains_closed_to_product(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path, resource_kind="prompt")
    candidate = _candidate()
    artifact = catalog.source_root / candidate.filename
    artifact.write_bytes(candidate.wheel_bytes)
    artifact.chmod(0o600)

    with pytest.raises(CodingLegacyBindingError, match="differs from accepted review"):
        _append(catalog, candidate)
    assert catalog.records() == ()

    recorded = catalog.append(
        candidate,
        legacy_source_identity=candidate.original_source_identity,
        legacy_binding_digest="1" * 64,
        dependency_lock_digest="2" * 64,
        approval_id=_accepted_review("prompt").acceptance_id,
        resource_kind="prompt",
    )
    assert recorded.record_version == 2
    assert recorded.to_dict()["resourceKind"] == "prompt"
    assert CodingLegacyLocalBindingV1.from_dict(recorded.to_dict()) == recorded
    assert _catalog(tmp_path, resource_kind="prompt").read_records() == (recorded,)
    binding = catalog.read_extend_policy(_base_policy(catalog)).bindings[-1]
    assert binding.source_trust_class == "legacy-local-reacquired-prompt"

    with pytest.raises(CodingLegacyBindingError, match="differs from accepted review"):
        _catalog(tmp_path).read_extend_policy(_base_policy(catalog))
    with pytest.raises(CodingLegacyBindingError, match="conflicts"):
        _append(catalog, candidate)
    wrong_wire = dict(recorded.to_dict())
    wrong_wire.pop("resourceKind")
    with pytest.raises(JournalCodecError):
        CodingLegacyLocalBindingV1.from_dict(wrong_wire)


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


def test_legacy_catalog_read_records_never_creates_or_repairs(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    lock = catalog.path.with_name(f"{catalog.path.name}.lock")
    assert catalog.read_records() == ()
    assert not catalog.path.exists()
    assert not lock.exists()

    catalog.path.write_bytes(b'{"partial":')
    with journal_file_lock(catalog.path, "exclusive"):
        pass
    original = catalog.path.read_bytes()
    with pytest.raises(CodingLegacyBindingError, match="corrupt"):
        catalog.read_records()
    assert catalog.path.read_bytes() == original


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
