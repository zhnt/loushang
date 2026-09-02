"""POSIX-native rooted Store materialization for PLC9B3e-3c1.

The Store path is configuration held only by the role-specific Store owner.
Every operation pins the complete visible ancestor chain, writes through
descriptor-relative no-follow calls, and returns only an existing typed ref.
"""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager, suppress
from hashlib import sha256
from pathlib import Path
from typing import Literal, cast

from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    PluginRevisionRefV1,
    VerifiedArtifactRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackageArtifactStagingReceiptV1,
    PackageArtifactStagingRequestV1,
    PackagePluginRootTargetV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementJournal,
    PackageStoreSettlementJournalError,
)
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackagePhysicalStagingError,
    PackageVerifiedTreeEntryV1,
    PackageVerifiedTreeManifestV1,
    PackageVerifiedTreeSinkPort,
    PackageVerifiedTreeTransferOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    VerifiedWheelCandidate,
)

_Role = Literal["dependency", "root"]
_Identity = tuple[int, int]


class PosixPackageDependencyMaterializationStore:
    """Dependency-only adapter over one configured immutable Store root."""

    def __init__(
        self,
        root: str | Path,
        *,
        store_identity: str,
        settlement_journal: PackageStoreSettlementJournal,
        transfer: PackageVerifiedTreeTransferOwner | None = None,
        commit_probe: Callable[[], None] | None = None,
        receipt_probe: Callable[[], None] | None = None,
    ) -> None:
        self._store = _PosixRoleStore(
            root,
            role="dependency",
            store_identity=store_identity,
            settlement_journal=settlement_journal,
            transfer=transfer,
            commit_probe=commit_probe,
            receipt_probe=receipt_probe,
        )

    def open_dependency_sink(
        self,
        request: PackageArtifactStagingRequestV1,
        manifest: PackageVerifiedTreeManifestV1,
    ) -> AbstractContextManager[PackageVerifiedTreeSinkPort]:
        return self._store.open_sink(request, manifest)

    def stage_dependency(
        self,
        request: PackageArtifactStagingRequestV1,
        candidate: VerifiedWheelCandidate,
    ) -> PackageArtifactStagingReceiptV1:
        return self._store.stage(request, candidate)

    def validate_dependency_receipt(
        self,
        receipt: PackageArtifactStagingReceiptV1,
    ) -> PackageArtifactStagingReceiptV1:
        return self._store.validate_receipt(receipt)


class PosixPackagePluginRootMaterializationStore:
    """Designated-Plugin-root adapter over one configured revision Store root."""

    def __init__(
        self,
        root: str | Path,
        *,
        store_identity: str,
        package_store_id: str | None = None,
        settlement_journal: PackageStoreSettlementJournal,
        transfer: PackageVerifiedTreeTransferOwner | None = None,
        commit_probe: Callable[[], None] | None = None,
        receipt_probe: Callable[[], None] | None = None,
    ) -> None:
        self._store = _PosixRoleStore(
            root,
            role="root",
            store_identity=store_identity,
            settlement_journal=settlement_journal,
            transfer=transfer,
            commit_probe=commit_probe,
            receipt_probe=receipt_probe,
        )
        if package_store_id is not None and not package_store_id:
            raise ValueError("Package store identity is required")
        self._package_store_id = package_store_id

    def open_root_sink(
        self,
        request: PackageArtifactStagingRequestV1,
        manifest: PackageVerifiedTreeManifestV1,
    ) -> AbstractContextManager[PackageVerifiedTreeSinkPort]:
        return self._store.open_sink(request, manifest)

    def stage_root(
        self,
        request: PackageArtifactStagingRequestV1,
        candidate: VerifiedWheelCandidate,
    ) -> PackageArtifactStagingReceiptV1:
        return self._store.stage(request, candidate)

    def validate_root_receipt(
        self,
        receipt: PackageArtifactStagingReceiptV1,
    ) -> PackageArtifactStagingReceiptV1:
        return self._store.validate_receipt(receipt)

    def authorize_adoption(
        self,
        *,
        store_id: str,
        current_root_identity: str,
        target: PackagePluginRootTargetV1,
    ) -> bool:
        """Prove that an adoption request names this exact configured root."""

        if (
            self._package_store_id is None
            or store_id != self._package_store_id
            or not isinstance(target, PackagePluginRootTargetV1)
        ):
            return False
        return self._store.authorizes_root_identity(current_root_identity)


