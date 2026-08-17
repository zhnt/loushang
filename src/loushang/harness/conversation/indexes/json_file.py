from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
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

P = TypeVar("P")
Q = TypeVar("Q")


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
    ) -> None:
        if version < 1:
            raise ValueError("conversation index version must be positive")
        self.path = Path(path)
        self.version = version
        self.codec = codec
        self._query_items = query_items
        self._lock = Lock()

    async def upsert(self, item: IndexedProjection[P]) -> bool:
        return await asyncio.to_thread(self._upsert_sync, item)

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

    def _upsert_sync(self, item: IndexedProjection[P]) -> bool:
        require_revision(item.source_revision, name="source revision")
        with self._lock:
            state = self._read_state()
            if item.source_revision <= state.tombstones.get(item.locator, -1):
                return False
            current = state.items.get(item.locator)
            if current is not None and item.source_revision < current.source_revision:
                return False
            state.items[item.locator] = item
            self._write_state(
                state.items,
                state.tombstones,
                generation=_writable_generation(state),
                sequence=state.sequence + 1,
            )
            return True

    def _delete_sync(
        self,
        locator: ConversationLocator,
        through_revision: int,
    ) -> bool:
        revision = require_revision(through_revision, name="deletion revision")
        with self._lock:
            state = self._read_state()
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
        with self._lock:
            state = self._read_state()
            items = {
                item.locator: item
                for item in replacement
                if item.source_revision > state.tombstones.get(item.locator, -1)
            }
            self._write_state(
                items,
                state.tombstones,
                generation=_new_generation(),
                sequence=0,
            )
            return tuple(items.values())

    def _read_state(
        self,
    ) -> _JsonConversationIndexState[P]:
        if not self.path.exists():
            return _JsonConversationIndexState(
                items={},
                tombstones={},
                generation="unavailable",
                sequence=0,
                index_state="unavailable",
            )
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
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
            self._preserve_corrupt()
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
    ) -> None:
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

    def _preserve_corrupt(self) -> Path | None:
        if not self.path.exists():
            return None
        target = self.path.with_name(f"{self.path.name}.corrupt-{time_ns()}")
        try:
            self.path.replace(target)
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
