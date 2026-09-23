from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    PackageAcquisitionBudgetV1,
    PackageAcquisitionError,
    PackageAcquisitionOwner,
    PackageAcquisitionRequestV1,
    PackageQuarantineStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.local_source import (
    PackagePinnedLocalWheelSourceAuthority,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX rooted local Source")


def _request(source: Path) -> PackageAcquisitionRequestV1:
    identity = str(source)
    return PackageAcquisitionRequestV1(
        operation_id="operation:local-wheel",
        attempt_epoch=1,
        node_id="root",
        canonical_source_identity=identity,
        request_fingerprint="a" * 64,
        requested_locator_digest=sha256(identity.encode()).hexdigest(),
        policy_revision="local-policy:1",
    )


def _owner(
    root: Path, source: Path, digest: str
) -> tuple[PackageAcquisitionOwner, PackageQuarantineStore]:
    store = PackageQuarantineStore(root / "quarantine")
    authority = PackagePinnedLocalWheelSourceAuthority(
        source_root=root / "sources",
        allowed_digests={str(source): digest},
        policy_revision="local-policy:1",
        authority_id="coding-local-source:1",
    )
    return PackageAcquisitionOwner(
        source_authority=authority, quarantine_store=store
    ), store


def _budgets() -> PackageAcquisitionBudgetV1:
    return PackageAcquisitionBudgetV1(
        max_transport_bytes=1024,
        max_requests=1,
        max_redirects=0,
        max_wall_time_ms=1000,
    )


def test_pinned_local_wheel_streams_to_owner_quarantine(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    source = sources / "plugin-1.0-py3-none-any.whl"
    payload = b"local-wheel-bytes"
    source.write_bytes(payload)
    owner, _store = _owner(tmp_path, source, sha256(payload).hexdigest())

    candidate = owner.acquire(_request(source), budgets=_budgets())

    assert candidate.authenticated_envelope.origin_kind == "local"
    assert candidate.receipt.actual_byte_digest == sha256(payload).hexdigest()
    with candidate.open_for_verifier() as verifier_input:
        assert verifier_input.read() == payload
    candidate.suspend_for_recovery()


def test_local_source_refuses_unlisted_identity_before_quarantine(
    tmp_path: Path,
) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    allowed = sources / "allowed.whl"
    allowed.write_bytes(b"allowed")
    unlisted = sources / "unlisted.whl"
    unlisted.write_bytes(b"unlisted")
    owner, store = _owner(tmp_path, allowed, sha256(b"allowed").hexdigest())

    with pytest.raises(PackageAcquisitionError) as raised:
        owner.acquire(_request(unlisted), budgets=_budgets())
    assert raised.value.code == "package_source_unauthorized"
    assert store.attempt_names() == ()


def test_local_source_refuses_changed_bytes_and_cleans_quarantine(
    tmp_path: Path,
) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    source = sources / "plugin.whl"
    source.write_bytes(b"original")
    owner, store = _owner(tmp_path, source, sha256(b"original").hexdigest())
    source.write_bytes(b"changed")

    with pytest.raises(PackageAcquisitionError) as raised:
        owner.acquire(_request(source), budgets=_budgets())
    assert raised.value.code == "package_acquisition_digest_mismatch"
    assert store.attempt_names() == ()


def test_local_source_refuses_link_swap_without_following_target(
    tmp_path: Path,
) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    source = sources / "plugin.whl"
    source.write_bytes(b"original")
    owner, store = _owner(tmp_path, source, sha256(b"original").hexdigest())
    source.unlink()
    target = tmp_path / "outside.whl"
    target.write_bytes(b"original")
    source.symlink_to(target)

    with pytest.raises(PackageAcquisitionError) as raised:
        owner.acquire(_request(source), budgets=_budgets())
    assert raised.value.code == "package_source_provenance_changed"
    assert store.attempt_names() == ()


def test_local_source_refuses_linked_ancestor(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    real = sources / "real"
    real.mkdir()
    source = real / "plugin.whl"
    source.write_bytes(b"original")
    linked = sources / "linked"
    linked.symlink_to(real, target_is_directory=True)
    linked_source = linked / "plugin.whl"
    owner, store = _owner(
        tmp_path, linked_source, sha256(b"original").hexdigest()
    )

    with pytest.raises(PackageAcquisitionError) as raised:
        owner.acquire(_request(linked_source), budgets=_budgets())
    assert raised.value.code == "package_source_provenance_changed"
    assert store.attempt_names() == ()


def test_local_source_refuses_policy_change_before_quarantine(tmp_path: Path) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    source = sources / "plugin.whl"
    source.write_bytes(b"original")
    owner, store = _owner(tmp_path, source, sha256(b"original").hexdigest())
    request = _request(source)

    with pytest.raises(PackageAcquisitionError) as raised:
        owner.acquire(
            PackageAcquisitionRequestV1(
                operation_id=request.operation_id,
                attempt_epoch=request.attempt_epoch,
                node_id=request.node_id,
                canonical_source_identity=request.canonical_source_identity,
                request_fingerprint=request.request_fingerprint,
                requested_locator_digest=request.requested_locator_digest,
                policy_revision="local-policy:changed",
            ),
            budgets=_budgets(),
        )
    assert raised.value.code == "package_source_unauthorized"
    assert store.attempt_names() == ()
