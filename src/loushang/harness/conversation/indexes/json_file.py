from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import stat
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from time import time_ns
from typing import Any, Generic, Protocol, TypeVar, cast

from loushang.harness.conversation.index import (
    ConversationIndexSnapshot,
    ConversationIndexState,
    IndexedProjection,
    IndexQuery,
)
from loushang.harness.conversation.store import (
    ConversationKey,
    ConversationLocator,
    require_revision,
)
from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.journal.jsonl import journal_file_lock, journal_file_lock_at

P = TypeVar("P")
Q = TypeVar("Q")
_MAX_CONVERSATION_INDEX_BYTES = 64 * 1024 * 1024


class ProjectionCodec(Protocol, Generic[P]):
    def encode(self, projection: P) -> Mapping[str, object]: ...

    def decode(self, value: Mapping[str, object]) -> P: ...


@dataclass(frozen=True)
class FunctionalProjectionCodec(Generic[P]):
    encoder: Callable[[P], Mapping[str, object]]
    decoder: Callable[[Mapping[str, object]], P]

    def encode(self, projection: P) -> Mapping[str, object]:
        return self.encoder(projection)

    def decode(self, value: Mapping[str, object]) -> P:
        return self.decoder(value)


@dataclass(frozen=True)
class ProjectionIndexSnapshot(Generic[P]):
    projections: tuple[P, ...]
    stale: bool = False


@dataclass(frozen=True)
class JsonIndexPublication:
    """Exact successful local publication, not permission to delete by name."""

    path: Path
    generation: str
    sequence: int
    identity: tuple[int, int]
    parent_identity: tuple[int, int] | None = None


class JsonProjectionIndex(Generic[P]):
    def __init__(
        self,
        path: str | Path,
        *,
        version: int,
        codec: ProjectionCodec[P],
        items_key: str = "items",
        is_current: Callable[[P], bool] | None = None,
        sort_key: Callable[[P], Any] | None = None,
        reverse: bool = False,
        generated_at: Callable[[], str] | None = None,
    ) -> None:
        if version < 1:
            raise ValueError("projection index version must be positive")
        if not items_key:
            raise ValueError("projection index items key must not be empty")
        self.path = Path(path)
        self.version = version
        self.codec = codec
        self.items_key = items_key
        self.is_current = is_current
        self.sort_key = sort_key
        self.reverse = reverse
        self.generated_at = generated_at or _now_iso

    def write(self, projections: Sequence[P]) -> tuple[P, ...]:
        ordered = self._sort(projections)
        payload = {
            "version": self.version,
            "generated_at": self.generated_at(),
            self.items_key: [dict(self.codec.encode(item)) for item in ordered],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp_path.replace(self.path)
        except BaseException:
            with suppress(FileNotFoundError):
                temp_path.unlink()
            raise
        return ordered

    def load(self) -> ProjectionIndexSnapshot[P]:
        if not self.path.exists():
            return ProjectionIndexSnapshot(())
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.preserve_corrupt()
            return ProjectionIndexSnapshot((), stale=True)
        if not isinstance(payload, Mapping) or payload.get("version") != self.version:
            return ProjectionIndexSnapshot((), stale=True)
        raw_items = payload.get(self.items_key)
        if not isinstance(raw_items, list):
            return ProjectionIndexSnapshot((), stale=True)

        projections: list[P] = []
        stale = False
        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping):
                stale = True
                continue
            try:
                projection = self.codec.decode(cast(Mapping[str, object], raw_item))
            except Exception:
                stale = True
                continue
            if self.is_current is not None and not self.is_current(projection):
                stale = True
                continue
            projections.append(projection)
        return ProjectionIndexSnapshot(self._sort(projections), stale=stale)

    def load_or_refresh(
        self,
        build: Callable[[], Sequence[P]],
        *,
        refresh: bool = False,
        refresh_empty: bool = True,
    ) -> tuple[P, ...]:
        if not refresh:
            snapshot = self.load()
            if not snapshot.stale and (snapshot.projections or not refresh_empty):
                return snapshot.projections
        return self.write(build())

    def preserve_corrupt(self) -> Path | None:
        if not self.path.exists():
            return None
        target = self.path.with_name(f"{self.path.name}.corrupt-{time_ns()}")
        try:
            self.path.replace(target)
        except Exception:
            return None
        return target

    def _sort(self, projections: Sequence[P]) -> tuple[P, ...]:
        if self.sort_key is None:
            return tuple(projections)
        return tuple(sorted(projections, key=self.sort_key, reverse=self.reverse))


