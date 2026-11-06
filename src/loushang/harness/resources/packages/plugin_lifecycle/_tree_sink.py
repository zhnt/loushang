"""Shared verified-tree sink lifecycle over the original native operations."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import AbstractContextManager, suppress
from typing import Generic, Self

from ._file_sinks import ReuseFileSink, VerifiedFileSink
from ._materialization_shared import (
    ObservedTree,
    RootT,
    _collision,
    _root_untrusted,
    finish_verified_tree,
    stable_ref,
)
from .staging import PackageArtifactStagingReceiptV1, PackageArtifactStagingRequestV1
from .store_settlements import (
    NativeIdentity,
    PackageStoreRole,
    PackageStoreSettlementJournal,
    PackageStoreSettlementJournalError,
)
from .tree_transfer import (
    PackagePhysicalStagingError,
    PackageVerifiedTreeEntryV1,
    PackageVerifiedTreeManifestV1,
)


class PackageVerifiedTreeSink(ABC, Generic[RootT]):
    """Own sink state and ordering; native subclasses own filesystem effects."""

    def __init__(
        self,
        *,
        root: RootT,
        role: PackageStoreRole,
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
        self._stable_ref = stable_ref(
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
        self._staging_identity: NativeIdentity | None = None
        self._directory_identities: dict[tuple[str, ...], NativeIdentity] = {}
        self._file_identities: dict[tuple[str, ...], NativeIdentity] = {}
        self._next_entry = 0
        self._active_file: VerifiedFileSink | ReuseFileSink | None = None
        self._reuse = False
        self._reuse_alias = False
        self._authorized = False
        self._renamed = False
        self._finished = False
        self._closed = False
        self._prepare()

    def __enter__(self) -> Self:
        if self._closed:
            raise RuntimeError("Package verified-tree sink is closed")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is not None or not self._finished:
            self.abort()

    def open_file(
        self,
        entry: PackageVerifiedTreeEntryV1,
    ) -> AbstractContextManager[VerifiedFileSink | ReuseFileSink]:
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
            file_sink: VerifiedFileSink | ReuseFileSink = ReuseFileSink(
                entry=entry,
                on_finished=self._file_finished,
            )
        else:
            file_sink = self._create_file_sink(entry)
        self._active_file = file_sink
        return file_sink

    def _file_finished(self, sink: VerifiedFileSink | ReuseFileSink) -> None:
        if sink is not self._active_file:
            raise RuntimeError("Package Store file sink ownership changed")
        self._active_file = None
        self._next_entry += 1

    def finish(self) -> PackageArtifactStagingReceiptV1:
        self._require_open()
        return finish_verified_tree(
            self,
            store_role=self._role,
            store_identity=self._store_identity,
            root_identities=self._root.identities,
            final_name=self._final_name,
            staging_name=self._staging_name,
            manifest=self._manifest,
            receipt=self._receipt,
            settlement_journal=self._settlement_journal,
            reuse=self._reuse,
            reuse_alias=self._reuse_alias,
            completed_entries=self._next_entry,
            has_active_file=self._active_file is not None,
        )

    def complete_and_close(self) -> None:
        self._finished = True
        self._close_handles()

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

    def _prepare(self) -> None:
        try:
            self._root.validate_visible()
            if self._settlement_journal.is_tombstoned(self._stable_ref.ref_id):
                raise _collision()
            if self._entry_exists(self._staging_name):
                raise _root_untrusted()
            if self._entry_exists(self._final_name):
                tree_identity, directory_identities, file_identities = (
                    self._root.validate_tree(
                        self._final_name,
                        self._manifest,
                    )
                )
                exact = self._settlement_journal.authorizes(
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
                )
                alias = (
                    self._role == "dependency"
                    and not exact
                    and self._settlement_journal.authorizes_dependency_reuse(
                        store_identity=self._store_identity,
                        root_identities=self._root.identities,
                        tree_identity=tree_identity,
                        directory_identities=directory_identities,
                        file_identities=file_identities,
                        final_name=self._final_name,
                        staging_name=self._staging_name,
                        manifest=self._manifest,
                        receipt=self._receipt,
                    )
                )
                if not exact and not alias:
                    raise PackagePhysicalStagingError(
                        "Package Store final identity lacks durable owner evidence",
                        code="package_publication_collision",
                    )
                self._reuse = True
                self._reuse_alias = alias
                return
            self._create_staging()
        except PackagePhysicalStagingError:
            raise
        except PackageStoreSettlementJournalError:
            raise _root_untrusted() from None
        except Exception:
            raise _root_untrusted() from None

    @abstractmethod
    def _entry_exists(self, name: str) -> bool: ...

    @abstractmethod
    def _create_staging(self) -> None: ...

    @abstractmethod
    def _create_file_sink(
        self, entry: PackageVerifiedTreeEntryV1
    ) -> VerifiedFileSink: ...

    @abstractmethod
    def _remove_owned_tree(self, name: str, expected: NativeIdentity) -> None: ...

    @abstractmethod
    def observe_reused_tree(self) -> ObservedTree: ...

    @abstractmethod
    def prepare_new_tree(self) -> ObservedTree: ...

    @abstractmethod
    def publish_authorized_tree(self) -> None: ...
