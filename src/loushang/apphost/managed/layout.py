"""Explicit new-deployment directory preparation using existing native owners.

This is not service recovery: callers must not use it to recreate a lost
runtime or lifecycle fence for an existing/unknown live instance. It creates
neither authority records nor Session roots, and reads no environment.
"""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from time import monotonic

from ._files import ManagedStorageError, PrivateManagedDirectory, _check_deadline
from .contracts import ManagedInstanceRefV1, ManagedNamespaceV1, ManagedServiceKeyV1
from .paths import ManagedDeploymentPathsV1, resolve_managed_paths


class ManagedLayoutPreparationV1:
    """Retain all fixed directory owners before the first native operation.

    Synchronous composition only. Async callers must retain and join their
    original native task; cancelling a waiter does not settle this object.
    Failed initialization leaves directories in place, never recursively
    removes them, and does not become a ready service or a recovery proof.
    """

    def __init__(
        self, namespace: ManagedNamespaceV1, service: ManagedServiceKeyV1,
        instance: ManagedInstanceRefV1, *, runtime_root: str,
        temporary_override: str | None = None,
        require_control_roots: bool = False,
    ) -> None:
        if type(require_control_roots) is not bool:
            raise ManagedStorageError("invalid_record")
        self._paths = resolve_managed_paths(
            namespace, service, instance, runtime_root=runtime_root,
            temporary_override=temporary_override,
        )
        paths = tuple(Path(path) for path in (
            self.paths.registry, self.paths.lifecycle, self.paths.application,
            self.paths.control, self.paths.logs, self.paths.temporary,
            self.paths.cache, self.paths.connection, self.paths.runtime_control,
        ))
        # Include the anchor, all ancestor fds, final fd and opening slot.
        if sum(len(path.parts) + 2 for path in paths) > 512:
            raise ManagedStorageError("capacity")
        self._directories = tuple(
            PrivateManagedDirectory(
                path, create=not (require_control_roots and index < 2),
                create_parents=not (require_control_roots and index < 2), defer_open=True,
            )
            for index, path in enumerate(paths)
        )
        self._closed: set[int] = set()
        self._mutex = RLock()
        self._attempted = self._opened = self._closing = False

    @property
    def paths(self) -> ManagedDeploymentPathsV1:
        return self._paths

    @property
    def cleanup_pending(self) -> bool:
        return len(self._closed) != len(self._directories)

    @property
    def initialized(self) -> bool:
        return self._opened and not self._closing

    def open(self, *, deadline: float) -> None:
        _check_deadline(deadline)
        if not self._mutex.acquire(timeout=max(0.0, min(30.0, deadline - monotonic()))):
            raise ManagedStorageError("busy")
        try:
            if self._attempted or self._closing:
                raise ManagedStorageError("closed")
            self._attempted = True
            for directory in self._directories:
                directory.open(deadline=deadline)
            # No earlier owner can have been replaced while later leaves open.
            for directory in self._directories:
                _check_deadline(deadline)
                directory._check()
            _check_deadline(deadline)
            self._opened = True
        finally:
            self._mutex.release()

    def close(self) -> None:
        with self._mutex:
            self._closing = True
            failures: list[BaseException] = []
            for index, directory in enumerate(self._directories):
                if index in self._closed:
                    continue
                try:
                    directory.close()
                except BaseException as error:
                    failures.append(error)
                else:
                    self._closed.add(index)
            if failures:
                raise failures[0]


__all__ = ["ManagedLayoutPreparationV1"]
