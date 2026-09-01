from __future__ import annotations

import os
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

import pytest

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


@dataclass
class _Clock:
    now: float = 100.0

    def __call__(self) -> float:
        return self.now


@dataclass
class _Stream:
    envelope: AuthenticatedSourceEnvelopeV1
    chunks: tuple[bytes, ...] = (b"wheel-bytes",)
    request_count: int = 1
    redirects: tuple[str, ...] = ()
    clock: _Clock | None = None
    advance_seconds: float = 0.0
    observed_public_names: set[str] = field(default_factory=set)

    def transfer_to(self, sink: BoundedAcquisitionSinkPort) -> SourceAdapterResultV1:
        self.observed_public_names = {
            name for name in dir(sink) if not name.startswith("_")
        }
        for _index in range(self.request_count):
            sink.begin_request()
        for redirect in self.redirects:
            sink.record_redirect(redirect)
        for chunk in self.chunks:
            sink.write(chunk)
            if self.clock is not None:
                self.clock.now += self.advance_seconds
        return SourceAdapterResultV1(disposition="complete")


@dataclass
class _Authority:
    stream: _Stream | None = None
    error_code: str | None = None

    def authorize(self, _request: PackageAcquisitionRequestV1) -> _Stream:
        if self.error_code is not None:
            raise PackageAcquisitionError(
                "Source authority rejected the request",
                code=self.error_code,
                stage="acquiring",
                retryable=False,
                consumed_bytes=0,
            )
        assert self.stream is not None
        return self.stream


def _request() -> PackageAcquisitionRequestV1:
    return PackageAcquisitionRequestV1(
        operation_id="operation-1",
        attempt_epoch=1,
        node_id="root",
        canonical_source_identity="https://packages.example.test/acme.whl",
        request_fingerprint="a" * 64,
        requested_locator_digest="b" * 64,
        policy_revision="source-policy:1",
    )


def _envelope(
    *,
    source: str = "https://packages.example.test/acme.whl",
    expected_digest: str | None = None,
) -> AuthenticatedSourceEnvelopeV1:
    return AuthenticatedSourceEnvelopeV1(
        operation_id="operation-1",
        node_id="root",
        canonical_source_identity=source,
        origin_kind="https",
        authentication_decision="authorized",
        authority_id="source-authority:registry",
        requested_locator_digest="b" * 64,
        expected_artifact_digest=expected_digest,
        redirect_policy_revision="redirect-policy:1",
        policy_revision="source-policy:1",
        capture_epoch=1,
    )


def _budgets(**overrides: int) -> PackageAcquisitionBudgetV1:
    values = {
        "max_transport_bytes": 1024,
        "max_requests": 2,
        "max_redirects": 1,
        "max_wall_time_ms": 1000,
    }
    values.update(overrides)
    return PackageAcquisitionBudgetV1(**values)


def _owner(
    tmp_path: Path,
    stream: _Stream,
    *,
    clock: _Clock | None = None,
) -> tuple[PackageAcquisitionOwner, PackageQuarantineStore]:
    store = PackageQuarantineStore(tmp_path / "quarantine")
    return (
        PackageAcquisitionOwner(
            source_authority=_Authority(stream=stream),
            quarantine_store=store,
            clock=clock,
        ),
        store,
    )


def test_source_adapter_receives_bounded_sink_without_path_authority(
    tmp_path: Path,
) -> None:
    payload = b"verified-wheel-bytes"
    stream = _Stream(
        envelope=_envelope(expected_digest=sha256(payload).hexdigest()),
        chunks=(payload[:7], payload[7:]),
    )
    owner, store = _owner(tmp_path, stream)

    candidate = owner.acquire(_request(), budgets=_budgets())

    assert stream.observed_public_names == {
        "begin_request",
        "record_redirect",
        "write",
    }
    assert candidate.receipt.actual_byte_digest == sha256(payload).hexdigest()
    assert candidate.receipt.actual_byte_count == len(payload)
    assert candidate.receipt.request_count == 1
    assert candidate.receipt.redirect_count == 0
    with candidate.open_for_verifier() as verifier_input:
        assert verifier_input.read() == payload
    assert "path" not in str(candidate.receipt.to_dict()).lower()
    assert str(store.root) not in repr(candidate)
    candidate.cleanup()
    assert store.attempt_names() == ()


