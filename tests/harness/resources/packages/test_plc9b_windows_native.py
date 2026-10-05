from __future__ import annotations

import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
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
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_deletion_entry_at,
    open_windows_directory,
    open_windows_regular_file_at,
    windows_delete_open_entry,
    windows_rename_open_directory_at,
)

pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="requires native Windows rooted-handle and reparse semantics",
)


def test_windows_rooted_regular_file_handle_reads_data(tmp_path: Path) -> None:
    member = tmp_path / "member.json"
    member.write_bytes(b"{\"source\":\"product\"}")
    parent = open_windows_directory(tmp_path)
    try:
        descriptor = open_windows_regular_file_at(
            parent, member.name, create_new=False, write=False
        )
        try:
            assert os.read(descriptor, 1024) == b"{\"source\":\"product\"}"
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)


def test_windows_rooted_file_opens_remain_isolated_under_concurrent_reads(
    tmp_path: Path,
) -> None:
    member = tmp_path / "repeated.json"
    member.write_bytes(b"concurrent rooted read")
    parent = open_windows_directory(tmp_path)
    try:
        def read_once(_: int) -> bytes:
            descriptor = open_windows_regular_file_at(
                parent, member.name, create_new=False, write=False
            )
            try:
                return os.read(descriptor, 1024)
            finally:
                os.close(descriptor)

        with ThreadPoolExecutor(max_workers=8) as executor:
            assert tuple(executor.map(read_once, range(128))) == (
                b"concurrent rooted read",
            ) * 128
    finally:
        os.close(parent)


def test_windows_private_rooted_file_handle_reads_data(tmp_path: Path) -> None:
    with WindowsPrivateDirectoryAcl() as acl:
        parent = open_windows_directory(tmp_path)
        try:
            private = open_windows_directory(
                "private",
                dir_fd=parent,
                create_new=True,
                security_descriptor=acl.security_descriptor,
            )
            try:
                writer = open_windows_regular_file_at(
                    private,
                    "member.json",
                    create_new=True,
                    write=True,
                    security_descriptor=acl.security_descriptor,
                )
                try:
                    os.write(writer, b"private product")
                finally:
                    os.close(writer)
                reader = open_windows_regular_file_at(
                    private, "member.json", create_new=False, write=False
                )
                try:
                    assert os.read(reader, 1024) == b"private product"
                finally:
                    os.close(reader)
            finally:
                os.close(private)
        finally:
            os.close(parent)


