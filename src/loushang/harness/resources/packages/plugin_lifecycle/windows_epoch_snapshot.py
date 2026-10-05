"""Rooted Windows pre-B snapshot publication and authenticated evidence reads.

The Product maps complete legacy state into the fixed offline-restore domains.
The snapshot is copied under native directory handles and indexed only after
its immutable bundle can be read back through the restore verifier.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal import journal_file_lock
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PACKAGE_PRE_B_SNAPSHOT_DOMAINS,
    PackageOfflineRestoreSnapshotEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_offline_restore import (
    DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_BYTES,
    DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_DEPTH,
    DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_ENTRIES,
    PACKAGE_WINDOWS_OFFLINE_RESTORE_STATE_MANIFEST_VERSION,
    _copy_tree,
    _directory_identity,
    _entry_exists,
    _expected_state_manifest,
    _flush_tree,
    _inspect_tree,
    _native_identity,
    _open_directory_at,
    _paths_overlap,
    _pinned_roots_overlap,
    _PinnedWindowsRoot,
    _read_regular_file,
    _remove_owned_namespace,
    _revalidate_source,
    _strict_json_object,
    _TreeInspection,
    _validate_entry_name,
    _validated_limit,
    _validated_root_path,
    _validated_snapshot_bundle,
    _write_new_file,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
    supports_windows_rooted_io,
    windows_flush_directory,
    windows_flush_file,
    windows_listdir_at,
    windows_rename_at,
    windows_unlink_at,
)

_PAYLOAD_NAME = "payload"
_STATE_MANIFEST_NAME = "state-manifest.json"
_EVIDENCE_SUFFIX = ".evidence.json"
_LOCK_NAME = ".epoch-snapshot.lock"
# Held by pre-fence quiescence; Windows denies reads while its byte is locked.
_FENCE_TRANSIENT_NAMES = frozenset({"coordination.lock"})
_LEGACY_ROOT_POINTER_NAME = "legacy-root-pointer.json"
_MAX_EVIDENCE_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class PackageWindowsSnapshotSharedMemberV1:
    """One physical top-level member intentionally used by several domains."""

    source_root: Path
    member_name: str
    domains: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source_root, Path) or type(self.member_name) is not str:
            raise TypeError("Package snapshot shared member is invalid")
        _validated_root_path(self.source_root, name="shared source")
        _validate_entry_name(self.member_name)
        if (
            len(self.domains) < 2
            or self.domains != tuple(sorted(set(self.domains)))
            or not set(self.domains) <= set(PACKAGE_PRE_B_SNAPSHOT_DOMAINS)
        ):
            raise ValueError("Package snapshot shared member domains are invalid")


class PackageWindowsEpochSnapshotEvidenceStore:
    """Verify a published snapshot without opening any old Source root."""

    def __init__(
        self,
        snapshot_authority_root: str | Path,
        *,
        store_id: str,
        maximum_entries: int = DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_ENTRIES,
        maximum_bytes: int = DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_BYTES,
        maximum_depth: int = DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_DEPTH,
    ) -> None:
        if os.name != "nt" or not supports_windows_rooted_io():
            raise OSError("Windows rooted snapshot publication is unavailable")
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
        root = _open_private_root(self._snapshot_root)
        try:
            self._snapshot_identities = root.identities
        finally:
            root.close()

    def snapshot(
        self, snapshot_receipt_id: str
    ) -> PackageOfflineRestoreSnapshotEvidenceV1 | None:
        if (
            type(snapshot_receipt_id) is not str
            or len(snapshot_receipt_id) != 64
            or any(char not in "0123456789abcdef" for char in snapshot_receipt_id)
        ):
            raise ValueError("Package snapshot receipt identity is invalid")
        root = _open_private_root(
            self._snapshot_root, expected_identities=self._snapshot_identities
        )
        try:
            name = snapshot_receipt_id + _EVIDENCE_SUFFIX
            if not _entry_exists(root.descriptor, name):
                return None
            raw, _ = _read_regular_file(
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

    def read_regular_member(
        self,
        snapshot_receipt_id: str,
        *,
        domain: str,
        member_name: str,
        maximum_bytes: int = 2 * 1024 * 1024,
    ) -> bytes | None:
        if domain not in PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
            raise ValueError("Package snapshot domain is invalid")
        _validate_entry_name(member_name)
        limit = min(
            _validated_limit(maximum_bytes, name="maximum snapshot member bytes"),
            self._maximum_bytes,
        )
        evidence = self.snapshot(snapshot_receipt_id)
        if evidence is None:
            return None
        root = _open_private_root(
            self._snapshot_root, expected_identities=self._snapshot_identities
        )
        try:
            bundle = _validated_snapshot_bundle(
                root, evidence, maximum_depth=self._maximum_depth
            )
            try:
                _require_domains(bundle.payload_fd)
                directory = _open_directory_at(bundle.payload_fd, domain)
                try:
                    value = (
                        _read_regular_file(directory, member_name, maximum_bytes=limit)[
                            0
                        ]
                        if _entry_exists(directory, member_name)
                        else None
                    )
                finally:
                    os.close(directory)
                _revalidate_source(bundle, evidence, maximum_depth=self._maximum_depth)
                root.assert_visible()
                return value
            finally:
                bundle.close()
        finally:
            root.close()

    def list_domain_members(
        self, snapshot_receipt_id: str, *, domain: str
    ) -> tuple[str, ...] | None:
        if domain not in PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
            raise ValueError("Package snapshot domain is invalid")
        evidence = self.snapshot(snapshot_receipt_id)
        if evidence is None:
            return None
        root = _open_private_root(
            self._snapshot_root, expected_identities=self._snapshot_identities
        )
        try:
            bundle = _validated_snapshot_bundle(
                root, evidence, maximum_depth=self._maximum_depth
            )
            try:
                _require_domains(bundle.payload_fd)
                prefix = domain + "/"
                members = tuple(
                    entry.logical_path[len(prefix) :]
                    for entry in bundle.inspection.entries
                    if entry.logical_path.startswith(prefix)
                    and entry.logical_path.count("/") == 1
                )
                _revalidate_source(bundle, evidence, maximum_depth=self._maximum_depth)
                root.assert_visible()
                return members
            finally:
                bundle.close()
        finally:
            root.close()


class PackageWindowsEpochSnapshotOwner(PackageWindowsEpochSnapshotEvidenceStore):
    """Publish one complete restore-compatible Windows pre-B snapshot."""

    def __init__(
        self,
        snapshot_authority_root: str | Path,
        *,
        store_id: str,
        domain_roots: Mapping[str, str | Path],
        domain_members: Mapping[str, tuple[str, ...] | None] | None = None,
        shared_members: tuple[PackageWindowsSnapshotSharedMemberV1, ...] = (),
        legacy_root_pointer_name: str | None = None,
        maximum_entries: int = DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_ENTRIES,
        maximum_bytes: int = DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_BYTES,
        maximum_depth: int = DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_DEPTH,
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
        if legacy_root_pointer_name is not None:
            _validate_entry_name(legacy_root_pointer_name)
            if self._domain_roots["store_bytes"].name != legacy_root_pointer_name:
                raise ValueError("Package snapshot legacy root name does not match")
        self._legacy_root_pointer_name = legacy_root_pointer_name
        if domain_members is not None and set(domain_members) != set(
            PACKAGE_PRE_B_SNAPSHOT_DOMAINS
        ):
            raise ValueError("Package snapshot member mapping requires every domain")
        self._domain_members: dict[str, tuple[str, ...] | None] = {}
        for domain in PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
            members = None if domain_members is None else domain_members[domain]
            if members is not None:
                if (
                    type(members) is not tuple
                    or any(type(name) is not str for name in members)
                    or members != tuple(sorted(set(members)))
                ):
                    raise ValueError("Package snapshot domain members are invalid")
                for name in members:
                    _validate_entry_name(name)
            self._domain_members[domain] = members
        if type(shared_members) is not tuple:
            raise TypeError("Package snapshot shared members must be a tuple")
        self._shared_members = shared_members
        self._shared_aliases: dict[tuple[Path, str], tuple[str, ...]] = {}
        for alias in shared_members:
            if not isinstance(alias, PackageWindowsSnapshotSharedMemberV1):
                raise TypeError("Package snapshot shared member is invalid")
            key = alias.source_root, alias.member_name
            if key in self._shared_aliases or any(
                self._domain_roots[domain] != alias.source_root
                or self._domain_members[domain] is None
                or alias.member_name not in (self._domain_members[domain] or ())
                for domain in alias.domains
            ):
                raise ValueError("Package snapshot shared member mapping is invalid")
            self._shared_aliases[key] = alias.domains
        if any(
            _paths_overlap(self._snapshot_root, source)
            for source in self._domain_roots.values()
        ):
            raise ValueError("Package snapshot authority overlaps source state")
        domains = tuple(PACKAGE_PRE_B_SNAPSHOT_DOMAINS)
        if any(
            _paths_overlap(self._domain_roots[left], self._domain_roots[right])
            and not self._shared_selected_source(left, right)
            for index, left in enumerate(domains)
            for right in domains[index + 1 :]
        ):
            raise ValueError("Package snapshot domain roots overlap")
        snapshot = _open_private_root(
            self._snapshot_root, expected_identities=self._snapshot_identities
        )
        try:
            identities = {}
            with ExitStack() as opened:
                sources: list[tuple[str, _PinnedWindowsRoot]] = []
                for domain, path in self._domain_roots.items():
                    source = _open_private_root(path)
                    opened.callback(source.close)
                    if _pinned_roots_overlap(source, snapshot) or any(
                        _pinned_roots_overlap(source, prior)
                        and not self._shared_selected_source(domain, prior_domain)
                        for prior_domain, prior in sources
                    ):
                        raise ValueError("Package snapshot domain roots overlap")
                    identities[domain] = source.identities
                    sources.append((domain, source))
            self._domain_identities = identities
        finally:
            snapshot.close()

    def _shared_selected_source(self, left: str, right: str) -> bool:
        return (
            self._domain_roots[left] == self._domain_roots[right]
            and self._domain_members[left] is not None
            and self._domain_members[right] is not None
        )

    def _selected_names(self, domain: str) -> frozenset[str] | None:
        members = self._domain_members[domain]
        return None if members is None else frozenset(members)

    def _require_member_coverage(
        self, sources: Mapping[str, _PinnedWindowsRoot]
    ) -> None:
        grouped: dict[Path, list[str]] = {}
        for domain, path in self._domain_roots.items():
            grouped.setdefault(path, []).append(domain)
        for _path, domains in grouped.items():
            if len(domains) == 1 and self._domain_members[domains[0]] is None:
                continue
            by_name: dict[str, list[str]] = {}
            for domain in domains:
                for name in self._domain_members[domain] or ():
                    by_name.setdefault(name, []).append(domain)
            duplicates = {
                (self._domain_roots[domains[0]], name): tuple(sorted(owners))
                for name, owners in by_name.items()
                if len(owners) > 1
            }
            expected_aliases = {
                key: owners
                for key, owners in self._shared_aliases.items()
                if key[0] == self._domain_roots[domains[0]]
            }
            observed = set(windows_listdir_at(sources[domains[0]].descriptor))
            if duplicates != expected_aliases or set(by_name) != observed:
                raise ValueError(
                    "Package snapshot source member coverage is incomplete"
                )

    def _require_shared_member_inspections(
        self, inspections: Mapping[str, _TreeInspection]
    ) -> None:
        for alias in self._shared_members:
            observed = [
                tuple(
                    entry
                    for entry in inspections[domain].entries
                    if entry.logical_path == alias.member_name
                    or entry.logical_path.startswith(alias.member_name + "/")
                )
                for domain in alias.domains
            ]
            if not observed[0] or any(value != observed[0] for value in observed[1:]):
                raise OSError("Package snapshot shared member changed")

    def capture(
        self,
        *,
        store_id: str,
        legacy_root_identity: str,
        quiescence_receipt_id: str,
    ) -> PackageEpochCutoverSnapshotReceiptV1:
        if store_id != self._store_id:
            raise ValueError("Package snapshot store changed")
        _prepare_private_snapshot_lock(
            self._snapshot_root, expected_identities=self._snapshot_identities
        )
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
        with WindowsPrivateDirectoryAcl() as acl:
            return self._capture_private(
                legacy_root_identity=legacy_root_identity,
                quiescence_receipt_id=quiescence_receipt_id,
                security_descriptor=acl.security_descriptor,
            )

    def _capture_private(
        self,
        *,
        legacy_root_identity: str,
        quiescence_receipt_id: str,
        security_descriptor: int,
    ) -> PackageEpochCutoverSnapshotReceiptV1:
        snapshot = _open_private_root(
            self._snapshot_root, expected_identities=self._snapshot_identities
        )
        sources: dict[str, _PinnedWindowsRoot] = {}
        stage_name = "staging-" + secrets.token_hex(16)
        stage_identity = None
        published = False
        try:
            for domain, path in self._domain_roots.items():
                sources[domain] = _open_private_root(
                    path, expected_identities=self._domain_identities[domain]
                )
            self._require_member_coverage(sources)
            if (
                _directory_identity(sources["store_bytes"].descriptor)
                != legacy_root_identity
            ):
                raise ValueError("Package snapshot legacy root changed")
            inspections = {
                domain: _inspect_tree(
                    source.descriptor,
                    maximum_entries=self._maximum_entries,
                    maximum_bytes=self._maximum_bytes,
                    maximum_depth=self._maximum_depth - 1,
                    top_level_names=self._selected_names(domain),
                    skip_top_level_names=(
                        _FENCE_TRANSIENT_NAMES
                        if domain == "fence_record"
                        else frozenset()
                    ),
                )
                for domain, source in sources.items()
            }
            self._require_shared_member_inspections(inspections)
            pointer_contents = None
            if self._legacy_root_pointer_name is not None:
                if inspections["legacy_root_pointer"].entries:
                    raise ValueError("Package snapshot pointer source must be empty")
                pointer_contents = canonical_json_bytes(
                    {
                        "legacyRootIdentity": legacy_root_identity,
                        "legacyRootName": self._legacy_root_pointer_name,
                        "recordVersion": 1,
                        "storeId": self._store_id,
                    }
                )
            stage_fd = _open_directory_at(
                snapshot.descriptor,
                stage_name,
                create_new=True,
                security_descriptor=security_descriptor,
            )
            stage_identity = _native_identity(os.fstat(stage_fd))
            try:
                payload_fd = _open_directory_at(
                    stage_fd,
                    _PAYLOAD_NAME,
                    create_new=True,
                    security_descriptor=security_descriptor,
                )
                try:
                    for domain in PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
                        source = sources[domain]
                        target_fd = _open_directory_at(
                            payload_fd,
                            domain,
                            create_new=True,
                            security_descriptor=security_descriptor,
                        )
                        try:
                            _copy_tree(
                                source.descriptor,
                                target_fd,
                                inspections[domain],
                                security_descriptor=security_descriptor,
                            )
                            expected_entries = inspections[domain].entries
                            if (
                                domain == "legacy_root_pointer"
                                and pointer_contents is not None
                            ):
                                _write_new_file(
                                    target_fd,
                                    _LEGACY_ROOT_POINTER_NAME,
                                    pointer_contents,
                                    security_descriptor=security_descriptor,
                                )
                            copied_domain = _inspect_tree(
                                target_fd,
                                maximum_entries=self._maximum_entries,
                                maximum_bytes=self._maximum_bytes,
                                maximum_depth=self._maximum_depth - 1,
                            )
                            if (
                                domain == "legacy_root_pointer"
                                and pointer_contents is not None
                            ):
                                if len(copied_domain.entries) != 1 or (
                                    copied_domain.entries[0].logical_path
                                    != _LEGACY_ROOT_POINTER_NAME
                                    or copied_domain.entries[0].kind != "file"
                                    or copied_domain.entries[0].content_digest
                                    != sha256(pointer_contents).hexdigest()
                                    or copied_domain.entries[0].byte_count
                                    != len(pointer_contents)
                                ):
                                    raise OSError("Package snapshot pointer changed")
                            elif copied_domain.entries != expected_entries:
                                raise OSError(
                                    "Package snapshot domain changed during copy"
                                )
                            _flush_tree(target_fd, copied_domain.entries)
                            windows_flush_directory(target_fd)
                        finally:
                            os.close(target_fd)
                    copied = _inspect_tree(
                        payload_fd,
                        maximum_entries=self._maximum_entries,
                        maximum_bytes=self._maximum_bytes,
                        maximum_depth=self._maximum_depth,
                    )
                    _require_domains(payload_fd)
                    self._require_member_coverage(sources)
                    for domain, source in sources.items():
                        source.assert_visible()
                        after = _inspect_tree(
                            source.descriptor,
                            maximum_entries=self._maximum_entries,
                            maximum_bytes=self._maximum_bytes,
                            maximum_depth=self._maximum_depth - 1,
                            top_level_names=self._selected_names(domain),
                            skip_top_level_names=(
                                _FENCE_TRANSIENT_NAMES
                                if domain == "fence_record"
                                else frozenset()
                            ),
                        )
                        if after.entries != inspections[domain].entries:
                            raise OSError("Package snapshot source changed during copy")
                    snapshot_id = sha256(
                        canonical_json_bytes(
                            {
                                "domain": "loushang.package-windows-epoch-snapshot/v1",
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
                        "manifestVersion": PACKAGE_WINDOWS_OFFLINE_RESTORE_STATE_MANIFEST_VERSION,
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
                    _write_new_file(
                        stage_fd,
                        _STATE_MANIFEST_NAME,
                        manifest_bytes,
                        security_descriptor=security_descriptor,
                    )
                    _flush_tree(payload_fd, copied.entries)
                    windows_flush_directory(payload_fd)
                finally:
                    os.close(payload_fd)
                windows_flush_directory(stage_fd)
            finally:
                os.close(stage_fd)
            snapshot.assert_visible()
            if _entry_exists(snapshot.descriptor, receipt.snapshot_id):
                self._verify_and_index(
                    snapshot, evidence, security_descriptor=security_descriptor
                )
                return receipt
            windows_rename_at(snapshot.descriptor, stage_name, receipt.snapshot_id)
            published = True
            windows_flush_directory(snapshot.descriptor)
            self._verify_and_index(
                snapshot, evidence, security_descriptor=security_descriptor
            )
            return receipt
        finally:
            try:
                if stage_identity is not None and not published:
                    _remove_owned_namespace(
                        snapshot.descriptor,
                        stage_name,
                        expected_identity=stage_identity,
                    )
                    windows_flush_directory(snapshot.descriptor)
            finally:
                for source in sources.values():
                    source.close()
                snapshot.close()

    def _verify_and_index(
        self,
        root: _PinnedWindowsRoot,
        evidence: PackageOfflineRestoreSnapshotEvidenceV1,
        *,
        security_descriptor: int,
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
            observed, _ = _read_regular_file(
                root.descriptor, name, maximum_bytes=_MAX_EVIDENCE_BYTES
            )
            if observed != expected:
                raise ValueError("Package snapshot evidence index changed")
        else:
            temporary = "index-staging-" + secrets.token_hex(16)
            _write_new_file(
                root.descriptor,
                temporary,
                expected,
                security_descriptor=security_descriptor,
            )
            try:
                windows_flush_directory(root.descriptor)
                windows_rename_at(root.descriptor, temporary, name)
            finally:
                if _entry_exists(root.descriptor, temporary):
                    windows_unlink_at(root.descriptor, temporary)
        windows_flush_directory(root.descriptor)
        root.assert_visible()


def _require_domains(payload_fd: int) -> None:
    names = set(windows_listdir_at(payload_fd))
    if names != set(PACKAGE_PRE_B_SNAPSHOT_DOMAINS):
        raise OSError("Package snapshot domain coverage changed")
    for domain in PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
        descriptor = _open_directory_at(payload_fd, domain)
        os.close(descriptor)


def _open_private_root(
    path: Path,
    *,
    expected_identities: tuple[tuple[int, int], ...] | None = None,
) -> _PinnedWindowsRoot:
    root = _PinnedWindowsRoot.open(
        path, expected_identities=expected_identities, read_control=True
    )
    try:
        with WindowsPrivateDirectoryAcl() as acl:
            acl.validate(root.descriptor)
        return root
    except BaseException:
        root.close()
        raise


def _prepare_private_snapshot_lock(
    path: Path,
    *,
    expected_identities: tuple[tuple[int, int], ...],
) -> None:
    root = _open_private_root(path, expected_identities=expected_identities)
    try:
        with WindowsPrivateDirectoryAcl() as acl:
            created = False
            try:
                descriptor = open_windows_regular_file_at(
                    root.descriptor,
                    _LOCK_NAME,
                    create_new=True,
                    write=True,
                    security_descriptor=acl.security_descriptor,
                    read_control=True,
                )
                created = True
            except FileExistsError:
                descriptor = open_windows_regular_file_at(
                    root.descriptor,
                    _LOCK_NAME,
                    create_new=False,
                    write=True,
                    read_control=True,
                )
            try:
                acl.validate(descriptor)
                if created:
                    windows_flush_file(descriptor)
                    windows_flush_directory(root.descriptor)
            finally:
                os.close(descriptor)
        root.assert_visible()
    finally:
        root.close()


__all__ = [
    "PackageWindowsEpochSnapshotEvidenceStore",
    "PackageWindowsEpochSnapshotOwner",
    "PackageWindowsSnapshotSharedMemberV1",
]
