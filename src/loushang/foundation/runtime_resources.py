"""Application-owned composition of one machine-local runtime lifetime."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from threading import Condition
from typing import Literal
from weakref import ReferenceType, ref

from .artifact_store import (
    ArtifactDisclosure,
    ArtifactReader,
    ArtifactRef,
    ArtifactSnapshotStore,
    ArtifactStore,
    ArtifactStoreBackend,
    ArtifactWriter,
)
from .runtime_scope import (
    DEFAULT_RUNTIME_SWEEP_POLICY,
    RunLease,
    RuntimeScope,
    RuntimeSweepPolicy,
    RuntimeSweepReport,
)

ArtifactStoreFactory = Callable[[RuntimeScope], ArtifactStoreBackend]
DEFAULT_ARTIFACT_STORE_FACTORY: ArtifactStoreFactory = ArtifactStore

_OWNER_CONSTRUCTION_TOKEN = object()
_OwnerState = Literal["open", "closing", "closed"]


class _RuntimeArtifactPort:
    """Weak, revocable base for one focused artifact capability."""

    __slots__ = ("_owner_ref",)

    def __init__(self, owner: RuntimeResourceOwner) -> None:
        self._owner_ref: ReferenceType[RuntimeResourceOwner] = ref(owner)

    @contextmanager
    def _operation(self) -> Iterator[ArtifactStoreBackend]:
        owner = self._owner_ref()
        if owner is None:
            raise RuntimeError("runtime resource owner is closed")
        with owner._artifact_operation() as store:
            yield store


class _RuntimeArtifactWriter(_RuntimeArtifactPort):
    """Runtime projection that grants artifact publication only."""

    __slots__ = ()

    def put_bytes(
        self,
        content: bytes,
        *,
        logical_name: str,
        kind: str,
        media_type: str,
        disclosure: ArtifactDisclosure = "private",
        source: str | None = None,
    ) -> ArtifactRef:
        with self._operation() as store:
            return store.put_bytes(
                content,
                logical_name=logical_name,
                kind=kind,
                media_type=media_type,
                disclosure=disclosure,
                source=source,
            )


class _RuntimeArtifactReader(_RuntimeArtifactPort):
    """Runtime projection that grants verified artifact reads only."""

    __slots__ = ()

    def read_bytes(self, artifact: ArtifactRef) -> bytes:
        with self._operation() as store:
            return store.read_bytes(artifact)


class _RuntimeArtifactSnapshots(_RuntimeArtifactPort):
    """Runtime projection bound to composition-authorized snapshot roots."""

    __slots__ = ("_allowed_roots",)

    def __init__(
        self,
        owner: RuntimeResourceOwner,
        *,
        allowed_roots: Sequence[str | Path],
    ) -> None:
        super().__init__(owner)
        roots = tuple(allowed_roots)
        if not roots:
            raise ValueError("artifact snapshot capability requires allowed roots")
        self._allowed_roots = roots

    def snapshot_file(
        self,
        source_path: str | Path,
        *,
        logical_name: str,
        kind: str,
        media_type: str,
        disclosure: ArtifactDisclosure = "private",
        source: str | None = None,
    ) -> ArtifactRef:
        with self._operation() as store:
            return store.snapshot_file(
                source_path,
                logical_name=logical_name,
                kind=kind,
                media_type=media_type,
                disclosure=disclosure,
                source=source,
                allowed_roots=self._allowed_roots,
            )

    def read_bytes(self, artifact: ArtifactRef) -> bytes:
        with self._operation() as store:
            return store.read_bytes(artifact)


class RuntimeResourceOwner:
    """Own the lease and run-local services for exactly one application run.

    Construction roots retain this object for the whole application lifetime.
    Consumers receive focused, revocable artifact projections and never the
    Lease, backend Store, or authority to remove the shared run tree.
    """

    __slots__ = (
        "scope",
        "_active_operations",
        "_artifact_reader",
        "_artifact_store",
        "_artifact_writer",
        "_condition",
        "_lease",
        "_state",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        scope: RuntimeScope,
        lease: RunLease,
        artifact_store: ArtifactStoreBackend,
        _construction_token: object | None = None,
    ) -> None:
        if _construction_token is not _OWNER_CONSTRUCTION_TOKEN:
            raise TypeError("RuntimeResourceOwner must be created with acquire()")
        if not lease.active or lease.scope != scope:
            raise ValueError("runtime lease does not match the owner scope")
        if artifact_store.scope != scope:
            raise ValueError("artifact store does not match the owner scope")
        self.scope = scope
        self._lease: RunLease | None = lease
        self._artifact_store = artifact_store
        self._condition = Condition()
        self._active_operations = 0
        self._state: _OwnerState = "open"
        self._artifact_writer = _RuntimeArtifactWriter(self)
        self._artifact_reader = _RuntimeArtifactReader(self)

    @classmethod
    def acquire(
        cls,
        scope: RuntimeScope,
        *,
        sweep_policy: RuntimeSweepPolicy = DEFAULT_RUNTIME_SWEEP_POLICY,
        artifact_store_factory: ArtifactStoreFactory = DEFAULT_ARTIFACT_STORE_FACTORY,
    ) -> RuntimeResourceOwner:
        """Acquire one Lease and construct its services as one transaction."""

        lease = RunLease.acquire(scope, sweep_policy=sweep_policy)
        try:
            artifact_store = artifact_store_factory(scope)
            if artifact_store.scope != scope:
                raise ValueError("artifact store factory returned a mismatched scope")
            return cls(
                scope=scope,
                lease=lease,
                artifact_store=artifact_store,
                _construction_token=_OWNER_CONSTRUCTION_TOKEN,
            )
        except BaseException:
            lease.close()
            raise

    @property
    def active(self) -> bool:
        with self._condition:
            lease = self._lease
            return self._state == "open" and lease is not None and lease.active

    @property
    def sweep_report(self) -> RuntimeSweepReport:
        with self._condition:
            lease = self._require_open_lease()
            return lease.sweep_report

    @property
    def artifact_writer(self) -> ArtifactWriter:
        with self._condition:
            self._require_open_lease()
            return self._artifact_writer

    @property
    def artifact_reader(self) -> ArtifactReader:
        with self._condition:
            self._require_open_lease()
            return self._artifact_reader

    def artifact_snapshots(
        self,
        *,
        allowed_roots: Sequence[str | Path],
    ) -> ArtifactSnapshotStore:
        """Bind snapshot authority once at the application composition edge."""

        with self._condition:
            self._require_open_lease()
            return _RuntimeArtifactSnapshots(
                self,
                allowed_roots=allowed_roots,
            )

    def close(self) -> None:
        """Revoke new operations, drain in-flight work, then close the Lease."""

        with self._condition:
            if self._state == "closed":
                return
            if self._state == "closing":
                while self._state != "closed":
                    self._condition.wait()
                return
            self._state = "closing"
            while self._active_operations:
                self._condition.wait()
            lease = self._lease

        try:
            if lease is not None:
                lease.close()
        finally:
            with self._condition:
                self._lease = None
                self._state = "closed"
                self._condition.notify_all()

    @contextmanager
    def _artifact_operation(self) -> Iterator[ArtifactStoreBackend]:
        with self._condition:
            self._require_open_lease()
            self._active_operations += 1
        try:
            yield self._artifact_store
        finally:
            with self._condition:
                self._active_operations -= 1
                if self._active_operations == 0:
                    self._condition.notify_all()

    def _require_open_lease(self) -> RunLease:
        lease = self._lease
        if self._state != "open" or lease is None or not lease.active:
            raise RuntimeError("runtime resource owner is closed")
        return lease

    def __enter__(self) -> RuntimeResourceOwner:
        with self._condition:
            self._require_open_lease()
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