class _PosixRoleStore:
    def __init__(
        self,
        root: str | Path,
        *,
        role: _Role,
        store_identity: str,
        settlement_journal: PackageStoreSettlementJournal,
        transfer: PackageVerifiedTreeTransferOwner | None,
        commit_probe: Callable[[], None] | None,
        receipt_probe: Callable[[], None] | None,
    ) -> None:
        if os.name != "posix" or not _supports_posix_rooted_io():
            raise PackagePhysicalStagingError(
                "POSIX rooted Store operations are unavailable",
                code="package_publication_root_untrusted",
            )
        if not isinstance(root, (str, Path)):
            raise TypeError("Package Store root must be a filesystem path")
        if not isinstance(store_identity, str) or not store_identity:
            raise TypeError("Package Store identity is required")
        if not isinstance(settlement_journal, PackageStoreSettlementJournal):
            raise TypeError("Package Store settlement journal is required")
        if transfer is not None and not isinstance(
            transfer, PackageVerifiedTreeTransferOwner
        ):
            raise TypeError("Verified-tree transfer owner is required")
        if commit_probe is not None and not callable(commit_probe):
            raise TypeError("Package Store commit probe must be callable")
        if receipt_probe is not None and not callable(receipt_probe):
            raise TypeError("Package Store receipt probe must be callable")
        raw_root = Path(root)
        if not raw_root.is_absolute() or ".." in raw_root.parts:
            raise PackagePhysicalStagingError(
                "Package Store root must be an absolute normalized path",
                code="package_publication_root_untrusted",
            )
        self._root = raw_root
        if self._root == Path(self._root.anchor):
            raise PackagePhysicalStagingError(
                "Filesystem root cannot be a Package Store root",
                code="package_publication_root_untrusted",
            )
        self._role = role
        self._store_identity = store_identity
        self._settlement_journal = settlement_journal
        self._transfer = transfer or PackageVerifiedTreeTransferOwner()
        self._commit_probe = commit_probe
        self._receipt_probe = receipt_probe
        self._lock = threading.RLock()
        provisioned = _PinnedPosixRoot.open(self._root)
        try:
            self._root_identities = provisioned.identities
        finally:
            provisioned.close()
        try:
            self._settlement_journal.validate_store_root(
                store_role=self._role,
                store_identity=self._store_identity,
                root_identities=self._root_identities,
            )
        except PackageStoreSettlementJournalError:
            raise _root_untrusted() from None

    def stage(
        self,
        request: PackageArtifactStagingRequestV1,
        candidate: VerifiedWheelCandidate,
    ) -> PackageArtifactStagingReceiptV1:
        if not isinstance(candidate, VerifiedWheelCandidate):
            raise TypeError("Verified Wheel candidate is required")
        with self.open_sink(request, candidate.transfer_manifest) as sink:
            return self._transfer.transfer(request, candidate, sink)

    def validate_receipt(
        self,
        receipt: PackageArtifactStagingReceiptV1,
    ) -> PackageArtifactStagingReceiptV1:
        if not isinstance(receipt, PackageArtifactStagingReceiptV1):
            raise TypeError("Package artifact staging receipt is required")
        self._lock.acquire()
        durable_owner_lock = self._settlement_journal.owner_lock()
        try:
            durable_owner_lock.__enter__()
        except Exception:
            self._lock.release()
            raise _root_untrusted() from None
        try:
            root = _PinnedPosixRoot.open(
                self._root,
                expected_identities=self._root_identities,
            )
            try:
                return self._validate_receipt_at_root(root, receipt)
            finally:
                root.close()
        except PackagePhysicalStagingError:
            raise
        except PackageStoreSettlementJournalError:
            raise _root_untrusted() from None
        except Exception:
            raise _root_untrusted() from None
        finally:
            try:
                durable_owner_lock.__exit__(None, None, None)
            finally:
                self._lock.release()

    def authorizes_root_identity(self, expected_identity: str) -> bool:
        if self._role != "root" or not isinstance(expected_identity, str):
            return False
        self._lock.acquire()
        try:
            root = _PinnedPosixRoot.open(
                self._root,
                expected_identities=self._root_identities,
            )
            try:
                metadata = os.fstat(root.descriptor)
                observed = sha256(
                    canonical_json_bytes(
                        {
                            "device": metadata.st_dev,
                            "fileType": "directory",
                            "inode": metadata.st_ino,
                            "identityVersion": 1,
                        }
                    )
                ).hexdigest()
                return observed == expected_identity
            finally:
                root.close()
        except Exception:
            return False
        finally:
            self._lock.release()

    def _validate_receipt_at_root(
        self,
        root: _PinnedPosixRoot,
        receipt: PackageArtifactStagingReceiptV1,
    ) -> PackageArtifactStagingReceiptV1:
        stable_ref = receipt.stable_ref
        if (
            stable_ref.store_identity != self._store_identity
            or (self._role == "dependency" and not isinstance(stable_ref, VerifiedArtifactRefV1))
            or (self._role == "root" and not isinstance(stable_ref, PluginRevisionRefV1))
        ):
            raise _collision()
        settlements = self._settlement_journal.settlements_for_receipt(
            store_role=self._role,
            store_identity=self._store_identity,
            root_identities=root.identities,
            receipt=receipt,
        )
        if not settlements:
            raise _collision()
        authority = settlements[0]
        tree_identity, directory_identities, file_identities = _validate_existing_tree(
            root,
            authority.final_name,
            authority.manifest,
        )
        if not self._settlement_journal.authorizes(
            store_role=self._role,
            store_identity=self._store_identity,
            root_identities=root.identities,
            tree_identity=tree_identity,
            directory_identities=directory_identities,
            file_identities=file_identities,
            final_name=authority.final_name,
            staging_name=authority.staging_name,
            manifest=authority.manifest,
            receipt=receipt,
        ):
            raise _collision()
        return receipt

    def open_sink(
        self,
        request: PackageArtifactStagingRequestV1,
        manifest: PackageVerifiedTreeManifestV1,
    ) -> _PosixVerifiedTreeSink:
        _validate_role_request(self._role, request, manifest)
        self._lock.acquire()
        durable_owner_lock = self._settlement_journal.owner_lock()
        try:
            durable_owner_lock.__enter__()
        except Exception:
            self._lock.release()
            raise _root_untrusted() from None

        def release_owner_lock() -> None:
            try:
                durable_owner_lock.__exit__(None, None, None)
            finally:
                self._lock.release()

        try:
            root = _PinnedPosixRoot.open(
                self._root,
                expected_identities=self._root_identities,
            )
            try:
                return _PosixVerifiedTreeSink(
                    root=root,
                    role=self._role,
                    store_identity=self._store_identity,
                    request=request,
                    manifest=manifest,
                    commit_probe=self._commit_probe,
                    receipt_probe=self._receipt_probe,
                    settlement_journal=self._settlement_journal,
                    release_owner_lock=release_owner_lock,
                )
            except Exception:
                root.close()
                raise
        except Exception:
            release_owner_lock()
            raise