class JsonConversationIndex(Generic[P, Q]):
    """Atomic local adapter for the revision-aware projection index contract."""

    def __init__(
        self,
        path: str | Path,
        *,
        version: int,
        codec: ProjectionCodec[P],
        query_items: IndexQuery[Q, P],
        writable: bool = True,
    ) -> None:
        if version < 1:
            raise ValueError("conversation index version must be positive")
        self.path = Path(path)
        self.version = version
        self.codec = codec
        self._query_items = query_items
        self._writable = writable
        self._lock = Lock()

    async def upsert(self, item: IndexedProjection[P]) -> bool:
        return await asyncio.to_thread(self._upsert_sync, item)

    def upsert_rooted(self, item: IndexedProjection[P], target: RootedFile) -> bool:
        """Update an existing cache using the caller's retained transaction.

        The caller owns admission and native settlement. This synchronous path
        neither creates the index nor repairs/renames corrupt pathname caches.
        Its stable short lock serializes read/modify/write across processes.
        """
        require_revision(item.source_revision, name="source revision")
        if not self._writable:
            raise RuntimeError("read-only conversation index cannot be modified")
        try:
            target.read_bytes(max_bytes=_MAX_CONVERSATION_INDEX_BYTES)
        except FileNotFoundError:
            return False
        target.acquire_lock(exclusive=True, blocking=False, suffix=".lock")
        try:
            content = target.read_bytes(max_bytes=_MAX_CONVERSATION_INDEX_BYTES)
        except FileNotFoundError:
            return False
        state = self._decode_state(content, preserve_corrupt=False)
        if state.index_state != "fresh":
            return False
        if item.source_revision <= state.tombstones.get(item.locator, -1):
            return False
        current = state.items.get(item.locator)
        if current is not None and item.source_revision < current.source_revision:
            return False
        state.items[item.locator] = item
        self._write_state(
            state.items, state.tombstones, generation=_writable_generation(state),
            sequence=state.sequence + 1, target=target,
        )
        return True

    async def delete(
        self,
        locator: ConversationLocator,
        *,
        through_revision: int,
    ) -> bool:
        return await asyncio.to_thread(
            self._delete_sync,
            locator,
            through_revision,
        )

    async def get(
        self,
        locator: ConversationLocator,
    ) -> IndexedProjection[P] | None:
        return await asyncio.to_thread(self._get_sync, locator)

    async def query(self, query: Q) -> Sequence[IndexedProjection[P]]:
        snapshot = await self.query_snapshot(query)
        return snapshot.items

    async def query_snapshot(self, query: Q) -> ConversationIndexSnapshot[P]:
        return await asyncio.to_thread(self._query_snapshot_sync, query)

    async def replace(
        self,
        items: Sequence[IndexedProjection[P]],
    ) -> tuple[IndexedProjection[P], ...]:
        return await asyncio.to_thread(self._replace_sync, tuple(items))

    async def replace_with_receipt(
        self, items: Sequence[IndexedProjection[P]],
    ) -> tuple[tuple[IndexedProjection[P], ...], JsonIndexPublication]:
        return await asyncio.to_thread(self._replace_with_receipt_sync, tuple(items))

    async def invalidate_if_current(self, receipt: JsonIndexPublication) -> bool:
        """Invalidate only this exact version, serialized with all writers."""
        return await asyncio.to_thread(self._invalidate_if_current_sync, receipt)

    async def observe_publication(self) -> JsonIndexPublication | None:
        """Capture the exact existing version for a subsequent conditional check."""
        return await asyncio.to_thread(self._observe_publication_sync)

    def _observe_publication_sync(self) -> JsonIndexPublication | None:
        with self._mutation_scope() as directory:
            try:
                content, opened = _read_stable_regular_snapshot(
                    self.path, max_bytes=_MAX_CONVERSATION_INDEX_BYTES, directory=directory,
                )
            except FileNotFoundError:
                return None
            state = self._decode_state(content, preserve_corrupt=False)
            if state.index_state != "fresh":
                return None
            parent = os.fstat(directory) if directory is not None else None
            return JsonIndexPublication(
                self.path, state.generation, state.sequence, (opened.st_dev, opened.st_ino),
                (parent.st_dev, parent.st_ino) if parent is not None else None,
            )

    async def upsert_with_receipt(
        self, item: IndexedProjection[P],
    ) -> tuple[bool, JsonIndexPublication | None]:
        return await asyncio.to_thread(self._upsert_with_receipt_sync, item)

    def _invalidate_if_current_sync(self, receipt: JsonIndexPublication) -> bool:
        if receipt.path != self.path:
            raise ValueError("index publication belongs to another path")
        with self._mutation_scope(create_lock=False) as directory:
            if directory is not None:
                status = os.fstat(directory)
                if (status.st_dev, status.st_ino) != receipt.parent_identity:
                    return False
            try:
                if directory is None:
                    descriptor, parent = _open_file_no_follow(self.path)
                else:
                    descriptor = os.open(
                        self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                        dir_fd=directory,
                    )
                    parent = directory
            except FileNotFoundError:
                return False
            try:
                opened = os.fstat(descriptor)
                if (not _regular_file_status_no_follow(opened)
                        or (opened.st_dev, opened.st_ino) != receipt.identity
                        or opened.st_size > _MAX_CONVERSATION_INDEX_BYTES):
                    return False
                chunks: list[bytes] = []
                remaining = opened.st_size
                while remaining:
                    chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                    if not chunk:
                        return False
                    chunks.append(chunk)
                    remaining -= len(chunk)
                state = self._decode_state(b"".join(chunks), preserve_corrupt=False)
                if (state.index_state != "fresh" or state.generation != receipt.generation
                        or state.sequence != receipt.sequence
                        or not _same_file_status(opened, os.fstat(descriptor))):
                    return False
                current = (os.stat(self.path.name, dir_fd=parent, follow_symlinks=False)
                           if parent >= 0 else self.path.lstat())
                if not _same_file_status(opened, current):
                    return False
                if parent >= 0:
                    os.unlink(self.path.name, dir_fd=parent)
                else:
                    self.path.unlink()
                return True
            finally:
                try:
                    os.close(descriptor)
                finally:
                    if parent >= 0 and directory is None:
                        os.close(parent)

    def _upsert_sync(self, item: IndexedProjection[P]) -> bool:
        return self._upsert_with_receipt_sync(item)[0]

    def _upsert_with_receipt_sync(
        self, item: IndexedProjection[P],
    ) -> tuple[bool, JsonIndexPublication | None]:
        require_revision(item.source_revision, name="source revision")
        with self._mutation_scope() as directory:
            state = self._read_state(preserve_corrupt=True, directory=directory)
            if item.source_revision <= state.tombstones.get(item.locator, -1):
                return False, None
            current = state.items.get(item.locator)
            if current is not None and item.source_revision < current.source_revision:
                return False, None
            state.items[item.locator] = item
            receipt = self._write_state(
                state.items,
                state.tombstones,
                generation=_writable_generation(state),
                sequence=state.sequence + 1,
                directory=directory,
            )
            return True, receipt

    def _delete_sync(
        self,
        locator: ConversationLocator,
        through_revision: int,
    ) -> bool:
        revision = require_revision(through_revision, name="deletion revision")
        with self._mutation_scope() as directory:
            state = self._read_state(preserve_corrupt=True, directory=directory)
            previous = state.tombstones.get(locator, -1)
            if revision < previous:
                return False
            state.tombstones[locator] = revision
            current = state.items.get(locator)
            if current is not None and current.source_revision <= revision:
                del state.items[locator]
            self._write_state(
                state.items,
                state.tombstones,
                generation=_writable_generation(state),
                sequence=state.sequence + 1,
                directory=directory,
            )
            return revision > previous

    def _get_sync(
        self,
        locator: ConversationLocator,
    ) -> IndexedProjection[P] | None:
        with self._lock:
            return self._read_state().items.get(locator)

    def _items_sync(self) -> tuple[IndexedProjection[P], ...]:
        with self._lock:
            return tuple(self._read_state().items.values())

    def _query_snapshot_sync(self, query: Q) -> ConversationIndexSnapshot[P]:
        with self._lock:
            state = self._read_state()
            items = tuple(self._query_items(query, tuple(state.items.values())))
        return ConversationIndexSnapshot(
            items=items,
            index_state=state.index_state,
            index_generation=state.generation,
            query_snapshot=f"{state.generation}:{state.sequence}",
        )

    def _replace_sync(
        self,
        replacement: tuple[IndexedProjection[P], ...],
    ) -> tuple[IndexedProjection[P], ...]:
        return self._replace_with_receipt_sync(replacement)[0]

    def _replace_with_receipt_sync(
        self, replacement: tuple[IndexedProjection[P], ...],
    ) -> tuple[tuple[IndexedProjection[P], ...], JsonIndexPublication]:
        with self._mutation_scope() as directory:
            state = self._read_state(preserve_corrupt=True, directory=directory)
            items = {
                item.locator: item
                for item in replacement
                if item.source_revision > state.tombstones.get(item.locator, -1)
            }
            receipt = self._write_state(
                items,
                state.tombstones,
                generation=_new_generation(),
                sequence=0,
                directory=directory,
            )
            assert receipt is not None
            return tuple(items.values()), receipt

    @contextmanager
    def _mutation_scope(self, *, create_lock: bool = True) -> Iterator[int | None]:
        """Serialize legacy writers with the retained-root cache transaction.

        Contention is reported before reading or publishing the index. Do not
        wait on a lock that an owned transaction may retain for cleanup.
        """
        if not self._writable:
            raise RuntimeError("read-only conversation index cannot be modified")
        with self._lock:
            if os.name == "posix" and hasattr(os, "O_DIRECTORY"):
                if create_lock:
                    self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                directory = os.open(
                    self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                )
                try:
                    with journal_file_lock_at(
                        directory, self.path.name + ".lock", "exclusive",
                        blocking=False, create=create_lock,
                    ):
                        yield directory
                finally:
                    os.close(directory)
            else:
                with journal_file_lock(self.path, "exclusive", blocking=False, create=create_lock):
                    yield None

    def _read_state(
        self,
        *, preserve_corrupt: bool = False,
        directory: int | None = None,
    ) -> _JsonConversationIndexState[P]:
        try:
            content = _read_stable_regular_file(
                self.path,
                max_bytes=_MAX_CONVERSATION_INDEX_BYTES,
                directory=directory,
            )
        except FileNotFoundError:
            return _JsonConversationIndexState(
                items={},
                tombstones={},
                generation="unavailable",
                sequence=0,
                index_state="unavailable",
            )
        except OSError:
            return _JsonConversationIndexState(
                items={},
                tombstones={},
                generation="stale",
                sequence=0,
                index_state="stale",
            )
        # Read paths must not rename an index concurrently owned by a writer.
        # Quarantine is permitted only inside the mutation scope above.
        return self._decode_state(content, preserve_corrupt=preserve_corrupt, directory=directory)

    def _decode_state(
        self, content: bytes, *, preserve_corrupt: bool = True,
        directory: int | None = None,
    ) -> _JsonConversationIndexState[P]:
        try:
            payload = json.loads(content.decode("utf-8"))
            if (
                not isinstance(payload, Mapping)
                or payload.get("version") != self.version
            ):
                raise ValueError("conversation index version is unsupported")
            items = self._decode_items(payload.get("items"))
            tombstones = self._decode_tombstones(payload.get("tombstones"))
            raw_generation = payload.get("index_generation")
            generation = (
                raw_generation
                if isinstance(raw_generation, str) and raw_generation
                else _legacy_generation(items)
            )
            raw_sequence = payload.get("index_sequence", 0)
            if type(raw_sequence) is not int or raw_sequence < 0:
                raise ValueError("conversation index sequence is invalid")
        except Exception:
            if self._writable and preserve_corrupt:
                self._preserve_corrupt(directory=directory)
            return _JsonConversationIndexState(
                items={},
                tombstones={},
                generation="stale",
                sequence=0,
                index_state="stale",
            )
        return _JsonConversationIndexState(
            items=items,
            tombstones=tombstones,
            generation=generation,
            sequence=raw_sequence,
            index_state="fresh",
        )

    def _decode_items(
        self,
        raw_items: object,
    ) -> dict[ConversationLocator, IndexedProjection[P]]:
        if not isinstance(raw_items, list):
            raise ValueError("conversation index items are invalid")
        items: dict[ConversationLocator, IndexedProjection[P]] = {}
        for raw in raw_items:
            if not isinstance(raw, Mapping):
                raise ValueError("conversation index item is invalid")
            locator = _decode_locator(raw)
            revision = require_revision(
                raw.get("source_revision"),
                name="source revision",
            )
            raw_projection = raw.get("projection")
            if not isinstance(raw_projection, Mapping):
                raise ValueError("conversation index projection is invalid")
            projection = self.codec.decode(cast(Mapping[str, object], raw_projection))
            items[locator] = IndexedProjection(locator, revision, projection)
        return items

    def _decode_tombstones(
        self,
        raw_tombstones: object,
    ) -> dict[ConversationLocator, int]:
        if raw_tombstones is None:
            return {}
        if not isinstance(raw_tombstones, list):
            raise ValueError("conversation index tombstones are invalid")
        tombstones: dict[ConversationLocator, int] = {}
        for raw in raw_tombstones:
            if not isinstance(raw, Mapping):
                raise ValueError("conversation index tombstone is invalid")
            tombstones[_decode_locator(raw)] = require_revision(
                raw.get("through_revision"),
                name="deletion revision",
            )
        return tombstones

    def _write_state(
        self,
        items: Mapping[ConversationLocator, IndexedProjection[P]],
        tombstones: Mapping[ConversationLocator, int],
        *,
        generation: str,
        sequence: int,
        target: RootedFile | None = None,
        directory: int | None = None,
    ) -> JsonIndexPublication | None:
        if not self._writable:
            raise RuntimeError("read-only conversation index cannot be modified")
        payload = {
            "version": self.version,
            "generated_at": _now_iso(),
            "index_generation": generation,
            "index_sequence": sequence,
            "items": [
                {
                    **_encode_locator(item.locator),
                    "source_revision": item.source_revision,
                    "projection": dict(self.codec.encode(item.projection)),
                }
                for item in sorted(items.values(), key=_indexed_projection_key)
            ],
            "tombstones": [
                {
                    **_encode_locator(locator),
                    "through_revision": revision,
                }
                for locator, revision in sorted(tombstones.items())
            ],
        }
        if target is not None:
            encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            if len(encoded) > _MAX_CONVERSATION_INDEX_BYTES:
                raise ValueError("conversation index exceeds the bounded cache size")
            target.atomic_write(encoded)
            return None
        if directory is not None:
            name = f".{self.path.name}.{secrets.token_hex(16)}.tmp"
            descriptor = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600, dir_fd=directory,
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
                    stream.flush()
                    opened, parent = os.fstat(stream.fileno()), os.fstat(directory)
                    receipt = JsonIndexPublication(
                        self.path, generation, sequence, (opened.st_dev, opened.st_ino),
                        (parent.st_dev, parent.st_ino),
                    )
                os.replace(name, self.path.name, src_dir_fd=directory, dst_dir_fd=directory)
                return receipt
            except BaseException:
                with suppress(FileNotFoundError):
                    os.unlink(name, dir_fd=directory)
                raise
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            # A private exclusive temporary file avoids following a pre-existing
            # predictable .tmp link and keeps the published cache owner-only.
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temp_path = Path(stream.name)
                stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
                stream.flush()
                opened = os.fstat(stream.fileno())
                receipt = JsonIndexPublication(
                    self.path, generation, sequence, (opened.st_dev, opened.st_ino),
                )
            temp_path.replace(self.path)
            return receipt
        except BaseException:
            if temp_path is not None:
                with suppress(FileNotFoundError):
                    temp_path.unlink()
            raise

    def _preserve_corrupt(self, *, directory: int | None = None) -> Path | None:
        target = self.path.with_name(f"{self.path.name}.corrupt-{time_ns()}")
        try:
            if directory is None:
                self.path.replace(target)
            else:
                os.replace(self.path.name, target.name, src_dir_fd=directory, dst_dir_fd=directory)
        except Exception:
            return None
        return target


