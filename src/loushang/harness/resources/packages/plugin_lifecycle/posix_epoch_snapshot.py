"""Rooted pre-B snapshots shared by POSIX cutover and offline restore.

The Product supplies one private source for each required pre-B domain.
Whole-tree sources must be disjoint. Explicit top-level member selections may
share one directory only when their union covers it exactly; Product policy
still decides which state belongs to each domain. An optional Product-declared
legacy root name yields one pointer record from the verified Store identity.
"""

from __future__ import annotations

import os
import secrets
import stat
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import journal_file_lock
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PACKAGE_PRE_B_SNAPSHOT_DOMAINS,
    PackageOfflineRestoreError,
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
    _revalidate_source,
    _strict_json_object,
    _supports_posix_rooted_io,
    _TreeEntry,
    _TreeInspection,
    _validate_entry_name,
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
_LEGACY_ROOT_POINTER_NAME = "legacy-root-pointer.json"
_MAX_EVIDENCE_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class PackagePosixSnapshotSharedMemberV1:
    """Product-declared one physical member serving multiple logical domains."""

    source_root: Path
    member_name: str
    domains: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source_root, Path) or type(self.member_name) is not str:
            raise TypeError("Package snapshot shared member is invalid")
        _validated_root_path(self.source_root, name="shared source")
        try:
            _validate_entry_name(self.member_name)
        except (OSError, UnicodeError) as exc:
            raise ValueError("Package snapshot shared member is invalid") from exc
        if (
            len(self.domains) < 2
            or self.domains != tuple(sorted(set(self.domains)))
            or not set(self.domains) <= set(PACKAGE_PRE_B_SNAPSHOT_DOMAINS)
        ):
            raise ValueError("Package snapshot shared member domains are invalid")


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

    def read_regular_member(
        self,
        snapshot_receipt_id: str,
        *,
        domain: str,
        member_name: str,
        maximum_bytes: int = 2 * 1024 * 1024,
    ) -> bytes | None:
        """Read one bounded member only from a fully verified immutable snapshot."""

        if domain not in PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
            raise ValueError("Package snapshot domain is invalid")
        if type(member_name) is not str:
            raise TypeError("Package snapshot member name is invalid")
        _validate_entry_name(member_name)
        limit = min(
            _validated_limit(maximum_bytes, name="maximum snapshot member bytes"),
            self._maximum_bytes,
        )
        evidence = self.snapshot(snapshot_receipt_id)
        if evidence is None:
            return None
        root = _PinnedRoot.open(
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
        except PackageOfflineRestoreError:
            raise
        except (OSError, UnicodeError, ValueError) as exc:
            raise PackageOfflineRestoreError(
                "Authenticated Package snapshot member changed",
                code="package_offline_restore_snapshot_invalid",
                evidence_ref=evidence.evidence_id,
            ) from exc
        finally:
            root.close()

    def list_domain_members(
        self, snapshot_receipt_id: str, *, domain: str
    ) -> tuple[str, ...] | None:
        """List immediate members only after verifying the whole immutable tree."""

        if domain not in PACKAGE_PRE_B_SNAPSHOT_DOMAINS:
            raise ValueError("Package snapshot domain is invalid")
        evidence = self.snapshot(snapshot_receipt_id)
        if evidence is None:
            return None
        root = _PinnedRoot.open(
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


class PackagePosixEpochSnapshotOwner(PackagePosixEpochSnapshotEvidenceStore):
    """Publish a complete, immutable, restore-compatible pre-B snapshot."""

    def __init__(
        self,
        snapshot_authority_root: str | Path,
        *,
        store_id: str,
        domain_roots: Mapping[str, str | Path],
        domain_members: Mapping[str, tuple[str, ...] | None] | None = None,
        shared_members: tuple[PackagePosixSnapshotSharedMemberV1, ...] = (),
        legacy_root_pointer_name: str | None = None,
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
        if legacy_root_pointer_name is not None:
            if type(legacy_root_pointer_name) is not str:
                raise TypeError("Package snapshot legacy root name is invalid")
            try:
                _validate_entry_name(legacy_root_pointer_name)
            except (OSError, UnicodeError) as exc:
                raise ValueError(
                    "Package snapshot legacy root name is invalid"
                ) from exc
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
                try:
                    for name in members:
                        _validate_entry_name(name)
                except (OSError, UnicodeError) as exc:
                    raise ValueError(
                        "Package snapshot domain members are invalid"
                    ) from exc
            self._domain_members[domain] = members
        if type(shared_members) is not tuple:
            raise TypeError("Package snapshot shared members must be a tuple")
        self._shared_members = shared_members
        self._shared_aliases: dict[tuple[Path, str], tuple[str, ...]] = {}
        for alias in shared_members:
            if not isinstance(alias, PackagePosixSnapshotSharedMemberV1):
                raise TypeError("Package snapshot shared member is invalid")
            key = alias.source_root, alias.member_name
            selected = (self._domain_members[domain] for domain in alias.domains)
            if key in self._shared_aliases or any(
                self._domain_roots[domain] != alias.source_root
                or members is None
                or alias.member_name not in members
                for domain, members in zip(alias.domains, selected, strict=True)
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
        snapshot = _PinnedRoot.open(
            self._snapshot_root, expected_identities=self._snapshot_identities
        )
        try:
            domain_identities = {}
            with ExitStack() as opened:
                sources: list[tuple[str, _PinnedRoot]] = []
                for domain, path in self._domain_roots.items():
                    source = _PinnedRoot.open(path)
                    opened.callback(source.close)
                    if _pinned_roots_overlap(source, snapshot):
                        raise ValueError("Package snapshot source overlaps authority")
                    if any(
                        _pinned_roots_overlap(source, prior)
                        and not self._shared_selected_source(domain, prior_domain)
                        for prior_domain, prior in sources
                    ):
                        raise ValueError("Package snapshot domain roots overlap")
                    domain_identities[domain] = source.identities
                    sources.append((domain, source))
            self._domain_identities = domain_identities
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

    def _require_member_coverage(self, sources: Mapping[str, _PinnedRoot]) -> None:
        grouped: dict[Path, list[str]] = {}
        for domain, path in self._domain_roots.items():
            grouped.setdefault(path, []).append(domain)
        for path, domains in grouped.items():
            if len(domains) == 1 and self._domain_members[domains[0]] is None:
                continue
            by_name: dict[str, list[str]] = {}
            for domain in domains:
                for name in self._domain_members[domain] or ():
                    by_name.setdefault(name, []).append(domain)
            duplicates = {
                (path, name): tuple(sorted(owners))
                for name, owners in by_name.items()
                if len(owners) > 1
            }
            expected_aliases = {
                key: owners
                for key, owners in self._shared_aliases.items()
                if key[0] == path
            }
            observed = set(os.listdir(sources[domains[0]].descriptor))
            if duplicates != expected_aliases or set(by_name) != observed:
                raise ValueError(
                    "Package snapshot source member coverage is incomplete"
                )

    def _require_shared_member_inspections(
        self, inspections: Mapping[str, _TreeInspection]
    ) -> None:
        for alias in self._shared_members:
            observed = []
            for domain in alias.domains:
                observed.append(
                    tuple(
                        entry
                        for entry in inspections[domain].entries
                        if entry.logical_path == alias.member_name
                        or entry.logical_path.startswith(alias.member_name + "/")
                    )
                )
            if not observed[0] or any(item != observed[0] for item in observed[1:]):
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
                            expected_entries = inspections[domain].entries
                            if (
                                domain == "legacy_root_pointer"
                                and pointer_contents is not None
                            ):
                                _write_new_file(
                                    target_fd,
                                    _LEGACY_ROOT_POINTER_NAME,
                                    pointer_contents,
                                )
                                expected_entries = (
                                    _TreeEntry(
                                        logical_path=_LEGACY_ROOT_POINTER_NAME,
                                        kind="file",
                                        mode=0o600,
                                        content_digest=sha256(
                                            pointer_contents
                                        ).hexdigest(),
                                        byte_count=len(pointer_contents),
                                    ),
                                )
                            copied_domain = _inspect_tree(
                                target_fd,
                                maximum_entries=self._maximum_entries,
                                maximum_bytes=self._maximum_bytes,
                                maximum_depth=self._maximum_depth - 1,
                            )
                            if copied_domain.entries != expected_entries:
                                raise OSError(
                                    "Package snapshot domain changed during copy"
                                )
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
                    self._require_member_coverage(sources)
                    for domain, source in sources.items():
                        source.assert_visible()
                        after = _inspect_tree(
                            source.descriptor,
                            maximum_entries=self._maximum_entries,
                            maximum_bytes=self._maximum_bytes,
                            maximum_depth=self._maximum_depth - 1,
                            top_level_names=self._selected_names(domain),
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
    "PackagePosixSnapshotSharedMemberV1",
]