class _PinnedPosixRoot:
    def __init__(
        self,
        *,
        path: Path,
        components: tuple[str, ...],
        descriptors: list[int],
        identities: tuple[_Identity, ...],
    ) -> None:
        self.path = path
        self.components = components
        self._descriptors = descriptors
        self.identities = identities
        self._closed = False

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        expected_identities: tuple[_Identity, ...] | None = None,
    ) -> _PinnedPosixRoot:
        components = path.parts[1:]
        descriptors: list[int] = []
        try:
            current = _open_directory("/")
            descriptors.append(current)
            for component in components:
                current = _open_directory(component, dir_fd=current)
                descriptors.append(current)
            identities = tuple(_identity(os.fstat(fd)) for fd in descriptors)
            if expected_identities is not None and identities != expected_identities:
                raise OSError("Configured Package Store root identity changed")
            metadata = os.fstat(descriptors[-1])
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) & 0o077
                or metadata.st_uid != os.geteuid()
            ):
                raise OSError("Package Store root must be a private directory")
            pinned = cls(
                path=path,
                components=components,
                descriptors=descriptors,
                identities=identities,
            )
            pinned.validate_visible()
            return pinned
        except Exception:
            for descriptor in reversed(descriptors):
                with suppress(OSError):
                    os.close(descriptor)
            raise _root_untrusted() from None

    @property
    def descriptor(self) -> int:
        if self._closed:
            raise RuntimeError("Package Store root handle is closed")
        return self._descriptors[-1]

    def validate_visible(self) -> None:
        if self._closed:
            raise OSError("Package Store root handle is closed")
        for descriptor, expected in zip(
            self._descriptors, self.identities, strict=True
        ):
            if _identity(os.fstat(descriptor)) != expected:
                raise OSError("Pinned Package Store ancestor identity changed")
        root_metadata = os.fstat(self._descriptors[-1])
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or stat.S_IMODE(root_metadata.st_mode) & 0o077
            or root_metadata.st_uid != os.geteuid()
        ):
            raise OSError("Pinned Package Store root permissions changed")
        visible = _open_directory("/")
        try:
            if _identity(os.fstat(visible)) != self.identities[0]:
                raise OSError("Package Store filesystem root identity changed")
            for component, expected in zip(
                self.components,
                self.identities[1:],
                strict=True,
            ):
                child = _open_directory(component, dir_fd=visible)
                os.close(visible)
                visible = child
                if _identity(os.fstat(visible)) != expected:
                    raise OSError("Package Store ancestor path identity changed")
        finally:
            os.close(visible)

    def close(self) -> None:
        if self._closed:
            return
        for descriptor in reversed(self._descriptors):
            with suppress(OSError):
                os.close(descriptor)
        self._descriptors.clear()
        self._closed = True