@dataclass
class _JsonConversationIndexState(Generic[P]):
    items: dict[ConversationLocator, IndexedProjection[P]]
    tombstones: dict[ConversationLocator, int]
    generation: str
    sequence: int
    index_state: ConversationIndexState


def _read_stable_regular_file(path: Path, *, max_bytes: int, directory: int | None = None) -> bytes:
    return _read_stable_regular_snapshot(path, max_bytes=max_bytes, directory=directory)[0]


def _read_stable_regular_snapshot(
    path: Path, *, max_bytes: int, directory: int | None = None,
) -> tuple[bytes, os.stat_result]:
    before = (path.lstat() if directory is None else
              os.stat(path.name, dir_fd=directory, follow_symlinks=False))
    if not _regular_file_status_no_follow(before):
        raise OSError("conversation index must be a direct regular file")
    if before.st_size > max_bytes:
        raise OSError("conversation index exceeds the read limit")
    descriptor = -1
    parent_descriptor = -1
    try:
        if directory is None:
            descriptor, parent_descriptor = _open_file_no_follow(path)
        else:
            descriptor = os.open(
                path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=directory,
            )
        opened = os.fstat(descriptor)
        if not _same_file_status(before, opened):
            raise OSError("conversation index identity changed")
        remaining = opened.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise OSError("conversation index was truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        current = (path.lstat() if directory is None else
                   os.stat(path.name, dir_fd=directory, follow_symlinks=False))
        if not _same_file_status(before, after) or not _same_file_status(
            before, current
        ):
            raise OSError("conversation index changed while reading")
        return b"".join(chunks), opened
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def _open_file_no_follow(path: Path) -> tuple[int, int]:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    if os.name != "nt" and directory_flag:
        parent_flags = os.O_RDONLY | directory_flag
        parent_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        parent = os.open(path.parent, parent_flags)
        try:
            return os.open(path.name, flags, dir_fd=parent), parent
        except BaseException:
            os.close(parent)
            raise
    return os.open(path, flags), -1


