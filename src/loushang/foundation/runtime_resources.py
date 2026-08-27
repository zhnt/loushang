"""Application-owned composition of one machine-local runtime lifetime."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import suppress
from pathlib import Path
from weakref import ReferenceType, ref

from .artifact_store import (
    ArtifactDisclosure,
    ArtifactReader,
    ArtifactSnapshotStore,
    ArtifactStore,
    ArtifactStorePort,
    ArtifactWriter,
    StoredArtifact,
)
from .runtime_scope import (
    DEFAULT_RUNTIME_SWEEP_POLICY,
    RunLease,
    RuntimeScope,
    RuntimeSweepPolicy,
    RuntimeSweepReport,
)

ArtifactStoreFactory = Callable[[RuntimeScope], ArtifactStorePort]
DEFAULT_ARTIFACT_STORE_FACTORY: ArtifactStoreFactory = ArtifactStore


class _RuntimeArtifactPort:
    """Revocable focused projection over the owner's concrete store."""

    __slots__ = ("_owner_ref",)

    def __init__(self, owner: RuntimeResourceOwner) -> None:
        self._owner_ref: ReferenceType[RuntimeResourceOwner] = ref(owner)

    def _active_store(self) -> ArtifactStorePort:
        owner = self._owner_ref()
        if owner is None:
            raise RuntimeError("runtime resource owner is closed")
        return owner._active_store()

    def put_bytes(
        self,
        content: bytes,
        *,
        logical_name: str,
        kind: str,
        media_type: str,
        disclosure: ArtifactDisclosure = "private",
        source: str | None = None,
    ) -> StoredArtifact:
        store = self._active_store()
        return store.put_bytes(
            content,
            logical_name=logical_name,
            kind=kind,
            media_type=media_type,
            disclosure=disclosure,
            source=source,
        )

    def snapshot_file(
        self,
        source_path: str | Path,
        *,
        logical_name: str,
        kind: str,
        media_type: str,
        allowed_roots: Sequence[str | Path],
        disclosure: ArtifactDisclosure = "private",
        source: str | None = None,
    ) -> StoredArtifact:
        store = self._active_store()
        return store.snapshot_file(
            source_path,
            logical_name=logical_name,
            kind=kind,
            media_type=media_type,
            allowed_roots=allowed_roots,
            disclosure=disclosure,
            source=source,
        )

    def read_bytes(self, artifact: StoredArtifact) -> bytes:
        return self._active_store().read_bytes(artifact)


class RuntimeResourceOwner:
    """Own the lease and run-local services for exactly one application run.

    Composition roots retain this object for the whole application lifetime.
    Consumers receive only the focused artifact capability they need and never
    receive the lease or authority to remove the shared run tree.
    """

    __slots__ = (
        "scope",
        "_artifact_port",
        "_artifact_store",
        "_lease",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        scope: RuntimeScope,
        lease: RunLease,
        artifact_store: ArtifactStorePort,
    ) -> None:
        self.scope = scope
        self._lease: RunLease | None = lease
        self._artifact_store = artifact_store
        self._artifact_port = _RuntimeArtifactPort(self)

    @classmethod
    def acquire(
        cls,
        scope: RuntimeScope,
        *,
        sweep_policy: RuntimeSweepPolicy = DEFAULT_RUNTIME_SWEEP_POLICY,
        artifact_store_factory: ArtifactStoreFactory = DEFAULT_ARTIFACT_STORE_FACTORY,
    ) -> RuntimeResourceOwner:
        """Acquire one lease and construct its services as one transaction."""

        lease = RunLease.acquire(scope, sweep_policy=sweep_policy)
        try:
            artifact_store = artifact_store_factory(scope)
        except BaseException:
            lease.close()
            raise
        return cls(
            scope=scope,
            lease=lease,
            artifact_store=artifact_store,
        )

    @property
    def active(self) -> bool:
        return self._lease is not None

    @property
    def sweep_report(self) -> RuntimeSweepReport:
        lease = self._lease
        if lease is None:
            raise RuntimeError("runtime resource owner is closed")
        return lease.sweep_report

    @property
    def artifact_writer(self) -> ArtifactWriter:
        self._require_active()
        return self._artifact_port

    @property
    def artifact_reader(self) -> ArtifactReader:
        self._require_active()
        return self._artifact_port

    @property
    def artifact_snapshots(self) -> ArtifactSnapshotStore:
        self._require_active()
        return self._artifact_port

    def close(self) -> None:
        """Close the shared lifetime once; leaf capabilities become invalid."""

        lease = self._lease
        if lease is None:
            return
        self._lease = None
        lease.close()

    def _require_active(self) -> None:
        if self._lease is None:
            raise RuntimeError("runtime resource owner is closed")

    def _active_store(self) -> ArtifactStorePort:
        self._require_active()
        return self._artifact_store

    def __enter__(self) -> RuntimeResourceOwner:
        self._require_active()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        with suppress(BaseException):
            self.close()


__all__ = [
    "ArtifactStoreFactory",
    "DEFAULT_ARTIFACT_STORE_FACTORY",
    "RuntimeResourceOwner",
]
