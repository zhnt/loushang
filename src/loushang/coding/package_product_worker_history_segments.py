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
_MAX_HEAD_BYTES = 512
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


@dataclass(frozen=True, slots=True)
class CodingWorkerUncommittedActiveAppendV1:
    committed_history: CodingWorkerSegmentedHistoryV1
    appended_line: bytes


def _segment_name(stem: str, generation: int) -> str:
    return f"{stem}.jsonl" if generation == 0 else f"{stem}.g{generation:08d}.jsonl"


def _head_name(stem: str, generation: int) -> str:
    return (
        f"{stem}.head.json"
        if generation == 0
        else f"{stem}.g{generation:08d}.head.json"
    )


def _head_bytes(stream_id: str, generation: int, raw: bytes) -> bytes:
    return canonical_json_bytes(
        {
            "byteCount": len(raw),
            "digest": sha256(raw).hexdigest(),
            "generation": generation,
            "streamId": stream_id,
            "version": 1,
        }
    )


def _assert_head(
    rooted: RootedFile, *, stem: str, stream_id: str, generation: int, raw: bytes
) -> None:
    try:
        head = rooted.sibling(_head_name(stem, generation)).read_bytes(
            max_bytes=_MAX_HEAD_BYTES
        )
    except FileNotFoundError:
        raise CodingWorkerHistorySegmentError(
            "coding_worker_segment_head_missing"
        ) from None
    except OSError as exc:
        raise CodingWorkerHistorySegmentError(
            "coding_worker_segment_head_changed"
        ) from exc
    if head != _head_bytes(stream_id, generation, raw):
        raise CodingWorkerHistorySegmentError("coding_worker_segment_head_changed")


def initialize_coding_worker_active_head(
    rooted: RootedFile, *, stem: str, stream_id: str
) -> None:
    """Publish the empty first head only after this caller created the lock."""

    if (
        type(stem) is not str
        or _STEM.fullmatch(stem) is None
        or type(stream_id) is not str
        or _STREAM.fullmatch(stream_id) is None
    ):
        raise ValueError("Worker segment head input is invalid")
    if rooted.sibling(_segment_name(stem, 0)).read_bytes(max_bytes=1) != b"":
        raise CodingWorkerHistorySegmentError("coding_worker_segment_head_changed")
    rooted.sibling(_head_name(stem, 0)).create_new(_head_bytes(stream_id, 0, b""))


def commit_coding_worker_active_segment(
    rooted: RootedFile,
    *,
    stem: str,
    stream_id: str,
    generation: int,
    previous_raw: bytes,
    appended_line: bytes,
) -> None:
    """Commit one durable append after checking its exact previous head."""

    if (
        type(stem) is not str
        or _STEM.fullmatch(stem) is None
        or type(stream_id) is not str
        or _STREAM.fullmatch(stream_id) is None
        or type(generation) is not int
        or not 0 <= generation <= _MAX_GENERATIONS
        or type(previous_raw) is not bytes
        or type(appended_line) is not bytes
        or not appended_line.endswith(b"\n")
    ):
        raise ValueError("Worker segment commit input is invalid")
    _assert_head(
        rooted,
        stem=stem,
        stream_id=stream_id,
        generation=generation,
        raw=previous_raw,
    )
    committed_raw = previous_raw + appended_line
    try:
        current = rooted.sibling(_segment_name(stem, generation)).read_bytes(
            max_bytes=len(committed_raw)
        )
    except OSError as exc:
        raise CodingWorkerHistorySegmentError(
            "coding_worker_segment_active_changed"
        ) from exc
    if current != committed_raw:
        raise CodingWorkerHistorySegmentError("coding_worker_segment_active_changed")
    rooted.sibling(_head_name(stem, generation)).atomic_write(
        _head_bytes(stream_id, generation, committed_raw)
    )