class _PosixVerifiedTreeSink:
    def __init__(
        self,
        *,
        root: _PinnedPosixRoot,
        role: _Role,
        store_identity: str,
        request: PackageArtifactStagingRequestV1,
        manifest: PackageVerifiedTreeManifestV1,
        commit_probe: Callable[[], None] | None,
        receipt_probe: Callable[[], None] | None,
        settlement_journal: PackageStoreSettlementJournal,
        release_owner_lock: Callable[[], None],
    ) -> None:
        self._root = root
        self._role = role
        self._request = request
        self._manifest = manifest
        self._commit_probe = commit_probe
        self._receipt_probe = receipt_probe
        self._settlement_journal = settlement_journal
        self._release_owner_lock = release_owner_lock
        self._store_identity = store_identity
        self._stable_ref = _stable_ref(
            role,
            store_identity=store_identity,
            request=request,
            manifest=manifest,
        )
        prefix = "artifact" if role == "dependency" else "revision"
        self._final_name = f"{prefix}-{self._stable_ref.ref_id}"
        self._staging_name = f"staging-{request.staging_request_id}"
        self._receipt = PackageArtifactStagingReceiptV1.create(
            self._request,
            stable_ref=self._stable_ref,
        )
        self._staging_fd: int | None = None
        self._staging_identity: _Identity | None = None
        self._directory_identities: dict[tuple[str, ...], _Identity] = {}
        self._file_identities: dict[tuple[str, ...], _Identity] = {}
        self._next_entry = 0
        self._active_file: _PosixFileSink | _ReuseFileSink | None = None
        self._reuse = False
        self._authorized = False
        self._renamed = False
        self._finished = False
        self._closed = False
        self._prepare()

    def __enter__(self) -> _PosixVerifiedTreeSink:
        if self._closed:
            raise RuntimeError("Package verified-tree sink is closed")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is not None or not self._finished:
            self.abort()

    def _prepare(self) -> None:
        try:
            self._root.validate_visible()
            if _entry_exists(self._root.descriptor, self._staging_name):
                raise _root_untrusted()
            if _entry_exists(self._root.descriptor, self._final_name):
                tree_identity, directory_identities, file_identities = (
                    _validate_existing_tree(
                        self._root,
                        self._final_name,
                        self._manifest,
                    )
                )
                if not self._settlement_journal.authorizes(
                    store_role=self._role,
                    store_identity=self._store_identity,
                    root_identities=self._root.identities,
                    tree_identity=tree_identity,
                    directory_identities=directory_identities,
                    file_identities=file_identities,
                    final_name=self._final_name,
                    staging_name=self._staging_name,
                    manifest=self._manifest,
                    receipt=self._receipt,
                ):
                    raise PackagePhysicalStagingError(
                        "Package Store final identity lacks durable owner evidence",
                        code="package_publication_collision",
                    )
                self._reuse = True
                return
            os.mkdir(
                self._staging_name,
                mode=0o700,
                dir_fd=self._root.descriptor,
            )
            self._staging_fd = _open_directory(
                self._staging_name,
                dir_fd=self._root.descriptor,
            )
            self._staging_identity = _identity(os.fstat(self._staging_fd))
        except PackagePhysicalStagingError:
            raise
        except PackageStoreSettlementJournalError:
            raise _root_untrusted() from None
        except Exception:
            raise _root_untrusted() from None

    def open_file(
        self,
        entry: PackageVerifiedTreeEntryV1,
    ) -> AbstractContextManager[_PosixFileSink | _ReuseFileSink]:
        self._require_open()
        if self._active_file is not None:
            raise RuntimeError("Previous Package Store file sink is still open")
        if (
            self._next_entry >= len(self._manifest.entries)
            or entry != self._manifest.entries[self._next_entry]
        ):
            raise PackagePhysicalStagingError(
                "Package Store file order changed from verified manifest",
                code="package_artifact_identity_changed",
            )
        if self._reuse:
            file_sink: _PosixFileSink | _ReuseFileSink = _ReuseFileSink(
                owner=self,
                entry=entry,
            )
        else:
            file_sink = self._create_file_sink(entry)
        self._active_file = file_sink
        return file_sink

    def _create_file_sink(self, entry: PackageVerifiedTreeEntryV1) -> _PosixFileSink:
        if self._staging_fd is None:
            raise RuntimeError("Package Store staging root is unavailable")
        parts = tuple(entry.logical_path.split("/"))
        self._ensure_directories(parts[:-1])
        parent_fd = self._open_staging_directory(parts[:-1])
        try:
            descriptor = _open_regular_file(
                parent_fd,
                parts[-1],
                create_new=True,
                write=True,
            )
        except Exception:
            os.close(parent_fd)
            raise _root_untrusted() from None
        os.close(parent_fd)
        identity = _identity(os.fstat(descriptor))
        self._file_identities[parts] = identity
        return _PosixFileSink(
            owner=self,
            entry=entry,
            descriptor=descriptor,
            identity=identity,
        )

    def _ensure_directories(self, parts: tuple[str, ...]) -> None:
        for depth in range(1, len(parts) + 1):
            current = parts[:depth]
            if current in self._directory_identities:
                continue
            parent_fd = self._open_staging_directory(current[:-1])
            try:
                os.mkdir(current[-1], mode=0o700, dir_fd=parent_fd)
                child_fd = _open_directory(current[-1], dir_fd=parent_fd)
            except Exception:
                os.close(parent_fd)
                raise _root_untrusted() from None
            os.close(parent_fd)
            try:
                self._directory_identities[current] = _identity(os.fstat(child_fd))
            finally:
                os.close(child_fd)

    def _open_staging_directory(self, parts: tuple[str, ...]) -> int:
        if self._staging_fd is None or self._staging_identity is None:
            raise RuntimeError("Package Store staging root is unavailable")
        if _identity(os.fstat(self._staging_fd)) != self._staging_identity:
            raise _root_untrusted()
        current_fd = os.dup(self._staging_fd)
        try:
            for depth, part in enumerate(parts, start=1):
                child_fd = _open_directory(part, dir_fd=current_fd)
                expected = self._directory_identities.get(parts[:depth])
                if expected is None or _identity(os.fstat(child_fd)) != expected:
                    os.close(child_fd)
                    raise OSError("Package Store staging ancestor changed")
                os.close(current_fd)
                current_fd = child_fd
            return current_fd
        except PackagePhysicalStagingError:
            os.close(current_fd)
            raise
        except Exception:
            os.close(current_fd)
            raise _root_untrusted() from None

    def _file_finished(self, sink: _PosixFileSink | _ReuseFileSink) -> None:
        if sink is not self._active_file:
            raise RuntimeError("Package Store file sink ownership changed")
        self._active_file = None
        self._next_entry += 1

    def finish(self) -> PackageArtifactStagingReceiptV1:
        self._require_open()
        if self._active_file is not None or self._next_entry != len(
            self._manifest.entries
        ):
            raise PackagePhysicalStagingError(
                "Package Store received an incomplete verified tree",
                code="package_artifact_identity_changed",
            )
        try:
            if self._reuse:
                self._root.validate_visible()
                tree_identity, directory_identities, file_identities = (
                    _validate_existing_tree(
                        self._root,
                        self._final_name,
                        self._manifest,
                    )
                )
                if not self._settlement_journal.authorizes(
                    store_role=self._role,
                    store_identity=self._store_identity,
                    root_identities=self._root.identities,
                    tree_identity=tree_identity,
                    directory_identities=directory_identities,
                    file_identities=file_identities,
                    final_name=self._final_name,
                    staging_name=self._staging_name,
                    manifest=self._manifest,
                    receipt=self._receipt,
                ):
                    raise PackagePhysicalStagingError(
                        "Package Store final identity lacks durable owner evidence",
                        code="package_publication_collision",
                    )
            else:
                self._settle_new_tree()
        except PackagePhysicalStagingError:
            raise
        except PackageStoreSettlementJournalError:
            raise _root_untrusted() from None
        except Exception:
            raise _root_untrusted() from None
        self._finished = True
        self._close_handles()
        return self._receipt

    def _settle_new_tree(self) -> None:
        if self._staging_fd is None or self._staging_identity is None:
            raise RuntimeError("Package Store staging root is unavailable")
        for parts in sorted(
            self._directory_identities,
            key=lambda value: (len(value), value),
            reverse=True,
        ):
            descriptor = self._open_staging_directory(parts)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.fsync(self._staging_fd)
        visible = _open_directory(self._staging_name, dir_fd=self._root.descriptor)
        try:
            if _identity(os.fstat(visible)) != self._staging_identity:
                raise OSError("Package Store staging path identity changed")
        finally:
            os.close(visible)
        os.close(self._staging_fd)
        self._staging_fd = None
        if self._commit_probe is not None:
            self._commit_probe()
        try:
            self._root.validate_visible()
            visible = _open_directory(
                self._staging_name,
                dir_fd=self._root.descriptor,
            )
            try:
                _validate_owned_tree(
                    visible,
                    self._staging_identity,
                    self._manifest,
                    directory_identities=self._directory_identities,
                    file_identities=self._file_identities,
                )
            finally:
                os.close(visible)
        except Exception:
            raise _root_untrusted() from None
        if _entry_exists(self._root.descriptor, self._final_name):
            raise PackagePhysicalStagingError(
                "Package Store final identity already exists",
                code="package_publication_collision",
            )
        self._settlement_journal.authorize(
            store_role=self._role,
            store_identity=self._store_identity,
            root_identities=self._root.identities,
            tree_identity=self._staging_identity,
            directory_identities=self._directory_identities,
            file_identities=self._file_identities,
            final_name=self._final_name,
            staging_name=self._staging_name,
            manifest=self._manifest,
            receipt=self._receipt,
        )
        self._authorized = True
        try:
            _rename_directory_noreplace(
                self._root.descriptor,
                self._staging_name,
                self._root.descriptor,
                self._final_name,
            )
            self._renamed = True
            os.fsync(self._root.descriptor)
            self._root.validate_visible()
            _validate_existing_tree(
                self._root,
                self._final_name,
                self._manifest,
                expected_tree_identity=self._staging_identity,
                directory_identities=self._directory_identities,
                file_identities=self._file_identities,
            )
            if self._receipt_probe is not None:
                self._receipt_probe()
        except FileExistsError:
            raise _collision() from None
        except PackagePhysicalStagingError:
            raise
        except Exception:
            raise _root_untrusted() from None

    def abort(self) -> None:
        if self._closed:
            return
        if self._active_file is not None:
            self._active_file.abort()
            self._active_file = None
        with suppress(Exception):
            if not self._reuse and not (self._renamed and self._authorized):
                name = self._final_name if self._renamed else self._staging_name
                expected = self._staging_identity
                if expected is not None:
                    self._remove_owned_tree(name, expected)
        self._close_handles()

    def _remove_owned_tree(self, name: str, expected: _Identity) -> None:
        if self._staging_fd is not None:
            os.close(self._staging_fd)
            self._staging_fd = None
        tree_fd = _open_directory(name, dir_fd=self._root.descriptor)
        try:
            if _identity(os.fstat(tree_fd)) != expected:
                raise OSError("Package Store owned tree identity changed")
            for parts in sorted(self._file_identities, reverse=True):
                parent_fd = _open_relative_directory(tree_fd, parts[:-1])
                try:
                    metadata = os.stat(
                        parts[-1],
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    if _identity(metadata) != self._file_identities[
                        parts
                    ] or not stat.S_ISREG(metadata.st_mode):
                        raise OSError("Package Store owned file identity changed")
                    os.unlink(parts[-1], dir_fd=parent_fd)
                finally:
                    os.close(parent_fd)
            for parts in sorted(
                self._directory_identities,
                key=lambda value: (len(value), value),
                reverse=True,
            ):
                parent_fd = _open_relative_directory(tree_fd, parts[:-1])
                try:
                    metadata = os.stat(
                        parts[-1],
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    if _identity(metadata) != self._directory_identities[
                        parts
                    ] or not stat.S_ISDIR(metadata.st_mode):
                        raise OSError("Package Store owned directory identity changed")
                    os.rmdir(parts[-1], dir_fd=parent_fd)
                finally:
                    os.close(parent_fd)
        finally:
            os.close(tree_fd)
        os.rmdir(name, dir_fd=self._root.descriptor)

    def _close_handles(self) -> None:
        if self._staging_fd is not None:
            with suppress(OSError):
                os.close(self._staging_fd)
            self._staging_fd = None
        self._root.close()
        self._release_owner_lock()
        self._closed = True

    def _require_open(self) -> None:
        if self._closed or self._finished:
            raise RuntimeError("Package verified-tree sink is closed")


class _PosixFileSink:
    def __init__(
        self,
        *,
        owner: _PosixVerifiedTreeSink,
        entry: PackageVerifiedTreeEntryV1,
        descriptor: int,
        identity: _Identity,
    ) -> None:
        self._owner = owner
        self._entry = entry
        self._descriptor: int | None = descriptor
        self._identity = identity
        self._digest = sha256()
        self._byte_count = 0
        self._finished = False

    def __enter__(self) -> _PosixFileSink:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is not None or not self._finished:
            self.abort()

    def write(self, chunk: bytes) -> None:
        descriptor = self._require_open()
        if not isinstance(chunk, bytes):
            raise TypeError("Package Store sink accepts only bytes")
        self._byte_count += len(chunk)
        if self._byte_count > self._entry.byte_count:
            raise PackagePhysicalStagingError(
                "Package Store file exceeds verified size",
                code="package_artifact_identity_changed",
            )
        try:
            view = memoryview(chunk)
            while view:
                written = os.write(descriptor, view)
                if written < 1:
                    raise OSError("Package Store write made no progress")
                view = view[written:]
        except OSError:
            raise _root_untrusted() from None
        self._digest.update(chunk)

    def finish(self) -> None:
        descriptor = self._require_open()
        metadata = os.fstat(descriptor)
        if (
            self._byte_count != self._entry.byte_count
            or self._digest.hexdigest() != self._entry.content_digest
            or _identity(metadata) != self._identity
            or metadata.st_nlink != 1
        ):
            raise PackagePhysicalStagingError(
                "Package Store file changed from verified manifest",
                code="package_artifact_identity_changed",
            )
        try:
            os.fsync(descriptor)
            os.close(descriptor)
        except OSError:
            raise _root_untrusted() from None
        self._descriptor = None
        self._finished = True
        self._owner._file_finished(self)

    def abort(self) -> None:
        if self._descriptor is not None:
            with suppress(OSError):
                os.close(self._descriptor)
            self._descriptor = None

    def _require_open(self) -> int:
        if self._descriptor is None or self._finished:
            raise RuntimeError("Package Store file sink is closed")
        return self._descriptor


class _ReuseFileSink:
    def __init__(
        self,
        *,
        owner: _PosixVerifiedTreeSink,
        entry: PackageVerifiedTreeEntryV1,
    ) -> None:
        self._owner = owner
        self._entry = entry
        self._digest = sha256()
        self._byte_count = 0
        self._closed = False
        self._finished = False

    def __enter__(self) -> _ReuseFileSink:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is not None or not self._finished:
            self.abort()

    def write(self, chunk: bytes) -> None:
        if self._closed:
            raise RuntimeError("Package Store reuse sink is closed")
        if not isinstance(chunk, bytes):
            raise TypeError("Package Store sink accepts only bytes")
        self._byte_count += len(chunk)
        if self._byte_count > self._entry.byte_count:
            raise PackagePhysicalStagingError(
                "Reused Package file exceeds verified size",
                code="package_artifact_identity_changed",
            )
        self._digest.update(chunk)

    def finish(self) -> None:
        if self._closed:
            raise RuntimeError("Package Store reuse sink is closed")
        if (
            self._byte_count != self._entry.byte_count
            or self._digest.hexdigest() != self._entry.content_digest
        ):
            raise PackagePhysicalStagingError(
                "Reused Package file changed from verified manifest",
                code="package_artifact_identity_changed",
            )
        self._closed = True
        self._finished = True
        self._owner._file_finished(self)

    def abort(self) -> None:
        self._closed = True


def _validate_role_request(
    role: _Role,
    request: PackageArtifactStagingRequestV1,
    manifest: PackageVerifiedTreeManifestV1,
) -> None:
    if not isinstance(request, PackageArtifactStagingRequestV1):
        raise TypeError("Package artifact staging request is required")
    if not isinstance(manifest, PackageVerifiedTreeManifestV1):
        raise TypeError("Package verified-tree manifest is required")
    node = request.plan_node
    if (
        node.role != role
        or (role == "dependency" and request.root_target is not None)
        or (role == "root" and request.root_target is None)
        or request.operation_id != manifest.operation_id
        or request.attempt_epoch != manifest.attempt_epoch
        or request.node_id != manifest.node_id
        or node.distribution != manifest.distribution
        or node.version != manifest.version
        or node.wheel_evidence_fingerprint != manifest.wheel_evidence_fingerprint
        or node.artifact_digest != manifest.artifact_digest
        or node.extraction_tree_digest != manifest.extraction_tree_digest
    ):
        raise PackagePhysicalStagingError(
            "Package Store request changed verified role or artifact identity",
            code="package_artifact_identity_changed",
        )


def _stable_ref(
    role: _Role,
    *,
    store_identity: str,
    request: PackageArtifactStagingRequestV1,
    manifest: PackageVerifiedTreeManifestV1,
) -> VerifiedArtifactRefV1 | PluginRevisionRefV1:
    values = {
        "store_identity": store_identity,
        "store_revision": f"tree:{manifest.manifest_id}",
        "distribution": manifest.distribution,
        "version": manifest.version,
        "artifact_digest": manifest.artifact_digest,
        "extraction_tree_digest": manifest.extraction_tree_digest,
    }
    if role == "dependency":
        return VerifiedArtifactRefV1.create(**values)
    target = request.root_target
    assert target is not None
    return PluginRevisionRefV1.create(
        **values,
        installation_id=target.installation_id,
        plugin_id=target.plugin_id,
    )


def _validate_existing_tree(
    root: _PinnedPosixRoot,
    final_name: str,
    manifest: PackageVerifiedTreeManifestV1,
    *,
    expected_tree_identity: _Identity | None = None,
    directory_identities: dict[tuple[str, ...], _Identity] | None = None,
    file_identities: dict[tuple[str, ...], _Identity] | None = None,
) -> tuple[
    _Identity,
    dict[tuple[str, ...], _Identity],
    dict[tuple[str, ...], _Identity],
]:
    try:
        root.validate_visible()
    except Exception:
        raise _root_untrusted() from None
    try:
        tree_fd = _open_directory(final_name, dir_fd=root.descriptor)
        try:
            tree_identity = _identity(os.fstat(tree_fd))
            if (
                expected_tree_identity is not None
                and tree_identity != expected_tree_identity
            ):
                raise OSError("Published Package tree identity changed")
            observed_directories, observed_files = _validate_tree_contents(
                tree_fd,
                manifest,
                directory_identities=directory_identities,
                file_identities=file_identities,
            )
        finally:
            os.close(tree_fd)
    except Exception:
        raise PackagePhysicalStagingError(
            "Existing Package Store object conflicts with verified identity",
            code="package_publication_collision",
        ) from None
    try:
        root.validate_visible()
    except Exception:
        raise _root_untrusted() from None
    return tree_identity, observed_directories, observed_files


def _validate_owned_tree(
    tree_fd: int,
    expected_tree_identity: _Identity,
    manifest: PackageVerifiedTreeManifestV1,
    *,
    directory_identities: dict[tuple[str, ...], _Identity],
    file_identities: dict[tuple[str, ...], _Identity],
) -> None:
    if _identity(os.fstat(tree_fd)) != expected_tree_identity:
        raise _root_untrusted()
    try:
        _validate_tree_contents(
            tree_fd,
            manifest,
            directory_identities=directory_identities,
            file_identities=file_identities,
        )
    except PackagePhysicalStagingError:
        raise
    except Exception:
        raise _root_untrusted() from None


def _validate_tree_contents(
    root_fd: int,
    manifest: PackageVerifiedTreeManifestV1,
    *,
    directory_identities: dict[tuple[str, ...], _Identity] | None,
    file_identities: dict[tuple[str, ...], _Identity] | None,
) -> tuple[
    dict[tuple[str, ...], _Identity],
    dict[tuple[str, ...], _Identity],
]:
    expected = {entry.logical_path: entry for entry in manifest.entries}
    observed, observed_directories, observed_files = _collect_tree(
        root_fd,
        expected,
        directory_identities=directory_identities,
        file_identities=file_identities,
    )
    if set(observed) != set(expected):
        raise OSError("Published Package tree members changed")
    for logical_path, entry in expected.items():
        byte_count, digest = observed[logical_path]
        if byte_count != entry.byte_count or digest != entry.content_digest:
            raise OSError("Published Package tree content changed")
    return observed_directories, observed_files


def _collect_tree(
    root_fd: int,
    expected: dict[str, PackageVerifiedTreeEntryV1],
    *,
    directory_identities: dict[tuple[str, ...], _Identity] | None,
    file_identities: dict[tuple[str, ...], _Identity] | None,
) -> tuple[
    dict[str, tuple[int, str]],
    dict[tuple[str, ...], _Identity],
    dict[tuple[str, ...], _Identity],
]:
    observed: dict[str, tuple[int, str]] = {}
    observed_directories: dict[tuple[str, ...], _Identity] = {}
    observed_files: dict[tuple[str, ...], _Identity] = {}
    expected_directories = {
        "/".join(parts[:depth])
        for logical_path in expected
        for parts in (tuple(logical_path.split("/")),)
        for depth in range(1, len(parts))
    }

    def visit(directory_fd: int, prefix: tuple[str, ...]) -> None:
        saw_entry = False
        with os.scandir(directory_fd) as directory_entries:
            for directory_entry in directory_entries:
                saw_entry = True
                name = directory_entry.name
                if not name or name in {".", ".."} or "/" in name or "\x00" in name:
                    raise OSError("Published Package tree entry name is invalid")
                metadata = os.stat(
                    name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                parts = prefix + (name,)
                logical_path = "/".join(parts)
                if stat.S_ISDIR(metadata.st_mode):
                    if logical_path not in expected_directories:
                        raise OSError(
                            "Published Package tree has an unexpected directory"
                        )
                    identity = _identity(metadata)
                    if (
                        directory_identities is not None
                        and identity != directory_identities.get(parts)
                    ):
                        raise OSError("Published Package directory identity changed")
                    child_fd = _open_directory(name, dir_fd=directory_fd)
                    try:
                        if _identity(os.fstat(child_fd)) != identity:
                            raise OSError(
                                "Published Package directory identity changed"
                            )
                        observed_directories[parts] = identity
                        visit(child_fd, parts)
                    finally:
                        os.close(child_fd)
                elif stat.S_ISREG(metadata.st_mode):
                    entry = expected.get(logical_path)
                    if entry is None or metadata.st_nlink != 1:
                        raise OSError("Published Package tree has an unexpected file")
                    identity = _identity(metadata)
                    if (
                        file_identities is not None
                        and identity != file_identities.get(parts)
                    ):
                        raise OSError("Published Package file identity changed")
                    descriptor = _open_regular_file(
                        directory_fd,
                        name,
                        create_new=False,
                        write=False,
                    )
                    digest = sha256()
                    byte_count = 0
                    try:
                        while chunk := os.read(descriptor, 64 * 1024):
                            digest.update(chunk)
                            byte_count += len(chunk)
                            if byte_count > entry.byte_count:
                                raise OSError(
                                    "Published Package file exceeds verified size"
                                )
                        opened = os.fstat(descriptor)
                        if (
                            _identity(opened) != _identity(metadata)
                            or opened.st_nlink != 1
                        ):
                            raise OSError("Published Package file identity changed")
                    finally:
                        os.close(descriptor)
                    observed[logical_path] = (byte_count, digest.hexdigest())
                    observed_files[parts] = identity
                else:
                    raise OSError("Published Package tree entry type changed")
        if not saw_entry and prefix:
            raise OSError("Published Package tree contains an empty directory")

    visit(root_fd, ())
    if directory_identities is not None and set(observed_directories) != set(
        directory_identities
    ):
        raise OSError("Published Package directory set changed")
    if file_identities is not None and set(observed_files) != set(file_identities):
        raise OSError("Published Package file set changed")
    return observed, observed_directories, observed_files


def _supports_posix_rooted_io() -> bool:
    return (
        os.name == "posix"
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and _noreplace_rename_function() is not None
        and os.rmdir in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
    )


_RenameAt = Callable[[int, bytes, int, bytes, int], int]


def _noreplace_rename_function() -> tuple[_RenameAt, int] | None:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
    except OSError:
        return None
    if sys.platform.startswith("linux"):
        function = getattr(libc, "renameat2", None)
        flag = 1  # RENAME_NOREPLACE
    elif sys.platform == "darwin":
        function = getattr(libc, "renameatx_np", None)
        flag = 0x00000004  # RENAME_EXCL
    else:
        return None
    if function is None:
        return None
    return cast(_RenameAt, function), flag


def _rename_directory_noreplace(
    source_directory_fd: int,
    source_name: str,
    target_directory_fd: int,
    target_name: str,
) -> None:
    resolved = _noreplace_rename_function()
    if resolved is None:
        raise OSError(errno.ENOTSUP, "Atomic no-replace rename is unavailable")
    function, flag = resolved
    ctypes.set_errno(0)
    result = function(
        source_directory_fd,
        os.fsencode(source_name),
        target_directory_fd,
        os.fsencode(target_name),
        flag,
    )
    if result != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(error_number, os.strerror(error_number), target_name)


def _open_directory(path: str | Path, *, dir_fd: int | None = None) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    return os.open(path, flags, dir_fd=dir_fd)


def _open_regular_file(
    directory_fd: int,
    name: str,
    *,
    create_new: bool,
    write: bool,
) -> int:
    flags = (os.O_WRONLY if write else os.O_RDONLY) | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    if create_new:
        flags |= os.O_CREAT | os.O_EXCL
    return os.open(name, flags, 0o600, dir_fd=directory_fd)


def _open_relative_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    current_fd = os.dup(root_fd)
    try:
        for part in parts:
            child_fd = _open_directory(part, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = child_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _entry_exists(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _identity(metadata: os.stat_result) -> _Identity:
    return (metadata.st_dev, metadata.st_ino)


def _root_untrusted() -> PackagePhysicalStagingError:
    return PackagePhysicalStagingError(
        "Package Store root or owned staging identity changed",
        code="package_publication_root_untrusted",
    )


def _collision() -> PackagePhysicalStagingError:
    return PackagePhysicalStagingError(
        "Package Store settlement evidence does not authorize this tree",
        code="package_publication_collision",
    )


__all__ = [
    "PackagePhysicalStagingError",
    "PosixPackageDependencyMaterializationStore",
    "PosixPackagePluginRootMaterializationStore",
]
