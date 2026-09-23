"""Rooted pre-B snapshots shared by POSIX cutover and offline restore.

The Product supplies one disjoint private directory for each required pre-B
domain. This owner copies and durably publishes those exact directories;
deciding which Product paths constitute each domain remains the Product's
responsibility.
"""

from __future__ import annotations

import os
import secrets
import stat
from collections.abc import Mapping
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import journal_file_lock
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PACKAGE_PRE_B_SNAPSHOT_DOMAINS,
    PackageOfflineRestoreSnapshotEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_offline_restore import (
    DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_BYTES,
    DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_DEPTH,
    DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_ENTRIES,
    PACKAGE_POSIX_OFFLINE_RESTORE_STATE_MANIFEST_VERSION,
    _copy_tree,
    _directory_identity,
    _entry_exists,
    _expected_state_manifest,
    _fsync_tree,
    _inspect_tree,
    _open_directory_at,
    _paths_overlap,
    _pinned_roots_overlap,
    _PinnedRoot,
    _read_regular_file,
    _remove_owned_namespace,
    _rename_directory_noreplace,
    _strict_json_object,
    _supports_posix_rooted_io,
    _validated_limit,
    _validated_root_path,
    _validated_snapshot_bundle,
    _write_new_file,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

_PAYLOAD_NAME = "payload"
_STATE_MANIFEST_NAME = "state-manifest.json"
_EVIDENCE_SUFFIX = ".evidence.json"
_LOCK_NAME = ".epoch-snapshot.lock"
_MAX_EVIDENCE_BYTES = 64 * 1024


class PackagePosixEpochSnapshotEvidenceStore:
    """Read and verify durable pre-B evidence without opening old source roots."""

    def __init__(
        self,
        snapshot_authority_root: str | Path,
        *,
        store_id: str,
        maximum_entries: int = DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_ENTRIES,
        maximum_bytes: int = DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_BYTES,
        maximum_depth: int = DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_DEPTH,
    ) -> None:
        if os.name != "posix" or not _supports_posix_rooted_io():
            raise OSError("POSIX rooted snapshot publication is unavailable")
        if not isinstance(store_id, str) or not store_id:
            raise ValueError("Package snapshot store identity is required")
        self._snapshot_root = _validated_root_path(
            snapshot_authority_root, name="snapshot authority"
        )
        self._store_id = store_id
        self._maximum_entries = _validated_limit(
            maximum_entries, name="maximum snapshot entries"
        )
        self._maximum_bytes = _validated_limit(
            maximum_bytes, name="maximum snapshot bytes"
        )
        self._maximum_depth = _validated_limit(
            maximum_depth, name="maximum snapshot depth"
        )
        snapshot = _PinnedRoot.open(self._snapshot_root)
        try:
            self._snapshot_identities = snapshot.identities
        finally:
            snapshot.close()

    def snapshot(
        self, snapshot_receipt_id: str
    ) -> PackageOfflineRestoreSnapshotEvidenceV1 | None:
        if (
            not isinstance(snapshot_receipt_id, str)
            or len(snapshot_receipt_id) != 64
            or any(char not in "0123456789abcdef" for char in snapshot_receipt_id)
        ):
            raise ValueError("Package snapshot receipt identity is invalid")
        root = _PinnedRoot.open(
            self._snapshot_root,
            expected_identities=self._snapshot_identities,
        )
        try:
            name = snapshot_receipt_id + _EVIDENCE_SUFFIX
            if not _entry_exists(root.descriptor, name):
                return None
            raw, _identity = _read_regular_file(
                root.descriptor, name, maximum_bytes=_MAX_EVIDENCE_BYTES
            )
            evidence = PackageOfflineRestoreSnapshotEvidenceV1.from_dict(
                _strict_json_object(raw, name="Package snapshot evidence")
            )
            if (
                evidence.snapshot.receipt_id != snapshot_receipt_id
                or evidence.snapshot.store_id != self._store_id
                or raw != canonical_json_bytes(evidence.to_dict())
                or evidence.snapshot.entry_count > self._maximum_entries
                or evidence.snapshot.byte_count > self._maximum_bytes
            ):
                raise ValueError("Package snapshot evidence changed")
            bundle = _validated_snapshot_bundle(
                root, evidence, maximum_depth=self._maximum_depth
            )
            try:
                _require_domains(bundle.payload_fd)
            finally:
                bundle.close()
            root.assert_visible()
            return evidence
        finally:
            root.close()


class PackagePosixEpochSnapshotOwner(PackagePosixEpochSnapshotEvidenceStore):
    """Publish a complete, immutable, restore-compatible pre-B snapshot."""

    def __init__(
        self,
        snapshot_authority_root: str | Path,
        *,
        store_id: str,
        domain_roots: Mapping[str, str | Path],
        maximum_entries: int = DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_ENTRIES,
        maximum_bytes: int = DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_BYTES,
        maximum_depth: int = DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_DEPTH,
    ) -> None:
        super().__init__(
            snapshot_authority_root,
            store_id=store_id,
            maximum_entries=maximum_entries,
            maximum_bytes=maximum_bytes,
            maximum_depth=maximum_depth,
        )
        if set(domain_roots) != set(PACKAGE_PRE_B_SNAPSHOT_DOMAINS):
            raise ValueError("Package snapshot requires every pre-B domain")
        self._domain_roots = {
            domain: _validated_root_path(domain_roots[domain], name=domain)
            for domain in PACKAGE_PRE_B_SNAPSHOT_DOMAINS
        }
        if any(
            _paths_overlap(self._snapshot_root, source)
            for source in self._domain_roots.values()
        ):
            raise ValueError("Package snapshot authority overlaps source state")
        domain_paths = tuple(self._domain_roots.values())
        if any(
            _paths_overlap(left, right)
            for index, left in enumerate(domain_paths)
            for right in domain_paths[index + 1 :]
        ):
            raise ValueError("Package snapshot domain roots overlap")
        snapshot = _PinnedRoot.open(
            self._snapshot_root, expected_identities=self._snapshot_identities
        )
        try:
            domain_identities = {}
            with ExitStack() as opened:
                sources: list[_PinnedRoot] = []
                for domain, path in self._domain_roots.items():
                    source = _PinnedRoot.open(path)
                    opened.callback(source.close)
                    if _pinned_roots_overlap(source, snapshot):
                        raise ValueError("Package snapshot source overlaps authority")
                    if any(_pinned_roots_overlap(source, prior) for prior in sources):
                        raise ValueError("Package snapshot domain roots overlap")
                    domain_identities[domain] = source.identities
                    sources.append(source)
            self._domain_identities = domain_identities
        finally:
            snapshot.close()

    def capture(
        self,
        *,
        store_id: str,
        legacy_root_identity: str,
        quiescence_receipt_id: str,
    ) -> PackageEpochCutoverSnapshotReceiptV1:
        if store_id != self._store_id:
            raise ValueError("Package snapshot store changed")
        with journal_file_lock(
            self._snapshot_root / _LOCK_NAME, "exclusive", lock_suffix=""
        ):
            return self._capture_locked(
                legacy_root_identity=legacy_root_identity,
                quiescence_receipt_id=quiescence_receipt_id,
            )

    def _capture_locked(
        self,
        *,
        legacy_root_identity: str,
        quiescence_receipt_id: str,
    ) -> PackageEpochCutoverSnapshotReceiptV1:
        snapshot = _PinnedRoot.open(
            self._snapshot_root, expected_identities=self._snapshot_identities
        )
        sources: dict[str, _PinnedRoot] = {}
        stage_name = ".staging-" + secrets.token_hex(16)
        stage_identity = None
        published = False
        try:
            for domain, path in self._domain_roots.items():
                sources[domain] = _PinnedRoot.open(
                    path, expected_identities=self._domain_identities[domain]
                )
            if _directory_identity(sources["store_bytes"].descriptor) != legacy_root_identity:
                raise ValueError("Package snapshot legacy root changed")
            inspections = {
                domain: _inspect_tree(
                    source.descriptor,
                    maximum_entries=self._maximum_entries,
                    maximum_bytes=self._maximum_bytes,
                    maximum_depth=self._maximum_depth - 1,
                )
                for domain, source in sources.items()
            }
            os.mkdir(stage_name, mode=0o700, dir_fd=snapshot.descriptor)
            stage_metadata = os.stat(
                stage_name,
                dir_fd=snapshot.descriptor,
                follow_symlinks=False,
            )
            stage_identity = stage_metadata.st_dev, stage_metadata.st_ino
            stage_fd = _open_directory_at(snapshot.descriptor, stage_name)
            try:
                opened_stage = os.fstat(stage_fd)
                if (opened_stage.st_dev, opened_stage.st_ino) != stage_identity:
                    raise OSError("Package snapshot staging identity changed")
                os.mkdir(_PAYLOAD_NAME, mode=0o700, dir_fd=stage_fd)
                payload_fd = _open_directory_at(stage_fd, _PAYLOAD_NAME)
                try:
                    for domain in PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
                        source = sources[domain]
                        os.mkdir(domain, mode=0o700, dir_fd=payload_fd)
                        target_fd = _open_directory_at(payload_fd, domain)
                        try:
                            _copy_tree(
                                source.descriptor, target_fd, inspections[domain]
                            )
                            copied_domain = _inspect_tree(
                                target_fd,
                                maximum_entries=self._maximum_entries,
                                maximum_bytes=self._maximum_bytes,
                                maximum_depth=self._maximum_depth - 1,
                            )
                            if copied_domain.entries != inspections[domain].entries:
                                raise OSError("Package snapshot domain changed during copy")
                            os.fchmod(
                                target_fd,
                                stat.S_IMODE(os.fstat(source.descriptor).st_mode),
                            )
                            _fsync_tree(target_fd, copied_domain.entries)
                            os.fsync(target_fd)
                        finally:
                            os.close(target_fd)
                    copied = _inspect_tree(
                        payload_fd,
                        maximum_entries=self._maximum_entries,
                        maximum_bytes=self._maximum_bytes,
                        maximum_depth=self._maximum_depth,
                    )
                    _require_domains(payload_fd)
                    for domain, source in sources.items():
                        source.assert_visible()
                        after = _inspect_tree(
                            source.descriptor,
                            maximum_entries=self._maximum_entries,
                            maximum_bytes=self._maximum_bytes,
                            maximum_depth=self._maximum_depth - 1,
                        )
                        if after.entries != inspections[domain].entries:
                            raise OSError("Package snapshot source changed during copy")
                    snapshot_id = sha256(
                        canonical_json_bytes(
                            {
                                "domain": "loushang.package-posix-epoch-snapshot/v1",
                                "storeId": self._store_id,
                                "legacyRootIdentity": legacy_root_identity,
                                "quiescenceReceiptId": quiescence_receipt_id,
                                "treeDigest": copied.tree_digest,
                            }
                        )
                    ).hexdigest()
                    receipt = PackageEpochCutoverSnapshotReceiptV1.create(
                        store_id=self._store_id,
                        legacy_root_identity=legacy_root_identity,
                        quiescence_receipt_id=quiescence_receipt_id,
                        snapshot_id=snapshot_id,
                        snapshot_revision=1,
                        entry_count=copied.entry_count,
                        byte_count=copied.byte_count,
                    )
                    manifest = {
                        "byteCount": receipt.byte_count,
                        "coveredDomains": list(PACKAGE_PRE_B_SNAPSHOT_DOMAINS),
                        "entryCount": receipt.entry_count,
                        "legacyRootIdentity": receipt.legacy_root_identity,
                        "manifestVersion": PACKAGE_POSIX_OFFLINE_RESTORE_STATE_MANIFEST_VERSION,
                        "snapshotId": receipt.snapshot_id,
                        "snapshotReceiptId": receipt.receipt_id,
                        "snapshotRevision": receipt.snapshot_revision,
                        "storeId": receipt.store_id,
                        "treeDigest": copied.tree_digest,
                    }
                    manifest_bytes = canonical_json_bytes(manifest)
                    evidence = PackageOfflineRestoreSnapshotEvidenceV1.create(
                        receipt,
                        snapshot_tree_digest=copied.tree_digest,
                        state_manifest_digest=sha256(manifest_bytes).hexdigest(),
                    )
                    if manifest != _expected_state_manifest(evidence):
                        raise AssertionError("Package snapshot manifest schema changed")
                    _write_new_file(stage_fd, _STATE_MANIFEST_NAME, manifest_bytes)
                    _fsync_tree(payload_fd, copied.entries)
                    os.fsync(payload_fd)
                finally:
                    os.close(payload_fd)
                os.fsync(stage_fd)
            finally:
                os.close(stage_fd)
            snapshot.assert_visible()
            try:
                _rename_directory_noreplace(
                    snapshot.descriptor,
                    stage_name,
                    snapshot.descriptor,
                    receipt.snapshot_id,
                )
            except FileExistsError:
                # A crash after publishing the bundle but before indexing it
                # must permit exact retry, never replacement of that bundle.
                self._verify_and_index(snapshot, evidence)
                return receipt
            published = True
            os.fsync(snapshot.descriptor)
            self._verify_and_index(snapshot, evidence)
            return receipt
        finally:
            try:
                if stage_identity is not None and not published:
                    _remove_owned_namespace(
                        snapshot.descriptor,
                        stage_name,
                        expected_identity=stage_identity,
                    )
                    os.fsync(snapshot.descriptor)
            finally:
                for source in sources.values():
                    source.close()
                snapshot.close()

    def _verify_and_index(
        self,
        root: _PinnedRoot,
        evidence: PackageOfflineRestoreSnapshotEvidenceV1,
    ) -> None:
        bundle = _validated_snapshot_bundle(
            root, evidence, maximum_depth=self._maximum_depth
        )
        try:
            _require_domains(bundle.payload_fd)
        finally:
            bundle.close()
        name = evidence.snapshot.receipt_id + _EVIDENCE_SUFFIX
        expected = canonical_json_bytes(evidence.to_dict())
        if _entry_exists(root.descriptor, name):
            observed, _identity = _read_regular_file(
                root.descriptor, name, maximum_bytes=_MAX_EVIDENCE_BYTES
            )
            if observed != expected:
                raise ValueError("Package snapshot evidence index changed")
        else:
            temporary_name = ".index-staging-" + secrets.token_hex(16)
            _write_new_file(root.descriptor, temporary_name, expected)
            os.fsync(root.descriptor)
            _rename_directory_noreplace(
                root.descriptor, temporary_name, root.descriptor, name
            )
        os.fsync(root.descriptor)
        root.assert_visible()


def _require_domains(payload_fd: int) -> None:
    if set(os.listdir(payload_fd)) != set(PACKAGE_PRE_B_SNAPSHOT_DOMAINS):
        raise OSError("Package snapshot domain coverage changed")
    for domain in PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
        child = _open_directory_at(payload_fd, domain)
        os.close(child)


__all__ = [
    "PackagePosixEpochSnapshotEvidenceStore",
    "PackagePosixEpochSnapshotOwner",
]