def _read_coding_worker_segmented_history(
    rooted: RootedFile,
    *,
    stem: str,
    stream_id: str,
    max_segment_bytes: int,
    allow_uncommitted_append: bool,
    require_complete_append: bool,
) -> tuple[CodingWorkerSegmentedHistoryV1, bytes]:
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
    expected_names.update(_head_name(stem, index) for index in range(active + 1))
    actual = {
        name
        for name in names
        if name.casefold().startswith((stem + ".", "." + stem + "."))
    }
    if not actual <= expected_names:
        raise CodingWorkerHistorySegmentError("coding_worker_segment_orphan")
    segments = []
    appended_line = b""
    for generation in range(active + 1):
        name = _segment_name(stem, generation)
        present = True
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
            present = False
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
        if present:
            if allow_uncommitted_append and generation == active:
                try:
                    _assert_head(
                        rooted,
                        stem=stem,
                        stream_id=stream_id,
                        generation=generation,
                        raw=raw,
                    )
                except CodingWorkerHistorySegmentError as exc:
                    if exc.code != "coding_worker_segment_head_changed":
                        raise
                    try:
                        head = rooted.sibling(_head_name(stem, generation)).read_bytes(
                            max_bytes=_MAX_HEAD_BYTES
                        )
                        value = json.loads(head)
                        if type(value) is not dict or type(value.get("byteCount")) is not int:
                            raise ValueError("Worker active head byte count is invalid")
                        committed_count = value["byteCount"]
                    except (OSError, TypeError, ValueError, UnicodeError) as invalid:
                        raise CodingWorkerHistorySegmentError(
                            "coding_worker_segment_head_changed"
                        ) from invalid
                    if (
                        not 0 <= committed_count < len(raw)
                        or head
                        != _head_bytes(stream_id, generation, raw[:committed_count])
                        or (committed_count > 0 and raw[committed_count - 1] != 10)
                        or (
                            require_complete_append
                            and (
                                not raw.endswith(b"\n")
                                or raw[committed_count:].count(b"\n") != 1
                            )
                        )
                    ):
                        raise CodingWorkerHistorySegmentError(
                            "coding_worker_segment_head_changed"
                        )
                    appended_line = raw[committed_count:]
                    raw = raw[:committed_count]
            else:
                _assert_head(
                    rooted,
                    stem=stem,
                    stream_id=stream_id,
                    generation=generation,
                    raw=raw,
                )
        elif _head_name(stem, generation) in names:
            raise CodingWorkerHistorySegmentError("coding_worker_segment_orphan")
        segments.append(raw)
    return CodingWorkerSegmentedHistoryV1(manifest=manifest, segments=tuple(segments)), appended_line


def read_coding_worker_segmented_history(
    rooted: RootedFile,
    *,
    stem: str,
    stream_id: str,
    max_segment_bytes: int,
) -> CodingWorkerSegmentedHistoryV1:
    """Read only fully committed segment bytes under one journal lock."""

    history, _ = _read_coding_worker_segmented_history(
        rooted,
        stem=stem,
        stream_id=stream_id,
        max_segment_bytes=max_segment_bytes,
        allow_uncommitted_append=False,
        require_complete_append=False,
    )
    return history


def rollback_coding_worker_unpublished_successor(
    rooted: RootedFile,
    *,
    stem: str,
    stream_id: str,
    max_segment_bytes: int,
) -> bool:
    """Remove only an exact empty successor left before manifest publication.

    The ordinary reader keeps rejecting this orphan. The caller must own the
    stream lock and its Product repair gate before invoking this operation.
    """

    if (
        type(stem) is not str
        or _STEM.fullmatch(stem) is None
        or type(stream_id) is not str
        or _STREAM.fullmatch(stream_id) is None
        or type(max_segment_bytes) is not int
        or max_segment_bytes < 1
    ):
        raise ValueError("Worker successor repair input is invalid")
    names, complete = rooted.scan_sibling_names(limit=_MAX_DIRECTORY_ENTRIES)
    if not complete:
        raise CodingWorkerHistorySegmentError(
            "coding_worker_segment_inventory_capacity"
        )
    manifest_name = stem + ".segments.json"
    try:
        manifest_raw = rooted.sibling(manifest_name).read_bytes(
            max_bytes=_MAX_MANIFEST_BYTES
        )
    except FileNotFoundError:
        manifest = None
    else:
        manifest = CodingWorkerSegmentManifestV1.from_bytes(
            manifest_raw, stream_id=stream_id
        )
    active = 0 if manifest is None else manifest.active_generation
    if active >= _MAX_GENERATIONS:
        raise CodingWorkerHistorySegmentError("coding_worker_segment_capacity")
    successor_name = _segment_name(stem, active + 1)
    successor_head_name = _head_name(stem, active + 1)
    expected_names = {stem + ".jsonl.lock", successor_name, successor_head_name}
    if manifest is not None:
        expected_names.add(manifest_name)
    expected_names.update(_segment_name(stem, index) for index in range(active + 1))
    expected_names.update(_head_name(stem, index) for index in range(active + 1))
    actual = {
        name
        for name in names
        if name.casefold().startswith((stem + ".", "." + stem + "."))
    }
    if not actual <= expected_names:
        raise CodingWorkerHistorySegmentError("coding_worker_segment_orphan")
    if successor_name not in actual:
        if successor_head_name in actual:
            raise CodingWorkerHistorySegmentError("coding_worker_segment_orphan")
        return False
    successor = rooted.sibling(successor_name)
    try:
        successor_raw = successor.read_bytes(max_bytes=1)
    except OSError as exc:
        raise CodingWorkerHistorySegmentError(
            "coding_worker_segment_unpublished_successor_changed"
        ) from exc
    if successor_raw != b"":
        raise CodingWorkerHistorySegmentError(
            "coding_worker_segment_unpublished_successor_changed"
        )
    if successor_head_name in actual:
        head = rooted.sibling(successor_head_name)
        try:
            head_raw = head.read_bytes(max_bytes=_MAX_HEAD_BYTES)
        except OSError as exc:
            raise CodingWorkerHistorySegmentError(
                "coding_worker_segment_unpublished_successor_changed"
            ) from exc
        if head_raw != _head_bytes(
            stream_id, active + 1, b""
        ):
            raise CodingWorkerHistorySegmentError(
                "coding_worker_segment_unpublished_successor_changed"
            )
        head_stat = head.stat()
        head.unlink_owned((head_stat.st_dev, head_stat.st_ino))
    successor_stat = successor.stat()
    successor.unlink_owned((successor_stat.st_dev, successor_stat.st_ino))
    read_coding_worker_segmented_history(
        rooted,
        stem=stem,
        stream_id=stream_id,
        max_segment_bytes=max_segment_bytes,
    )
    return True


