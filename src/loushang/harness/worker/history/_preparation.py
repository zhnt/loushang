"""Non-authoritative preparation values and read-only, fixed five-stream joins."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from hashlib import sha256
from typing import ClassVar, Generic, Self, TypeVar, cast

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from ._base_codec import _BaseWireMethods, _unchanged
from ._no_effect import _NoEffectArchiveMethods
from ._prepared import _PreparedMethods, _SemanticBaseV2
from ._v2_names import (
    NO_EFFECT_ARCHIVE_NAME,
    PREPARATION_ARTIFACT_NAMES,
    PREPARATION_INTENT_NAME,
    PREPARED_INDEX_NAME,
    PRODUCT_OWNER_INDEX_NAME,
    semantic_base_name,
    stream_cutover_name,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_INTENT_BYTES = 8192
_MAX_BASE_BYTES = 128 * 1024 * 1024
_MAX_STREAM_BYTES = 1024 * 1024
_MAX_INDEX_BYTES = 4096


class _PreparationIntentMethods(_BaseWireMethods):
    __slots__ = ()

    scope_id: str
    store_id: str
    checkpoint_digest: str
    index_digest: str
    artifact_digests: tuple[tuple[str, str], ...]
    record_digest: str
    version: int = 2

    _prepared_type: ClassVar[type[_PreparedMethods]]
    _wire_label = "Coding Worker V2 preparation intent"
    _wire_lists = ("artifactDigests",)
    _wire_max_bytes = _MAX_INTENT_BYTES

    @classmethod
    def _make_wire_schema(cls) -> RecordSchema:
        return RecordSchema.for_dataclass(
            cls,
            _unchanged,
            RecordField(
                "artifact_digests",
                encoder=lambda xs: [list(x) for x in xs],
                decoder=lambda xs: tuple(
                    tuple(x) if type(x) is list else x for x in xs
                ),
            ),
        )

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.checkpoint_digest) is not str
            or _DIGEST.fullmatch(self.checkpoint_digest) is None
            or type(self.index_digest) is not str
            or _DIGEST.fullmatch(self.index_digest) is None
            or type(self.artifact_digests) is not tuple
            or tuple(name for name, _digest in self.artifact_digests)
            not in (
                PREPARATION_ARTIFACT_NAMES,
                (*PREPARATION_ARTIFACT_NAMES, NO_EFFECT_ARCHIVE_NAME),
            )
            or any(
                type(digest) is not str or _DIGEST.fullmatch(digest) is None
                for _name, digest in self.artifact_digests
            )
            or self.artifact_digests[0][1] != self.index_digest
            or type(self.version) is not int
            or self.version != 2
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Coding Worker V2 preparation intent is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "artifactDigests": [list(item) for item in self.artifact_digests],
            "checkpointDigest": self.checkpoint_digest,
            "indexDigest": self.index_digest,
            "scopeId": self.scope_id,
            "storeId": self.store_id,
            "version": self.version,
        }

    @classmethod
    def from_prepared(cls, prepared: _PreparedMethods) -> Self:
        if type(prepared) is not cls._prepared_type:
            raise ValueError("Coding Worker V2 preparation requires typed sources")
        artifacts = _artifact_bytes(prepared)
        digests = tuple((name, sha256(raw).hexdigest()) for name, raw in artifacts)
        index = prepared.index
        unsigned = {
            "artifactDigests": [list(item) for item in digests],
            "checkpointDigest": index.checkpoint_digest,
            "indexDigest": sha256(index.to_bytes()).hexdigest(),
            "scopeId": index.scope_id,
            "storeId": index.store_id,
            "version": 2,
        }
        return cast(Callable[..., Self], cls)(
            scope_id=index.scope_id,
            store_id=index.store_id,
            checkpoint_digest=index.checkpoint_digest,
            index_digest=sha256(index.to_bytes()).hexdigest(),
            artifact_digests=digests,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )


def _artifact_bytes(
    prepared: _PreparedMethods,
) -> tuple[tuple[str, bytes], ...]:
    bases = cast(tuple[_SemanticBaseV2, ...], prepared.semantic_bases)
    result: list[tuple[str, bytes]] = [(PREPARED_INDEX_NAME, prepared.index.to_bytes())]
    for stream, base in zip(prepared.streams, bases, strict=True):
        result.append((semantic_base_name(stream.stem), base.to_bytes()))
        result.append((stream_cutover_name(stream.stem), stream.to_bytes()))
    if prepared.no_effect_archive is not None:
        result.append((NO_EFFECT_ARCHIVE_NAME, prepared.no_effect_archive.to_bytes()))
    return tuple(result)


def _optional_bytes(rooted: RootedFile, name: str, *, limit: int) -> bytes | None:
    try:
        return rooted.sibling(name).read_bytes(max_bytes=limit)
    except FileNotFoundError:
        return None


def _artifact_limit(
    name: str,
    *,
    max_index_bytes: int = _MAX_INDEX_BYTES,
    max_base_bytes: int = _MAX_BASE_BYTES,
    max_stream_bytes: int = _MAX_STREAM_BYTES,
) -> int:
    if name == PREPARED_INDEX_NAME:
        return max_index_bytes
    return (
        max_base_bytes
        if name.endswith(".base.json") or name == NO_EFFECT_ARCHIVE_NAME
        else max_stream_bytes
    )


_PreparedT = TypeVar("_PreparedT", bound=_PreparedMethods, covariant=True)
_IntentT = TypeVar("_IntentT", bound=_PreparationIntentMethods, covariant=True)


@dataclass(frozen=True, slots=True)
class PreparationHistory(Generic[_PreparedT, _IntentT]):
    """Intent-owned preparation artifacts, without the Product owner transition."""

    prepared_type: type[_PreparedT]
    intent_type: type[_IntentT]
    error_type: type[RuntimeError]

    def _require_no_owner(self, rooted: RootedFile, *, max_index_bytes: int) -> None:
        if (
            _optional_bytes(rooted, PRODUCT_OWNER_INDEX_NAME, limit=max_index_bytes)
            is not None
        ):
            raise self.error_type("coding_worker_v2_owner_already_present")

    def _require_no_artifacts(
        self,
        rooted: RootedFile,
        *,
        max_index_bytes: int,
        max_base_bytes: int,
        max_stream_bytes: int,
    ) -> None:
        if any(
            _optional_bytes(
                rooted,
                name,
                limit=_artifact_limit(
                    name,
                    max_index_bytes=max_index_bytes,
                    max_base_bytes=max_base_bytes,
                    max_stream_bytes=max_stream_bytes,
                ),
            )
            is not None
            for name in (*PREPARATION_ARTIFACT_NAMES, NO_EFFECT_ARCHIVE_NAME)
        ):
            raise self.error_type("coding_worker_v2_orphan_preparation")

    def stage(
        self,
        rooted: RootedFile,
        *,
        prepared: _PreparedMethods,
        max_intent_bytes: int = _MAX_INTENT_BYTES,
        max_base_bytes: int = _MAX_BASE_BYTES,
        max_stream_bytes: int = _MAX_STREAM_BYTES,
        max_index_bytes: int = _MAX_INDEX_BYTES,
    ) -> _IntentT:
        intent = self.intent_type.from_prepared(prepared)
        artifact_limit = partial(
            _artifact_limit,
            max_index_bytes=max_index_bytes,
            max_base_bytes=max_base_bytes,
            max_stream_bytes=max_stream_bytes,
        )
        self._require_no_owner(rooted, max_index_bytes=max_index_bytes)
        existing_intent = _optional_bytes(
            rooted, name=PREPARATION_INTENT_NAME, limit=max_intent_bytes
        )
        if existing_intent is None:
            self._require_no_artifacts(
                rooted,
                max_index_bytes=max_index_bytes,
                max_base_bytes=max_base_bytes,
                max_stream_bytes=max_stream_bytes,
            )
            rooted.sibling(PREPARATION_INTENT_NAME).create_new(intent.to_bytes())
        elif existing_intent != intent.to_bytes():
            raise self.error_type("coding_worker_v2_preparation_changed")
        for name, raw in _artifact_bytes(prepared):
            existing = _optional_bytes(rooted, name=name, limit=artifact_limit(name))
            if existing is None:
                rooted.sibling(name).create_new(raw)
            elif existing != raw:
                raise self.error_type("coding_worker_v2_preparation_changed")
        readback = self.read(
            rooted,
            max_intent_bytes=max_intent_bytes,
            max_base_bytes=max_base_bytes,
            max_stream_bytes=max_stream_bytes,
            max_index_bytes=max_index_bytes,
        )
        if readback != prepared:
            raise self.error_type("coding_worker_v2_preparation_changed")
        return intent

    def rollback(
        self,
        rooted: RootedFile,
        *,
        max_intent_bytes: int = _MAX_INTENT_BYTES,
        max_base_bytes: int = _MAX_BASE_BYTES,
        max_stream_bytes: int = _MAX_STREAM_BYTES,
        max_index_bytes: int = _MAX_INDEX_BYTES,
    ) -> bool:
        artifact_limit = partial(
            _artifact_limit,
            max_index_bytes=max_index_bytes,
            max_base_bytes=max_base_bytes,
            max_stream_bytes=max_stream_bytes,
        )
        self._require_no_owner(rooted, max_index_bytes=max_index_bytes)
        raw_intent = _optional_bytes(
            rooted, name=PREPARATION_INTENT_NAME, limit=max_intent_bytes
        )
        if raw_intent is None:
            self._require_no_artifacts(
                rooted,
                max_index_bytes=max_index_bytes,
                max_base_bytes=max_base_bytes,
                max_stream_bytes=max_stream_bytes,
            )
            return False
        intent = self.intent_type.from_bytes(raw_intent)
        if (
            NO_EFFECT_ARCHIVE_NAME not in dict(intent.artifact_digests)
            and _optional_bytes(
                rooted, name=NO_EFFECT_ARCHIVE_NAME, limit=max_base_bytes
            )
            is not None
        ):
            raise self.error_type("coding_worker_v2_preparation_changed")
        targets: list[tuple[str, tuple[int, int]]] = []
        for name, digest in intent.artifact_digests:
            target = rooted.sibling(name)
            try:
                before = target.stat()
                raw = target.read_bytes(max_bytes=artifact_limit(name))
                after = target.stat()
            except FileNotFoundError:
                continue
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ) or sha256(raw).hexdigest() != digest:
                raise self.error_type("coding_worker_v2_preparation_changed")
            targets.append((name, (after.st_dev, after.st_ino)))
        for name, identity in targets:
            rooted.sibling(name).unlink_owned(identity)
        intent_file = rooted.sibling(PREPARATION_INTENT_NAME)
        before = intent_file.stat()
        if intent_file.read_bytes(max_bytes=max_intent_bytes) != raw_intent:
            raise self.error_type("coding_worker_v2_preparation_changed")
        after = intent_file.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise self.error_type("coding_worker_v2_preparation_changed")
        intent_file.unlink_owned((after.st_dev, after.st_ino))
        return True

    def read(
        self,
        rooted: RootedFile,
        *,
        max_intent_bytes: int = _MAX_INTENT_BYTES,
        max_base_bytes: int = _MAX_BASE_BYTES,
        max_stream_bytes: int = _MAX_STREAM_BYTES,
        max_index_bytes: int = _MAX_INDEX_BYTES,
    ) -> _PreparedT | None:
        """Verify all staged bytes; this never selects V2 as Product authority."""

        raw_intent = _optional_bytes(
            rooted, name=PREPARATION_INTENT_NAME, limit=max_intent_bytes
        )
        if raw_intent is None:
            self._require_no_artifacts(
                rooted,
                max_index_bytes=max_index_bytes,
                max_base_bytes=max_base_bytes,
                max_stream_bytes=max_stream_bytes,
            )
            return None
        intent = self.intent_type.from_bytes(raw_intent)
        archive_named = NO_EFFECT_ARCHIVE_NAME in dict(intent.artifact_digests)
        archive_present = (
            _optional_bytes(rooted, name=NO_EFFECT_ARCHIVE_NAME, limit=max_base_bytes)
            is not None
        )
        if archive_named != archive_present:
            raise self.error_type("coding_worker_v2_preparation_changed")
        artifacts: dict[str, bytes] = {}
        for name, digest in intent.artifact_digests:
            raw = _optional_bytes(
                rooted,
                name=name,
                limit=_artifact_limit(
                    name,
                    max_index_bytes=max_index_bytes,
                    max_base_bytes=max_base_bytes,
                    max_stream_bytes=max_stream_bytes,
                ),
            )
            if raw is None:
                raise self.error_type("coding_worker_v2_preparation_incomplete")
            if sha256(raw).hexdigest() != digest:
                raise self.error_type("coding_worker_v2_preparation_changed")
            artifacts[name] = raw
        index = self.prepared_type._index_type.from_bytes(
            artifacts[PREPARED_INDEX_NAME]
        )
        bases = (
            self.prepared_type._opt_in_type.from_bytes(
                artifacts[semantic_base_name("worker-opt-in")]
            ),
            self.prepared_type._receipt_type.from_bytes(
                artifacts[semantic_base_name("worker-activation-receipts")]
            ),
            self.prepared_type._activation_type.from_bytes(
                artifacts[semantic_base_name("worker-activation-state")]
            ),
            self.prepared_type._gate_type.from_bytes(
                artifacts[semantic_base_name("worker-start-gates")]
            ),
            self.prepared_type._supervisor_type.from_bytes(
                artifacts[semantic_base_name("worker-supervisor")]
            ),
        )
        streams = tuple(
            self.prepared_type._stream_type.from_bytes(
                artifacts[stream_cutover_name(stem)]
            )
            for stem in (
                "worker-opt-in",
                "worker-activation-receipts",
                "worker-activation-state",
                "worker-start-gates",
                "worker-supervisor",
            )
        )
        prepared = cast(Callable[..., _PreparedT], self.prepared_type)(
            index=index,
            streams=streams,
            semantic_bases=bases,
            no_effect_archive=(
                None
                if NO_EFFECT_ARCHIVE_NAME not in artifacts
                else self.prepared_type._archive_type.from_bytes(
                    artifacts[NO_EFFECT_ARCHIVE_NAME]
                )
            ),
        )
        if (
            intent.scope_id != index.scope_id
            or intent.store_id != index.store_id
            or intent.checkpoint_digest != index.checkpoint_digest
            or intent.index_digest != sha256(index.to_bytes()).hexdigest()
        ):
            raise self.error_type("coding_worker_v2_preparation_changed")
        return prepared

    def read_bound_archive(self, rooted: RootedFile) -> _NoEffectArchiveMethods | None:
        """Read only the archive selected by the committed Product owner index."""
        owner = self.prepared_type._index_type.from_bytes(
            rooted.sibling(PRODUCT_OWNER_INDEX_NAME).read_bytes(max_bytes=4096)
        )
        prepared = self.read(rooted)
        if prepared is None or prepared.index != owner:
            raise ValueError("Coding Worker no-effect V2 archive owner differs")
        return prepared.no_effect_archive