def _regular_file_status_no_follow(value: os.stat_result) -> bool:
    return stat.S_ISREG(value.st_mode) and not (
        stat.S_ISLNK(value.st_mode)
        or bool(
            getattr(value, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    )


def _same_file_status(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_size,
        right.st_mtime_ns,
        right.st_ctime_ns,
    )


def _new_generation() -> str:
    return secrets.token_hex(16)


def _writable_generation(state: _JsonConversationIndexState[P]) -> str:
    if state.index_state == "fresh":
        return state.generation
    return _new_generation()


def _legacy_generation(
    items: Mapping[ConversationLocator, IndexedProjection[P]],
) -> str:
    digest = json.dumps(
        [
            (
                item.locator.provider_id,
                item.locator.key.namespace,
                item.locator.key.conversation_id,
                item.source_revision,
            )
            for item in sorted(items.values(), key=_indexed_projection_key)
        ],
        separators=(",", ":"),
    )
    return "legacy-" + hashlib.sha256(digest.encode("utf-8")).hexdigest()[:24]


def _encode_locator(locator: ConversationLocator) -> dict[str, str]:
    return {
        "provider_id": locator.provider_id,
        "namespace": locator.key.namespace,
        "conversation_id": locator.key.conversation_id,
    }


def _decode_locator(value: Mapping[str, object]) -> ConversationLocator:
    provider_id = value.get("provider_id")
    namespace = value.get("namespace")
    conversation_id = value.get("conversation_id")
    if not all(
        isinstance(item, str) and item
        for item in (
            provider_id,
            namespace,
            conversation_id,
        )
    ):
        raise ValueError("conversation index locator is invalid")
    return ConversationLocator(
        cast(str, provider_id),
        ConversationKey(cast(str, namespace), cast(str, conversation_id)),
    )


def _indexed_projection_key(item: IndexedProjection[P]):
    return item.locator


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "FunctionalProjectionCodec",
    "JsonConversationIndex",
    "JsonProjectionIndex",
    "ProjectionCodec",
    "ProjectionIndexSnapshot",
]