def read_coding_worker_uncommitted_active_append(
    rooted: RootedFile,
    *,
    stem: str,
    stream_id: str,
    max_segment_bytes: int,
) -> CodingWorkerUncommittedActiveAppendV1:
    """Return one head-anchored append for a separate Product repair decision."""

    history, appended_line = _read_coding_worker_segmented_history(
        rooted,
        stem=stem,
        stream_id=stream_id,
        max_segment_bytes=max_segment_bytes,
        allow_uncommitted_append=True,
        require_complete_append=True,
    )
    if not appended_line:
        raise CodingWorkerHistorySegmentError("coding_worker_segment_repair_absent")
    return CodingWorkerUncommittedActiveAppendV1(history, appended_line)


def read_coding_worker_uncommitted_active_tail(
    rooted: RootedFile,
    *,
    stem: str,
    stream_id: str,
    max_segment_bytes: int,
) -> tuple[CodingWorkerSegmentedHistoryV1, bytes]:
    """Inspect a head-anchored tail, including a partial crash append."""

    history, tail = _read_coding_worker_segmented_history(
        rooted,
        stem=stem,
        stream_id=stream_id,
        max_segment_bytes=max_segment_bytes,
        allow_uncommitted_append=True,
        require_complete_append=False,
    )
    if not tail:
        raise CodingWorkerHistorySegmentError("coding_worker_segment_repair_absent")
    return history, tail


def rollback_coding_worker_uncommitted_active_tail(
    rooted: RootedFile,
    *,
    stem: str,
    stream_id: str,
    max_segment_bytes: int,
) -> CodingWorkerSegmentedHistoryV1:
    """Discard only a noncommitted active tail after its exact old head."""

    history, tail = read_coding_worker_uncommitted_active_tail(
        rooted,
        stem=stem,
        stream_id=stream_id,
        max_segment_bytes=max_segment_bytes,
    )
    name = _segment_name(stem, history.active_generation)
    rooted.sibling(name).truncate_exact_prefix(
        expected=history.active_raw + tail,
        keep_bytes=len(history.active_raw),
    )
    reopened = read_coding_worker_segmented_history(
        rooted,
        stem=stem,
        stream_id=stream_id,
        max_segment_bytes=max_segment_bytes,
    )
    if reopened != history:
        raise CodingWorkerHistorySegmentError(
            "coding_worker_segment_rollback_changed"
        )
    return reopened


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
    _assert_head(
        rooted,
        stem=stem,
        stream_id=stream_id,
        generation=history.active_generation,
        raw=history.active_raw,
    )
    # Publish the empty successor durably before the manifest can name it.
    # Otherwise a later loss of a written active segment is indistinguishable
    # from an interrupted seal that never created the successor.
    try:
        rooted.sibling(_segment_name(stem, manifest.active_generation)).create_new(b"")
        rooted.sibling(_head_name(stem, manifest.active_generation)).create_new(
            _head_bytes(stream_id, manifest.active_generation, b"")
        )
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
    "CodingWorkerUncommittedActiveAppendV1",
    "commit_coding_worker_active_segment",
    "initialize_coding_worker_active_head",
    "read_coding_worker_segmented_history",
    "read_coding_worker_uncommitted_active_append",
    "read_coding_worker_uncommitted_active_tail",
    "rollback_coding_worker_unpublished_successor",
    "rollback_coding_worker_uncommitted_active_tail",
    "seal_coding_worker_active_segment",
]