def test_unauthorized_source_creates_no_quarantine(tmp_path: Path) -> None:
    store = PackageQuarantineStore(tmp_path / "quarantine")
    owner = PackageAcquisitionOwner(
        source_authority=_Authority(error_code="package_source_unauthorized"),
        quarantine_store=store,
    )

    with pytest.raises(PackageAcquisitionError) as denied:
        owner.acquire(_request(), budgets=_budgets())

    assert denied.value.code == "package_source_unauthorized"
    assert denied.value.consumed_bytes == 0
    assert store.attempt_names() == ()


def test_source_authority_exception_message_is_not_propagated(tmp_path: Path) -> None:
    secret = "authority-private-token"
    store = PackageQuarantineStore(tmp_path / "quarantine")

    @dataclass
    class _SecretAuthority:
        def authorize(self, _request: PackageAcquisitionRequestV1) -> _Stream:
            raise PackageAcquisitionError(
                f"registry rejected token {secret}",
                code="package_source_unauthorized",
                stage="acquiring",
                retryable=False,
                consumed_bytes=0,
            )

    owner = PackageAcquisitionOwner(
        source_authority=_SecretAuthority(),
        quarantine_store=store,
    )

    with pytest.raises(PackageAcquisitionError) as denied:
        owner.acquire(_request(), budgets=_budgets())
    assert secret not in str(denied.value)
    assert denied.value.__cause__ is None


