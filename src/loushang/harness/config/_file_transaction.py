"""Process- and host-wide serialization for persistent config files."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from threading import RLock
from weakref import WeakValueDictionary

from loushang.harness.journal import journal_file_lock


class _ReentrantConfigFileLock:
    """Keep one OS lease per path while allowing same-thread nesting."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._process_lock = RLock()
        self._depth = 0
        self._lease: AbstractContextManager[None] | None = None

    @contextmanager
    def hold(self) -> Iterator[None]:
        with self._process_lock:
            if self._depth == 0:
                lease = journal_file_lock(
                    self._path,
                    "exclusive",
                    lock_suffix=".config.lock",
                )
                lease.__enter__()
                self._lease = lease
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
                if self._depth == 0:
                    active_lease: AbstractContextManager[None] | None = self._lease
                    self._lease = None
                    assert active_lease is not None
                    active_lease.__exit__(None, None, None)


_REGISTRY_LOCK = RLock()
_LOCKS: WeakValueDictionary[Path, _ReentrantConfigFileLock] = WeakValueDictionary()


def normalized_config_path(path: Path) -> Path:
    """Return the stable identity used to order and share config locks."""

    return path.expanduser().resolve(strict=False)


def config_file_transaction_lock(path: Path) -> AbstractContextManager[None]:
    """Return a re-entrant process lock backed by one cross-process file lock."""

    identity = normalized_config_path(path)
    with _REGISTRY_LOCK:
        lock = _LOCKS.get(identity)
        if lock is None:
            lock = _ReentrantConfigFileLock(identity)
            _LOCKS[identity] = lock
    return lock.hold()


__all__ = ["config_file_transaction_lock", "normalized_config_path"]
