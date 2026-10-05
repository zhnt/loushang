"""Strict immutable segment manifest for Product-owned Worker journals.

This is a format and rooted read/write primitive. Product owners still decide
when a segment may be sealed and whether recovered history admits a Worker.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_STREAM = re.compile(r"[a-z][a-z0-9-]{1,63}\Z")
_STEM = re.compile(r"[a-z][a-z0-9-]{1,63}\Z")
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_GENERATIONS = 65536
_MAX_DIRECTORY_ENTRIES = 131072


class CodingWorkerHistorySegmentError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerSealedSegmentV1:
    generation: int
    first_revision: int
    last_revision: int
    byte_count: int
    digest: str

    def __post_init__(self) -> None:
        if (
            type(self.generation) is not int
            or self.generation < 0
            or type(self.first_revision) is not int
            or self.first_revision < 1
            or type(self.last_revision) is not int
            or self.last_revision < self.first_revision
            or type(self.byte_count) is not int
            or self.byte_count < 1
            or type(self.digest) is not str
            or _DIGEST.fullmatch(self.digest) is None
        ):
            raise ValueError("Worker sealed segment is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "byteCount": self.byte_count,
            "digest": self.digest,
            "firstRevision": self.first_revision,
            "generation": self.generation,
            "lastRevision": self.last_revision,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingWorkerSealedSegmentV1:
        if type(value) is not dict or set(value) != {
            "byteCount",
            "digest",
            "firstRevision",
            "generation",
            "lastRevision",
        }:
            raise ValueError("Worker sealed segment fields are invalid")
        return cls(
            generation=value["generation"],
            first_revision=value["firstRevision"],
            last_revision=value["lastRevision"],
            byte_count=value["byteCount"],
            digest=value["digest"],
        )


@dataclass(frozen=True, slots=True)
class CodingWorkerSegmentManifestV1:
    stream_id: str
    active_generation: int
    sealed: tuple[CodingWorkerSealedSegmentV1, ...]

    def __post_init__(self) -> None:
        if (
            type(self.stream_id) is not str
            or _STREAM.fullmatch(self.stream_id) is None
            or type(self.active_generation) is not int
            or not 1 <= self.active_generation <= _MAX_GENERATIONS
            or type(self.sealed) is not tuple
            or len(self.sealed) != self.active_generation
        ):
            raise ValueError("Worker segment manifest is invalid")
        expected_revision = 1
        for generation, segment in enumerate(self.sealed):
            if (
                type(segment) is not CodingWorkerSealedSegmentV1
                or segment.generation != generation
                or segment.first_revision != expected_revision
            ):
                raise ValueError("Worker segment manifest chain is invalid")
            expected_revision = segment.last_revision + 1

    @property
    def last_sealed_revision(self) -> int:
        return self.sealed[-1].last_revision

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "activeGeneration": self.active_generation,
                "sealed": [segment.to_dict() for segment in self.sealed],
                "streamId": self.stream_id,
                "version": 1,
            }
        )

    @classmethod
    def from_bytes(cls, raw: bytes, *, stream_id: str) -> CodingWorkerSegmentManifestV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_MANIFEST_BYTES:
            raise CodingWorkerHistorySegmentError(
                "coding_worker_segment_manifest_invalid"
            )
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value) != {"activeGeneration", "sealed", "streamId", "version"}
                or value["version"] != 1
                or value["streamId"] != stream_id
                or type(value["sealed"]) is not list
            ):
                raise ValueError("Worker segment manifest fields changed")
            manifest = cls(
                stream_id=value["streamId"],
                active_generation=value["activeGeneration"],
                sealed=tuple(
                    CodingWorkerSealedSegmentV1.from_dict(item)
                    for item in value["sealed"]
                ),
            )
            if manifest.to_bytes() != raw:
                raise ValueError("Worker segment manifest encoding changed")
            return manifest
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise CodingWorkerHistorySegmentError(
                "coding_worker_segment_manifest_invalid"
            ) from exc


@dataclass(frozen=True, slots=True)
class CodingWorkerSegmentedHistoryV1:
    manifest: CodingWorkerSegmentManifestV1 | None
    segments: tuple[bytes, ...]

    @property
    def active_raw(self) -> bytes:
        return self.segments[-1]

    @property
    def active_generation(self) -> int:
        return 0 if self.manifest is None else self.manifest.active_generation

    @property
    def last_sealed_revision(self) -> int:
        return 0 if self.manifest is None else self.manifest.last_sealed_revision


def _segment_name(stem: str, generation: int) -> str:
    return f"{stem}.jsonl" if generation == 0 else f"{stem}.g{generation:08d}.jsonl"


def read_coding_worker_segmented_history(
    rooted: RootedFile,
    *,
    stem: str,
    stream_id: str,
    max_segment_bytes: int,
) -> CodingWorkerSegmentedHistoryV1:
    """Read exact sealed bytes and the current active segment under one lock."""

    if (
        type(stem) is not str
        or _STEM.fullmatch(stem) is None
        or type(stream_id) is not str
        or _STREAM.fullmatch(stream_id) is None
        or type(max_segment_bytes) is not int
        or max_segment_bytes < 1
    ):
        raise ValueError("Worker segmented history input is invalid")
    names, complete = rooted.scan_sibling_names(limit=_MAX_DIRECTORY_ENTRIES)
    if not complete:
        raise CodingWorkerHistorySegmentError(
            "coding_worker_segment_inventory_capacity"
        )
    manifest_name = stem + ".segments.json"
    try:
        raw_manifest = rooted.sibling(manifest_name).read_bytes(
            max_bytes=_MAX_MANIFEST_BYTES
        )
    except FileNotFoundError:
        manifest = None
    except OSError as exc:
        raise CodingWorkerHistorySegmentError(
            "coding_worker_segment_manifest_invalid"
        ) from exc
    else:
        manifest = CodingWorkerSegmentManifestV1.from_bytes(
            raw_manifest, stream_id=stream_id
        )
    active = 0 if manifest is None else manifest.active_generation
    expected_names = {manifest_name} if manifest is not None else set()
    expected_names.add(stem + ".jsonl.lock")
    expected_names.update(_segment_name(stem, index) for index in range(active + 1))
    actual = {
        name
        for name in names
        if name.casefold().startswith((stem + ".", "." + stem + "."))
    }
    if not actual <= expected_names:
        raise CodingWorkerHistorySegmentError("coding_worker_segment_orphan")
    segments = []
    for generation in range(active + 1):
        name = _segment_name(stem, generation)
        try:
            raw = rooted.sibling(name).read_bytes(max_bytes=max_segment_bytes)
        except FileNotFoundError:
            if generation != active or manifest is not None:
                code = (
                    "coding_worker_sealed_segment_missing"
                    if generation != active
                    else "coding_worker_segment_active_missing"
                )
                raise CodingWorkerHistorySegmentError(code) from None
            if stem + ".jsonl.lock" in names:
                raise CodingWorkerHistorySegmentError(
                    "coding_worker_segment_initial_missing"
                ) from None
            raw = b""
        except OSError as exc:
            code = (
                "coding_worker_sealed_segment_changed"
                if generation < active
                else "coding_worker_segment_capacity"
            )
            raise CodingWorkerHistorySegmentError(code) from exc
        if manifest is not None and generation < active:
            sealed = manifest.sealed[generation]
            if (
                len(raw) != sealed.byte_count
                or sha256(raw).hexdigest() != sealed.digest
            ):
                raise CodingWorkerHistorySegmentError(
                    "coding_worker_sealed_segment_changed"
                )
        segments.append(raw)
    return CodingWorkerSegmentedHistoryV1(manifest=manifest, segments=tuple(segments))


def seal_coding_worker_active_segment(
    rooted: RootedFile,
    *,
    stem: str,
    stream_id: str,
    history: CodingWorkerSegmentedHistoryV1,
    last_revision: int,
) -> CodingWorkerSegmentManifestV1:
    """Publish a new active generation without rewriting the sealed bytes."""

    if (
        type(history) is not CodingWorkerSegmentedHistoryV1
        or type(stem) is not str
        or _STEM.fullmatch(stem) is None
        or type(stream_id) is not str
        or _STREAM.fullmatch(stream_id) is None
        or (history.manifest is not None and history.manifest.stream_id != stream_id)
        or not history.active_raw
        or type(last_revision) is not int
        or last_revision <= history.last_sealed_revision
        or history.active_generation >= _MAX_GENERATIONS
    ):
        raise CodingWorkerHistorySegmentError("coding_worker_segment_seal_invalid")
    segment = CodingWorkerSealedSegmentV1(
        generation=history.active_generation,
        first_revision=history.last_sealed_revision + 1,
        last_revision=last_revision,
        byte_count=len(history.active_raw),
        digest=sha256(history.active_raw).hexdigest(),
    )
    manifest = CodingWorkerSegmentManifestV1(
        stream_id=stream_id,
        active_generation=history.active_generation + 1,
        sealed=(
            (() if history.manifest is None else history.manifest.sealed) + (segment,)
        ),
    )
    if len(manifest.to_bytes()) > _MAX_MANIFEST_BYTES:
        raise CodingWorkerHistorySegmentError("coding_worker_segment_capacity")
    manifest_file = rooted.sibling(stem + ".segments.json")
    try:
        current_manifest = manifest_file.read_bytes(max_bytes=_MAX_MANIFEST_BYTES)
    except FileNotFoundError:
        current_manifest = None
    expected_manifest = (
        None if history.manifest is None else history.manifest.to_bytes()
    )
    if current_manifest != expected_manifest:
        raise CodingWorkerHistorySegmentError("coding_worker_segment_manifest_changed")
    try:
        current_active = rooted.sibling(
            _segment_name(stem, history.active_generation)
        ).read_bytes(max_bytes=max(1, len(history.active_raw)))
    except FileNotFoundError:
        current_active = None
    except OSError as exc:
        raise CodingWorkerHistorySegmentError(
            "coding_worker_segment_active_changed"
        ) from exc
    if current_active != history.active_raw:
        raise CodingWorkerHistorySegmentError("coding_worker_segment_active_changed")
    # Publish the empty successor durably before the manifest can name it.
    # Otherwise a later loss of a written active segment is indistinguishable
    # from an interrupted seal that never created the successor.
    try:
        rooted.sibling(_segment_name(stem, manifest.active_generation)).create_new(b"")
    except OSError as exc:
        raise CodingWorkerHistorySegmentError(
            "coding_worker_segment_active_changed"
        ) from exc
    manifest_file.atomic_write(manifest.to_bytes())
    return manifest


__all__ = [
    "CodingWorkerHistorySegmentError",
    "CodingWorkerSealedSegmentV1",
    "CodingWorkerSegmentManifestV1",
    "CodingWorkerSegmentedHistoryV1",
    "read_coding_worker_segmented_history",
    "seal_coding_worker_active_segment",
]
