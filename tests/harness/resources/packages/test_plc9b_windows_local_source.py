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

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-native contract")


def _request(source: Path) -> PackageAcquisitionRequestV1:
    identity = str(source)
    return PackageAcquisitionRequestV1(
        operation_id="windows-local-wheel",
        attempt_epoch=1,
        node_id="root",
        canonical_source_identity=identity,
        request_fingerprint="a" * 64,
        requested_locator_digest=sha256(identity.encode()).hexdigest(),
        policy_revision="windows-local-policy:1",
    )


def _owner(root: Path, source: Path, digest: str) -> PackageAcquisitionOwner:
    authority = PackagePinnedLocalWheelSourceAuthority(
        source_root=root / "sources",
        allowed_digests={str(source): digest},
        policy_revision="windows-local-policy:1",
        authority_id="windows-local-source:1",
    )
    return PackageAcquisitionOwner(
        source_authority=authority,
        quarantine_store=PackageQuarantineStore(root / "quarantine"),
    )


def test_windows_local_source_streams_exact_digest_into_private_quarantine(
    tmp_path: Path,
) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    source = sources / "plugin-1-py3-none-any.whl"
    body = b"windows-local-wheel"
    source.write_bytes(body)
    owner = _owner(tmp_path, source, sha256(body).hexdigest())
    candidate = owner.acquire(
        _request(source),
        budgets=PackageAcquisitionBudgetV1(
            max_transport_bytes=1024,
            max_requests=1,
            max_redirects=0,
            max_wall_time_ms=1000,
        ),
    )
    try:
        with candidate.open_for_verifier() as artifact:
            assert artifact.read() == body
    finally:
        candidate.cleanup()


def test_windows_local_source_refuses_reparse_target_before_store_effect(
    tmp_path: Path,
) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    source = sources / "plugin-1-py3-none-any.whl"
    body = b"windows-local-wheel"
    source.write_bytes(body)
    owner = _owner(tmp_path, source, sha256(body).hexdigest())
    source.unlink()
    outside = tmp_path / "outside.whl"
    outside.write_bytes(body)
    source.symlink_to(outside)
    with pytest.raises(PackageAcquisitionError) as refused:
        owner.acquire(
            _request(source),
            budgets=PackageAcquisitionBudgetV1(
                max_transport_bytes=1024,
                max_requests=1,
                max_redirects=0,
                max_wall_time_ms=1000,
            ),
        )
    assert refused.value.code == "package_source_provenance_changed"
    assert outside.read_bytes() == body