def test_quarantine_rejects_link_root_and_link_ancestor(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("native Windows reparse fixtures are a later PLC9B2 gate")
    real_root = tmp_path / "real"
    real_root.mkdir(mode=0o700)
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(OSError, match="private directory|link"):
        PackageQuarantineStore(linked_root)

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(OSError, match="link"):
        PackageQuarantineStore(linked_parent / "quarantine")


def test_quarantine_rejects_existing_non_private_root(tmp_path: Path) -> None:
    root = tmp_path / "broad"
    root.mkdir(mode=0o755)
    root.chmod(0o755)

    with pytest.raises(OSError, match="permissions"):
        PackageQuarantineStore(root)


def test_candidate_cleanup_can_retry_exact_attempt_after_failure(
    tmp_path: Path,
) -> None:
    payload = b"wheel"
    stream = _Stream(
        envelope=_envelope(expected_digest=sha256(payload).hexdigest()),
        chunks=(payload,),
    )
    owner, store = _owner(tmp_path, stream)
    candidate = owner.acquire(_request(), budgets=_budgets())
    attempt = store.attempt_names()[0]
    unexpected = store.root / attempt / "unexpected"
    unexpected.write_bytes(b"debt")

    with pytest.raises(OSError):
        candidate.cleanup()
    unexpected.unlink()
    candidate.cleanup()
    assert store.attempt_names() == ()


def test_store_rejects_root_replacement_before_new_attempt(tmp_path: Path) -> None:
    payload = b"wheel"
    stream = _Stream(
        envelope=_envelope(expected_digest=sha256(payload).hexdigest()),
        chunks=(payload,),
    )
    owner, store = _owner(tmp_path, stream)
    trusted = tmp_path / "trusted-quarantine"
    store.root.rename(trusted)
    store.root.mkdir(mode=0o700)

    with pytest.raises(PackageAcquisitionError) as rejected:
        owner.acquire(_request(), budgets=_budgets())

    assert rejected.value.code == "package_artifact_identity_changed"
    assert tuple(store.root.iterdir()) == ()


@pytest.mark.parametrize(
    ("changed", "code"),
    [
        (
            {"canonical_source_identity": "https://evil.example.test/acme.whl"},
            "package_source_provenance_changed",
        ),
        (
            {"requested_locator_digest": "c" * 64},
            "package_source_provenance_changed",
        ),
        (
            {"policy_revision": "source-policy:changed"},
            "package_source_provenance_changed",
        ),
    ],
)
def test_changed_source_envelope_fails_before_quarantine(
    tmp_path: Path,
    changed: dict[str, str],
    code: str,
) -> None:
    values = _envelope().to_dict()
    wire_names = {
        "canonical_source_identity": "canonicalSourceIdentity",
        "requested_locator_digest": "requestedLocatorDigest",
        "policy_revision": "policyRevision",
    }
    for key, value in changed.items():
        values[wire_names[key]] = value
    stream = _Stream(envelope=AuthenticatedSourceEnvelopeV1.from_dict(values))
    owner, store = _owner(tmp_path, stream)

    with pytest.raises(PackageAcquisitionError) as rejected:
        owner.acquire(_request(), budgets=_budgets())

    assert rejected.value.code == code
    assert rejected.value.consumed_bytes == 0
    assert store.attempt_names() == ()


def test_transport_byte_budget_is_checked_before_each_write(tmp_path: Path) -> None:
    stream = _Stream(
        envelope=_envelope(),
        chunks=(b"12345678", b"overflow"),
    )
    owner, store = _owner(tmp_path, stream)

    with pytest.raises(PackageAcquisitionError) as limited:
        owner.acquire(_request(), budgets=_budgets(max_transport_bytes=8))

    assert limited.value.code == "package_acquisition_limit_exceeded"
    assert limited.value.retryable is True
    assert limited.value.consumed_bytes == 8
    assert store.total_residue_bytes() <= 8
    assert store.attempt_names() == ()


@pytest.mark.parametrize(
    ("request_count", "redirects", "expected_code"),
    [
        (3, (), "package_acquisition_limit_exceeded"),
        (
            1,
            (
                "https://mirror-1.example.test/acme.whl",
                "https://mirror-2.example.test/acme.whl",
            ),
            "package_acquisition_limit_exceeded",
        ),
    ],
)
def test_request_and_redirect_budgets_are_incremental(
    tmp_path: Path,
    request_count: int,
    redirects: tuple[str, ...],
    expected_code: str,
) -> None:
    stream = _Stream(
        envelope=_envelope(),
        request_count=request_count,
        redirects=redirects,
    )
    owner, store = _owner(tmp_path, stream)

    with pytest.raises(PackageAcquisitionError) as limited:
        owner.acquire(_request(), budgets=_budgets())

    assert limited.value.code == expected_code
    assert limited.value.consumed_bytes == 0
    assert store.attempt_names() == ()


def test_wall_clock_budget_is_checked_during_streaming(tmp_path: Path) -> None:
    clock = _Clock()
    stream = _Stream(
        envelope=_envelope(),
        chunks=(b"first", b"second"),
        clock=clock,
        advance_seconds=0.006,
    )
    owner, store = _owner(tmp_path, stream, clock=clock)

    with pytest.raises(PackageAcquisitionError) as timed_out:
        owner.acquire(_request(), budgets=_budgets(max_wall_time_ms=5))

    assert timed_out.value.code == "package_operation_timed_out"
    assert timed_out.value.retryable is True
    assert timed_out.value.consumed_bytes == len(b"first")
    assert store.attempt_names() == ()


def test_declared_digest_mismatch_is_terminal_and_cleanup_is_exact(
    tmp_path: Path,
) -> None:
    payload = b"changed-wheel"
    stream = _Stream(
        envelope=_envelope(expected_digest="d" * 64),
        chunks=(payload,),
    )
    owner, store = _owner(tmp_path, stream)

    with pytest.raises(PackageAcquisitionError) as mismatch:
        owner.acquire(_request(), budgets=_budgets())

    assert mismatch.value.code == "package_acquisition_digest_mismatch"
    assert mismatch.value.retryable is False
    assert mismatch.value.consumed_bytes == len(payload)
    assert store.attempt_names() == ()


def test_secret_bearing_locator_never_enters_envelope_receipt_or_error(
    tmp_path: Path,
) -> None:
    secret = "private-registry-token"
    payload = b"wheel"
    envelope = _envelope(expected_digest=sha256(payload).hexdigest())
    stream = _Stream(envelope=envelope, chunks=(payload,))
    owner, _store = _owner(tmp_path, stream)
    request = PackageAcquisitionRequestV1(
        operation_id="operation-1",
        attempt_epoch=1,
        node_id="root",
        canonical_source_identity=envelope.canonical_source_identity,
        request_fingerprint="a" * 64,
        requested_locator_digest="b" * 64,
        policy_revision="source-policy:1",
        credential_reference=f"opaque:{secret}",
    )

    candidate = owner.acquire(request, budgets=_budgets())

    evidence = (
        repr(request),
        repr(candidate),
        str(envelope.to_dict()),
        str(candidate.receipt.to_dict()),
    )
    assert all(secret not in item for item in evidence)
    candidate.cleanup()


def test_versioned_acquisition_evidence_rejects_unknown_fields(tmp_path: Path) -> None:
    payload = b"wheel"
    stream = _Stream(
        envelope=_envelope(expected_digest=sha256(payload).hexdigest()),
        chunks=(payload,),
    )
    owner, _store = _owner(tmp_path, stream)
    candidate = owner.acquire(_request(), budgets=_budgets())

    assert type(candidate.receipt).from_dict(candidate.receipt.to_dict()) == (
        candidate.receipt
    )
    changed = candidate.receipt.to_dict()
    changed["unknown"] = True
    with pytest.raises(ValueError, match="fields do not match"):
        type(candidate.receipt).from_dict(changed)
    candidate.cleanup()