def test_windows_delete_inspected_entry_uses_same_handle_identity(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "private-cache"
    file_path.write_bytes(b"cache")
    directory_path = tmp_path / "private-directory"
    directory_path.mkdir()
    parent = open_windows_directory(tmp_path)
    try:
        for child, directory in ((file_path, False), (directory_path, True)):
            descriptor = open_windows_deletion_entry_at(
                parent, child.name, directory=directory
            )
            try:
                metadata = os.fstat(descriptor)
                identity = (
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_mode,
                    metadata.st_size,
                    metadata.st_mtime_ns,
                )
                wrong = (identity[0], identity[1] + 1, *identity[2:])
                with pytest.raises(OSError, match="identity changed"):
                    windows_delete_open_entry(
                        descriptor, expected_identity=wrong, directory=directory
                    )
                assert child.exists()
                windows_delete_open_entry(
                    descriptor, expected_identity=identity, directory=directory
                )
            finally:
                os.close(descriptor)
            assert not child.exists()
    finally:
        os.close(parent)


def test_windows_rename_inspected_directory_uses_same_handle_identity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "private-root"
    source.mkdir()
    parent = open_windows_directory(tmp_path)
    try:
        descriptor = open_windows_deletion_entry_at(parent, source.name, directory=True)
        try:
            metadata = os.fstat(descriptor)
            identity = (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_size,
                metadata.st_mtime_ns,
            )
            wrong = (identity[0], identity[1] + 1, *identity[2:])
            with pytest.raises(OSError, match="identity changed"):
                windows_rename_open_directory_at(
                    parent,
                    descriptor,
                    "private-tombstone",
                    expected_identity=wrong,
                )
            assert source.is_dir()
            windows_rename_open_directory_at(
                parent,
                descriptor,
                "private-tombstone",
                expected_identity=identity,
            )
        finally:
            os.close(descriptor)
        assert not source.exists()
        assert (tmp_path / "private-tombstone").is_dir()
    finally:
        os.close(parent)


@dataclass
class _Stream:
    envelope: AuthenticatedSourceEnvelopeV1
    payload: bytes

    def transfer_to(self, sink: BoundedAcquisitionSinkPort) -> SourceAdapterResultV1:
        sink.begin_request()
        sink.write(self.payload)
        return SourceAdapterResultV1(disposition="complete")


@dataclass
class _Authority:
    payload: bytes
    call_count: int = 0

    def authorize(self, request: PackageAcquisitionRequestV1) -> _Stream:
        self.call_count += 1
        return _Stream(
            envelope=AuthenticatedSourceEnvelopeV1(
                operation_id=request.operation_id,
                node_id=request.node_id,
                canonical_source_identity=request.canonical_source_identity,
                origin_kind="https",
                authentication_decision="authorized",
                authority_id="source-authority:windows-native",
                requested_locator_digest=request.requested_locator_digest,
                expected_artifact_digest=sha256(self.payload).hexdigest(),
                redirect_policy_revision="redirect-policy:1",
                policy_revision=request.policy_revision,
                capture_epoch=1,
            ),
            payload=self.payload,
        )


def _request() -> PackageAcquisitionRequestV1:
    return PackageAcquisitionRequestV1(
        operation_id="windows-native-operation",
        attempt_epoch=1,
        node_id="root",
        canonical_source_identity="https://packages.example.test/acme.whl",
        request_fingerprint="a" * 64,
        requested_locator_digest="b" * 64,
        policy_revision="source-policy:1",
    )


def _owner(
    tmp_path: Path,
) -> tuple[PackageAcquisitionOwner, PackageQuarantineStore, _Authority]:
    authority = _Authority(payload=b"windows-native-wheel-bytes")
    store = PackageQuarantineStore(tmp_path / "quarantine")
    return (
        PackageAcquisitionOwner(
            source_authority=authority,
            quarantine_store=store,
        ),
        store,
        authority,
    )


def _budgets() -> PackageAcquisitionBudgetV1:
    return PackageAcquisitionBudgetV1(
        max_transport_bytes=4096,
        max_requests=1,
        max_redirects=0,
        max_wall_time_ms=1000,
    )


def test_windows_native_quarantine_handles_pin_root_and_cleanup_exact_attempt(
    tmp_path: Path,
) -> None:
    owner, store, authority = _owner(tmp_path)
    candidate = owner.acquire(_request(), budgets=_budgets())
    moved = tmp_path / "moved-quarantine"

    with pytest.raises(OSError):
        store.root.rename(moved)
    with candidate.open_for_verifier() as artifact:
        assert artifact.read() == authority.payload

    candidate.cleanup()
    assert store.attempt_names() == ()


def test_windows_native_quarantine_root_attempt_and_artifact_have_private_acl(
    tmp_path: Path,
) -> None:
    owner, store, _ = _owner(tmp_path)
    candidate = owner.acquire(_request(), budgets=_budgets())
    try:
        with WindowsPrivateDirectoryAcl() as acl:
            root = open_windows_directory(store.root, read_control=True)
            try:
                acl.validate(root)
                attempt = open_windows_directory(
                    store.attempt_names()[0], dir_fd=root, read_control=True
                )
                try:
                    acl.validate(attempt)
                    artifact = open_windows_regular_file_at(
                        attempt,
                        candidate._attempt._artifact_name,
                        create_new=False,
                        write=False,
                        read_control=True,
                    )
                    try:
                        acl.validate(artifact)
                    finally:
                        os.close(artifact)
                finally:
                    os.close(attempt)
            finally:
                os.close(root)
    finally:
        candidate.cleanup()


def test_windows_native_store_rejects_root_swap_before_new_attempt(
    tmp_path: Path,
) -> None:
    owner, store, authority = _owner(tmp_path)
    trusted = tmp_path / "trusted-before-attempt"
    store.root.rename(trusted)
    store.root.mkdir()

    with pytest.raises(PackageAcquisitionError) as rejected:
        owner.acquire(_request(), budgets=_budgets())

    assert rejected.value.code == "package_artifact_identity_changed"
    assert authority.call_count == 1
    assert tuple(store.root.iterdir()) == ()


def test_windows_native_partial_tree_reset_is_rooted_and_source_free(
    tmp_path: Path,
) -> None:
    owner, store, authority = _owner(tmp_path)
    candidate = owner.acquire(_request(), budgets=_budgets())
    writer = candidate._attempt._begin_extraction()
    partial = writer._open_file(("partial", "nested", "entry"))
    partial.write(b"interrupted")
    partial.close()
    writer._abort()
    receipt = candidate.receipt
    candidate.suspend_for_recovery()

    reopened = owner.reopen_acquired(
        _request(),
        receipt,
        reset_extraction=True,
    )

    assert authority.call_count == 1
    attempt = store.root / store.attempt_names()[0]
    assert not (attempt / "tree").exists()
    reopened.cleanup()
    assert store.attempt_names() == ()


def test_windows_native_attempt_reparse_is_rejected_without_outside_delete(
    tmp_path: Path,
) -> None:
    owner, store, authority = _owner(tmp_path)
    candidate = owner.acquire(_request(), budgets=_budgets())
    receipt = candidate.receipt
    candidate.suspend_for_recovery()
    attempt = store.root / store.attempt_names()[0]
    detached = tmp_path / "detached-attempt"
    attempt.rename(detached)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")
    attempt.symlink_to(outside, target_is_directory=True)

    with pytest.raises(PackageAcquisitionError) as rejected:
        owner.reopen_acquired(_request(), receipt, reset_extraction=False)

    assert rejected.value.code == "package_artifact_identity_changed"
    assert authority.call_count == 1
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    attempt.unlink()


def test_windows_native_root_aba_cannot_adopt_replacement_tree(
    tmp_path: Path,
) -> None:
    owner, store, authority = _owner(tmp_path)
    candidate = owner.acquire(_request(), budgets=_budgets())
    receipt = candidate.receipt
    candidate.suspend_for_recovery()
    trusted = tmp_path / "trusted-detached"
    store.root.rename(trusted)
    shutil.copytree(trusted, store.root)
    outside = tmp_path / "outside-sentinel"
    outside.write_text("preserve", encoding="utf-8")

    with pytest.raises(PackageAcquisitionError) as rejected:
        owner.reopen_acquired(_request(), receipt, reset_extraction=False)

    assert rejected.value.code == "package_artifact_identity_changed"
    assert authority.call_count == 1
    assert outside.read_text(encoding="utf-8") == "preserve"
