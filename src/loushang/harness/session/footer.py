"""Reusable session footer state and workspace branch observation."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.workspace.git import find_git_paths, get_git_branch

BranchResolver = Callable[[str | Path], str | None]
BranchChangeCallback = Callable[[str | None], None]


@dataclass(frozen=True)
class FooterSnapshot:
    git_branch: str | None
    extension_statuses: dict[str, str]
    available_provider_count: int


class FooterDataProvider:
    def __init__(
        self,
        cwd: str | Path,
        *,
        branch_resolver: BranchResolver = get_git_branch,
    ) -> None:
        self._cwd = Path(cwd).resolve()
        self._branch_resolver = branch_resolver
        self._cached_git_branch: str | None = None
        self._has_cached_git_branch = False
        self._branch_change_callbacks: list[BranchChangeCallback] = []
        self._extension_statuses: dict[str, str] = {}
        self._available_provider_count = 0
        self._disposed = False
        self._watch_lock = threading.Lock()
        self._watch_stop: threading.Event | None = None
        self._watch_thread: threading.Thread | None = None
        self._watch_poll_interval_seconds = 0.25
        self._watch_debounce_seconds = 0.5

    @property
    def cwd(self) -> Path:
        return self._cwd

    def set_cwd(self, cwd: str | Path) -> None:
        next_cwd = Path(cwd).resolve()
        if next_cwd == self._cwd:
            return
        watcher_was_running = self.is_git_watcher_running()
        if watcher_was_running:
            self.stop_git_watcher()
        previous_branch = self.get_git_branch()
        self._cwd = next_cwd
        self._has_cached_git_branch = False
        next_branch = self.get_git_branch()
        if next_branch != previous_branch:
            self._notify_branch_change(next_branch)
        if watcher_was_running:
            self.start_git_watcher(
                poll_interval_seconds=self._watch_poll_interval_seconds,
                debounce_seconds=self._watch_debounce_seconds,
            )

    def get_git_branch(self) -> str | None:
        if not self._has_cached_git_branch:
            self._cached_git_branch = self._branch_resolver(self._cwd)
            self._has_cached_git_branch = True
        return self._cached_git_branch

    def refresh_git_branch(self) -> str | None:
        previous_branch = self._cached_git_branch if self._has_cached_git_branch else self.get_git_branch()
        next_branch = self._branch_resolver(self._cwd)
        self._cached_git_branch = next_branch
        self._has_cached_git_branch = True
        if next_branch != previous_branch:
            self._notify_branch_change(next_branch)
        return next_branch

    def on_branch_change(self, callback: BranchChangeCallback) -> Callable[[], None]:
        self._branch_change_callbacks.append(callback)

        def unsubscribe() -> None:
            try:
                self._branch_change_callbacks.remove(callback)
            except ValueError:
                return

        return unsubscribe

    def get_extension_statuses(self) -> dict[str, str]:
        return dict(self._extension_statuses)

    def set_extension_status(self, name: str, status: str | None) -> None:
        if status is None:
            self._extension_statuses.pop(name, None)
            return
        self._extension_statuses[name] = status

    def clear_extension_statuses(self) -> None:
        self._extension_statuses.clear()

    def get_available_provider_count(self) -> int:
        return self._available_provider_count

    def set_available_provider_count(self, count: int) -> None:
        if count < 0:
            raise ValueError("available provider count must be non-negative")
        self._available_provider_count = int(count)

    def snapshot(self) -> FooterSnapshot:
        return FooterSnapshot(
            git_branch=self.get_git_branch(),
            extension_statuses=self.get_extension_statuses(),
            available_provider_count=self._available_provider_count,
        )

    def start_git_watcher(
        self,
        *,
        poll_interval_seconds: float = 0.25,
        debounce_seconds: float = 0.5,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if debounce_seconds < 0:
            raise ValueError("debounce_seconds must be non-negative")
        with self._watch_lock:
            if self._disposed:
                return
            self._watch_poll_interval_seconds = poll_interval_seconds
            self._watch_debounce_seconds = debounce_seconds
            if self._watch_thread is not None and self._watch_thread.is_alive():
                return
            stop = threading.Event()
            initial_signature = self._git_watch_signature()
            self._watch_stop = stop
            self._watch_thread = threading.Thread(
                target=self._watch_git_branch,
                args=(stop, poll_interval_seconds, debounce_seconds, initial_signature),
                name="loushang-footer-git-watcher",
                daemon=True,
            )
            self._watch_thread.start()

    def stop_git_watcher(self) -> None:
        with self._watch_lock:
            stop = self._watch_stop
            thread = self._watch_thread
            self._watch_stop = None
            self._watch_thread = None
        if stop is not None:
            stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def is_git_watcher_running(self) -> bool:
        thread = self._watch_thread
        return thread is not None and thread.is_alive()

    def dispose(self) -> None:
        self._disposed = True
        self.stop_git_watcher()
        self._branch_change_callbacks.clear()
        self._extension_statuses.clear()

    def _notify_branch_change(self, branch: str | None) -> None:
        if self._disposed:
            return
        for callback in tuple(self._branch_change_callbacks):
            callback(branch)

    def _watch_git_branch(
        self,
        stop: threading.Event,
        poll_interval_seconds: float,
        debounce_seconds: float,
        initial_signature: tuple[tuple[str, bool, int, int], ...],
    ) -> None:
        previous_signature = initial_signature
        pending_since: float | None = None
        while not stop.wait(poll_interval_seconds):
            current_signature = self._git_watch_signature()
            if current_signature != previous_signature:
                previous_signature = current_signature
                pending_since = time.monotonic()
            if pending_since is None:
                continue
            if time.monotonic() - pending_since < debounce_seconds:
                continue
            pending_since = None
            self.refresh_git_branch()

    def _git_watch_signature(self) -> tuple[tuple[str, bool, int, int], ...]:
        git_paths = find_git_paths(self._cwd)
        if git_paths is None:
            return (("<no-git>", False, 0, 0),)
        watched_paths = (
            git_paths.head_path,
            git_paths.head_path.parent,
            git_paths.common_git_dir / "packed-refs",
            git_paths.common_git_dir / "reftable",
            git_paths.common_git_dir / "reftable" / "tables.list",
        )
        return tuple(_stat_signature(path) for path in dict.fromkeys(watched_paths))


def _stat_signature(path: Path) -> tuple[str, bool, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), False, 0, 0)
    return (str(path), True, stat.st_mtime_ns, stat.st_size)


def footer_snapshot_to_mapping(snapshot: FooterSnapshot) -> Mapping[str, object]:
    return {
        "git_branch": snapshot.git_branch,
        "extension_statuses": dict(snapshot.extension_statuses),
        "available_provider_count": snapshot.available_provider_count,
    }


__all__ = [
    "BranchChangeCallback",
    "BranchResolver",
    "FooterDataProvider",
    "FooterSnapshot",
    "footer_snapshot_to_mapping",
]
