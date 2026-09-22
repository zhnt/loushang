"""Disposable, authority-bound load index for large Model Input v2 transcripts.

The Conversation JSONL file remains the sole authority.  This sidecar only
records line locations and already-validated Model Input node identities.  A
cache hit requires a compatibility match, a self-checksum match, and an exact
SHA-256 match for the indexed journal prefix.  Any doubt falls back to the
normal strict journal reader and atomically rebuilds the sidecar.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, cast

from loushang.foundation.json import JSONValue, validate_json_value

if TYPE_CHECKING:
    from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.conversation.jsonl_codec import (
    ConversationJsonlHeaderCodec,
    ConversationJsonlRecordCodec,
)
from loushang.harness.conversation.types import (
    ConversationHeader,
    ConversationRecord,
)
from loushang.harness.journal import (
    JournalCodecError,
    JournalDiagnostic,
    JournalFileError,
    JsonlSnapshot,
    LockFactory,
)
from loushang.harness.transcript.kinds import MODEL_INPUT_COMPONENT_KIND
from loushang.harness.transcript.model_input_v2_codec import (
    decode_model_input_node_bundle,
    decode_model_input_sequence_tail_projection,
)
from loushang.harness.transcript.model_input_v2_types import (
    MODEL_INPUT_V2_PAYLOAD_VERSION,
    MODEL_INPUT_V2_SCHEMA_VERSION,
    DeferredModelInputNode,
    DeferredModelInputNodeBundle,
    DeferredModelInputSequenceLink,
    ModelInputJsonValueNode,
    ModelInputNode,
    ModelInputNodeBundle,
    ModelInputNodeKind,
    ModelInputSequenceTailNode,
)
from loushang.harness.transcript.types import AgentTranscriptRecord

_LOGGER = logging.getLogger(__name__)
_INDEX_VERSION = 1
_INDEX_SUFFIX = ".model-input-v2.index.json"
_MAX_INDEXED_TAIL_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class AgentTranscriptIndexLoadStats:
    status: str
    indexed_bytes: int
    tail_bytes: int
    record_count: int
    verify_ms: float
    load_ms: float


@dataclass(frozen=True)
class _LineSpan:
    start: int
    end: int
    line_number: int


@dataclass(frozen=True)
class _DeferredBundleEntry:
    start: int
    end: int
    line_sha256: str
    nodes: tuple[DeferredModelInputNode, ...]


class _CacheMiss(Exception):
    pass


class _DeferredNodeSource:
    def __init__(self, path: Path, *, raw: bytes | None = None) -> None:
        self._path = path
        self._raw = raw
        self._entries: dict[str, _DeferredBundleEntry] = {}
        self._bundles: dict[str, tuple[ModelInputNode, ...]] = {}
        self._sequence_links: dict[
            tuple[str, int],
            DeferredModelInputSequenceLink,
        ] = {}

    def register(self, record_id: str, entry: _DeferredBundleEntry) -> None:
        if record_id in self._entries:
            raise _CacheMiss("duplicate deferred Model Input record id")
        self._entries[record_id] = entry

    def load_bundle_nodes(self, record_id: str) -> tuple[ModelInputNode, ...]:
        cached = self._bundles.get(record_id)
        if cached is not None:
            return cached
        entry, line = self._read_entry_line(record_id)
        try:
            envelope = _json_mapping(line)
            payload = envelope.get("payload")
            if not isinstance(payload, dict):
                raise TypeError("Model Input bundle payload must be an object")
            bundle = decode_model_input_node_bundle(cast(JSONValue, payload))
        except Exception as exc:
            raise ValueError("deferred Model Input bundle is invalid") from exc
        _require_bundle_matches_index(bundle, entry.nodes)
        self._bundles[record_id] = bundle.nodes
        return bundle.nodes

    def load_sequence_link(
        self,
        record_id: str,
        ordinal: int,
    ) -> DeferredModelInputSequenceLink:
        key = (record_id, ordinal)
        cached = self._sequence_links.get(key)
        if cached is not None:
            return cached
        entry, line = self._read_entry_line(record_id)
        if ordinal < 0 or ordinal >= len(entry.nodes):
            raise ValueError("deferred Model Input sequence ordinal changed")
        indexed = entry.nodes[ordinal]
        if indexed.node_kind != "sequence_tail":
            raise ValueError("deferred Model Input node is not a sequence tail")
        try:
            envelope = _json_mapping(line)
            payload = envelope.get("payload")
            raw_nodes = payload.get("nodes") if isinstance(payload, dict) else None
            raw_node = raw_nodes[ordinal] if isinstance(raw_nodes, list) else None
            if not isinstance(raw_node, dict):
                raise TypeError("Model Input sequence node must be an object")
            if (
                raw_node.get("contentHash") != indexed.content_hash
                or raw_node.get("nodeKind") != indexed.node_kind
            ):
                raise ValueError("Model Input sequence identity changed")
            link = decode_model_input_sequence_tail_projection(raw_node)
            if (
                link.total_item_count != indexed.total_item_count
                or link.sequence_hash != indexed.sequence_hash
            ):
                raise ValueError("Model Input sequence state changed")
        except Exception as exc:
            raise ValueError("deferred Model Input sequence link is invalid") from exc
        self._sequence_links[key] = link
        return link

    def _read_entry_line(self, record_id: str) -> tuple[_DeferredBundleEntry, bytes]:
        entry = self._entries.get(record_id)
        if entry is None:
            raise ValueError("deferred Model Input record is outside the index")
        try:
            if self._raw is not None:
                line = self._raw[entry.start:entry.end]
            else:
                with self._path.open("rb") as handle:
                    handle.seek(entry.start)
                    line = handle.read(entry.end - entry.start)
        except OSError as exc:
            raise ValueError(
                "deferred Model Input journal line is unavailable"
            ) from exc
        if _sha256(line) != entry.line_sha256:
            raise ValueError("deferred Model Input journal line changed after load")
        return entry, line


def load_agent_transcript_snapshot_with_index(
    path: Path,
    *,
    strict_loader: Callable[
        [], JsonlSnapshot[ConversationHeader, AgentTranscriptRecord]
    ],
    header_codec: ConversationJsonlHeaderCodec,
    record_codec: ConversationJsonlRecordCodec,
    lock_factory: LockFactory,
    compatibility_token: str,
    write_index: bool = True,
    retain_raw: bool = False,
    read_bytes: Callable[[], bytes] | None = None,
    read_cache: Callable[[Path], bytes] | None = None,
    write_cache: Callable[[Path, bytes], None] | None = None,
) -> JsonlSnapshot[ConversationHeader, AgentTranscriptRecord]:
    """Load a verified index, optionally rebuilding it after strict replay.

    Read-only projections supply stable no-follow readers and a non-mutating
    lock strategy as well as write_index=False; this flag alone is not enough.
    """

    started = time.perf_counter_ns()
    try:
        with lock_factory(path, "shared"):
            raw = read_bytes() if read_bytes is not None else path.read_bytes()
            manifest = _read_manifest(
                _projection_cache_path(path),
                compatibility_token=compatibility_token,
                read_cache=read_cache,
            )
            verify_started = time.perf_counter_ns()
            indexed_size = _integer(manifest, "projectedSize")
            if indexed_size < 0 or indexed_size > len(raw):
                raise _CacheMiss("journal shrank before indexed prefix")
            if len(raw) - indexed_size > _MAX_INDEXED_TAIL_BYTES:
                raise _CacheMiss("journal tail exceeds the bounded index window")
            expected_prefix_hash = _text(manifest, "prefixSha256")
            if not hmac.compare_digest(
                expected_prefix_hash,
                "sha256:" + _sha256(raw[:indexed_size]),
            ):
                raise _CacheMiss("indexed journal prefix changed")
            verify_ms = _milliseconds(time.perf_counter_ns() - verify_started)
            try:
                snapshot = _load_verified_manifest(
                    path,
                    raw,
                    manifest,
                    header_codec=header_codec,
                    record_codec=record_codec,
                    retain_raw=retain_raw or not write_index,
                )
            except JournalFileError:
                # A strictly decoded appended tail is authoritative and must
                # preserve the journal reader's normal corruption semantics.
                raise
            except _CacheMiss:
                raise
            except (IndexError, KeyError, TypeError, ValueError) as exc:
                # Cache-derived construction must be fail-open.  The strict
                # loader below remains the sole authority for the transcript.
                raise _CacheMiss("node index projection is invalid") from exc
            if write_index and len(raw) != indexed_size:
                _try_rebuild_manifest(
                    path,
                    raw,
                    snapshot,
                    compatibility_token=compatibility_token,
                    write_cache=write_cache,
                )
            _log_stats(
                AgentTranscriptIndexLoadStats(
                    status=("extended" if write_index else "tail_read") if len(raw) != indexed_size else "hit",
                    indexed_bytes=indexed_size,
                    tail_bytes=len(raw) - indexed_size,
                    record_count=len(snapshot.records),
                    verify_ms=verify_ms,
                    load_ms=_milliseconds(time.perf_counter_ns() - started),
                )
            )
            return snapshot
    except _CacheMiss:
        pass

    snapshot = strict_loader()
    if not write_index:
        _log_stats(AgentTranscriptIndexLoadStats(
            status="replayed", indexed_bytes=0, tail_bytes=0,
            record_count=len(snapshot.records), verify_ms=0.0,
            load_ms=_milliseconds(time.perf_counter_ns() - started),
        ))
        return snapshot
    try:
        with lock_factory(path, "shared"):
            raw = read_bytes() if read_bytes is not None else path.read_bytes()
            _try_rebuild_manifest(
                path,
                raw,
                snapshot,
                compatibility_token=compatibility_token,
                write_cache=write_cache,
            )
    except OSError:
        # The journal result is still authoritative; a disposable cache failure
        # must never turn a successful load into a product failure.
        pass
    _log_stats(
        AgentTranscriptIndexLoadStats(
            status="rebuilt",
            indexed_bytes=0,
            tail_bytes=0,
            record_count=len(snapshot.records),
            verify_ms=0.0,
            load_ms=_milliseconds(time.perf_counter_ns() - started),
        )
    )
    return snapshot


def delete_agent_transcript_index(path: Path, *, file_io: RootedFileIO | None = None) -> None:
    """Remove the disposable projection associated with one transcript."""

    if file_io is not None:
        file_io.unlink(_projection_cache_path(path), missing_ok=True)
    else:
        _projection_cache_path(path).unlink(missing_ok=True)


def _load_verified_manifest(
    path: Path,
    raw: bytes,
    manifest: Mapping[str, JSONValue],
    *,
    header_codec: ConversationJsonlHeaderCodec,
    record_codec: ConversationJsonlRecordCodec,
    retain_raw: bool = False,
) -> JsonlSnapshot[ConversationHeader, AgentTranscriptRecord]:
    indexed_size = _integer(manifest, "projectedSize")
    ends_at_line_boundary = _boolean(manifest, "endsAtLineBoundary")
    actual_boundary = indexed_size == 0 or raw[indexed_size - 1 : indexed_size] == b"\n"
    if ends_at_line_boundary != actual_boundary:
        raise _CacheMiss("indexed prefix boundary metadata changed")
    if len(raw) > indexed_size and not ends_at_line_boundary:
        raise _CacheMiss("indexed prefix does not end at a JSONL boundary")

    next_line_number = _integer(manifest, "nextLineNumber")
    if next_line_number != raw[:indexed_size].count(b"\n") + 1:
        raise _CacheMiss("indexed prefix line count changed")

    prefix_spans = [
        span
        for span in _line_spans(
            raw[:indexed_size],
            start=0,
            first_line_number=1,
        )
        if raw[span.start : span.end].strip()
    ]
    raw_rows = _sequence(manifest, "records")
    if len(prefix_spans) != len(raw_rows) + 1:
        raise _CacheMiss("indexed journal line layout changed")

    header_row = _mapping(manifest, "headerLine")
    header_span = _manifest_span(header_row, maximum=indexed_size)
    if not prefix_spans or header_span != prefix_spans[0]:
        raise _CacheMiss("indexed header position changed")
    try:
        header_line = raw[header_span.start : header_span.end]
        _require_line_hash(header_line, header_row)
        header_value = _strict_json_mapping(header_line)
        header = header_codec.decode_header(header_value)
    except Exception as exc:
        raise _CacheMiss("indexed header no longer decodes") from exc

    source = _DeferredNodeSource(path, raw=bytes(raw) if retain_raw else None)
    prepared: list[
        tuple[
            Mapping[str, JSONValue],
            _LineSpan,
            Mapping[str, object],
            bytes,
            tuple[DeferredModelInputNode, ...] | None,
        ]
    ] = []
    for position, raw_row in enumerate(raw_rows):
        row = _as_mapping(raw_row, name="indexed record")
        span = _manifest_span(row, maximum=indexed_size)
        if _integer(row, "recordPosition") != position:
            raise _CacheMiss("indexed record position changed")
        if span != prefix_spans[position + 1]:
            raise _CacheMiss("indexed record line position changed")
        line = raw[span.start : span.end]
        _require_line_hash(line, row)
        try:
            envelope = _json_mapping(line)
        except Exception as exc:
            raise _CacheMiss("indexed record JSON changed") from exc
        nodes_value = row.get("modelInputNodes")
        if nodes_value is None:
            prepared.append((row, span, envelope, line, None))
            continue
        nodes = _require_deferred_envelope(
            envelope,
            _deferred_nodes(nodes_value),
        )
        record_id = _envelope_text(envelope, "recordId")
        source.register(
            record_id,
            _DeferredBundleEntry(
                start=span.start,
                end=span.end,
                line_sha256=_text(row, "lineSha256"),
                nodes=nodes,
            ),
        )
        prepared.append((row, span, envelope, line, nodes))

    records: list[AgentTranscriptRecord] = []
    for _row, _span, prepared_envelope, line, prepared_nodes in prepared:
        if prepared_nodes is None:
            try:
                records.append(_decode_record_line(line, record_codec=record_codec))
            except Exception as exc:
                raise _CacheMiss("indexed non-Model-Input record changed") from exc
            continue
        records.append(
            _deferred_record(
                prepared_envelope,
                nodes=prepared_nodes,
                source=source,
            )
        )

    tail_records, tail_diagnostics = _decode_tail(
        raw,
        start=indexed_size,
        first_line_number=next_line_number,
        path=path,
        record_codec=record_codec,
    )
    records.extend(tail_records)
    return JsonlSnapshot(
        header=header,
        records=tuple(records),
        diagnostics=tail_diagnostics,
    )


def _decode_tail(
    raw: bytes,
    *,
    start: int,
    first_line_number: int,
    path: Path,
    record_codec: ConversationJsonlRecordCodec,
) -> tuple[tuple[AgentTranscriptRecord, ...], tuple[JournalDiagnostic, ...]]:
    if start == len(raw):
        return (), ()
    spans = _line_spans(raw, start=start, first_line_number=first_line_number)
    nonblank = [span for span in spans if raw[span.start : span.end].strip()]
    last_nonblank = nonblank[-1] if nonblank else None
    has_trailing_newline = raw.endswith(b"\n")
    records: list[AgentTranscriptRecord] = []
    diagnostics: list[JournalDiagnostic] = []
    for span in nonblank:
        line = raw[span.start : span.end]
        try:
            records.append(_decode_record_line(line, record_codec=record_codec))
        except Exception as exc:
            is_partial_tail = span == last_nonblank and not has_trailing_newline
            if is_partial_tail:
                diagnostics.append(
                    JournalDiagnostic(
                        code="partial_journal_tail",
                        message=(
                            "Journal record was skipped because it is incomplete "
                            "or invalid."
                        ),
                        source_path=path,
                        line_number=span.line_number,
                    )
                )
                continue
            code = exc.code if isinstance(exc, JournalCodecError) else "invalid_record"
            raise JournalFileError(
                "Journal record is invalid",
                path=path,
                code=code,
                line_number=span.line_number,
            ) from exc
    return tuple(records), tuple(diagnostics)


def _deferred_record(
    envelope: Mapping[str, object],
    *,
    nodes: tuple[DeferredModelInputNode, ...],
    source: _DeferredNodeSource,
) -> AgentTranscriptRecord:
    record_id = _envelope_text(envelope, "recordId")
    parent = envelope.get("parentId")
    if parent is not None and (not isinstance(parent, str) or not parent.strip()):
        raise _CacheMiss("indexed Model Input parent id is invalid")
    metadata = envelope.get("metadata")
    if not isinstance(metadata, dict):
        raise _CacheMiss("indexed Model Input metadata is invalid")
    return ConversationRecord(
        record_id=record_id,
        parent_id=cast(str | None, parent),
        kind=MODEL_INPUT_COMPONENT_KIND,
        payload_version=MODEL_INPUT_V2_PAYLOAD_VERSION,
        created_at=_envelope_text(envelope, "createdAt"),
        payload=DeferredModelInputNodeBundle(
            record_id=record_id,
            source=source,
            indexed_nodes=nodes,
        ),
        metadata=cast(Mapping[str, JSONValue], metadata),
    )


def _require_deferred_envelope(
    envelope: Mapping[str, object],
    nodes: tuple[DeferredModelInputNode, ...],
) -> tuple[DeferredModelInputNode, ...]:
    if envelope.get("type") != "record":
        raise _CacheMiss("indexed Model Input envelope type changed")
    if _envelope_text(envelope, "kind") != MODEL_INPUT_COMPONENT_KIND:
        raise _CacheMiss("indexed Model Input record kind changed")
    if _envelope_integer(envelope, "payloadVersion") != MODEL_INPUT_V2_PAYLOAD_VERSION:
        raise _CacheMiss("indexed Model Input payload version changed")
    payload = envelope.get("payload")
    if not isinstance(payload, dict) or set(payload) != {"schemaVersion", "nodes"}:
        raise _CacheMiss("indexed Model Input payload shape changed")
    if _envelope_integer(payload, "schemaVersion") != MODEL_INPUT_V2_SCHEMA_VERSION:
        raise _CacheMiss("indexed Model Input schema changed")
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list) or len(raw_nodes) != len(nodes):
        raise _CacheMiss("indexed Model Input node count changed")
    verified_nodes = []
    for indexed, raw_node in zip(nodes, raw_nodes, strict=True):
        if not isinstance(raw_node, dict):
            raise _CacheMiss("indexed Model Input node shape changed")
        if (
            raw_node.get("nodeKind") != indexed.node_kind
            or raw_node.get("contentHash") != indexed.content_hash
        ):
            raise _CacheMiss("indexed Model Input node identity changed")
        if (
            indexed.node_kind == "json_value"
            and raw_node.get("valueHash") != indexed.value_hash
        ):
            raise _CacheMiss("indexed Model Input value identity changed")
        if indexed.node_kind == "json_value":
            inline_json = raw_node.get("inlineJson")
            if isinstance(inline_json, str):
                decoded_bytes = _envelope_integer(raw_node, "decodedBytes")
                encoded_inline = inline_json.encode("utf-8")
                if len(encoded_inline) != decoded_bytes:
                    raise _CacheMiss("indexed Model Input inline byte count changed")
                if "sha256:" + _sha256(encoded_inline) != indexed.value_hash:
                    raise _CacheMiss("indexed Model Input inline value hash changed")
                indexed = replace(indexed, value_hash_verified=True)
        if indexed.node_kind == "sequence_tail" and (
            raw_node.get("totalItemCount") != indexed.total_item_count
            or raw_node.get("sequenceHash") != indexed.sequence_hash
        ):
            raise _CacheMiss("indexed Model Input sequence identity changed")
        verified_nodes.append(indexed)
    return tuple(verified_nodes)


def _try_rebuild_manifest(
    path: Path,
    raw: bytes,
    snapshot: JsonlSnapshot[ConversationHeader, AgentTranscriptRecord],
    *,
    compatibility_token: str,
    write_cache: Callable[[Path, bytes], None] | None = None,
) -> None:
    try:
        manifest = _build_manifest(
            raw,
            snapshot,
            compatibility_token=compatibility_token,
        )
        _write_manifest(_projection_cache_path(path), manifest, write_cache=write_cache)
    except Exception as exc:
        _LOGGER.debug("failed to rebuild transcript node index", exc_info=exc)


def _build_manifest(
    raw: bytes,
    snapshot: JsonlSnapshot[ConversationHeader, AgentTranscriptRecord],
    *,
    compatibility_token: str,
) -> dict[str, JSONValue]:
    partial_line_number = next(
        (
            item.line_number
            for item in snapshot.diagnostics
            if item.code == "partial_journal_tail"
        ),
        None,
    )
    all_spans = _line_spans(raw, start=0, first_line_number=1)
    projected_size = len(raw)
    if partial_line_number is not None:
        partial = next(
            (item for item in all_spans if item.line_number == partial_line_number),
            None,
        )
        if partial is None:
            raise ValueError("partial-tail diagnostic is outside the journal")
        projected_size = partial.start
    nonblank = [
        span
        for span in all_spans
        if span.start < projected_size and raw[span.start : span.end].strip()
    ]
    if len(nonblank) != len(snapshot.records) + 1:
        raise ValueError("journal changed before node index publication")
    header_span = nonblank[0]
    record_rows = [
        _record_manifest_row(raw, span, record, position=position)
        for position, (span, record) in enumerate(
            zip(nonblank[1:], snapshot.records, strict=True)
        )
    ]
    manifest: dict[str, JSONValue] = {
        "version": _INDEX_VERSION,
        "compatibilityToken": compatibility_token,
        "projectedSize": projected_size,
        "prefixSha256": "sha256:" + _sha256(raw[:projected_size]),
        "endsAtLineBoundary": (
            projected_size == 0 or raw[projected_size - 1 : projected_size] == b"\n"
        ),
        "nextLineNumber": raw[:projected_size].count(b"\n") + 1,
        "headerLine": _span_json(raw, header_span),
        "records": cast(list[JSONValue], record_rows),
    }
    manifest["checksum"] = _manifest_checksum(manifest)
    return manifest


def _record_manifest_row(
    raw: bytes,
    span: _LineSpan,
    record: AgentTranscriptRecord,
    *,
    position: int,
) -> dict[str, JSONValue]:
    row = _span_json(raw, span)
    row["recordPosition"] = position
    if (
        record.kind == MODEL_INPUT_COMPONENT_KIND
        and record.payload_version == MODEL_INPUT_V2_PAYLOAD_VERSION
        and isinstance(record.payload, ModelInputNodeBundle)
    ):
        if isinstance(record.payload, DeferredModelInputNodeBundle):
            nodes = record.payload.indexed_nodes
        else:
            nodes = tuple(
                _deferred_node(node, ordinal=ordinal)
                for ordinal, node in enumerate(record.payload.nodes)
            )
        row["modelInputNodes"] = [_deferred_node_json(item) for item in nodes]
    return row


def _deferred_node(node: ModelInputNode, *, ordinal: int) -> DeferredModelInputNode:
    return DeferredModelInputNode(
        ordinal=ordinal,
        node_kind=node.node_kind,
        content_hash=node.content_hash,
        value_hash=(
            node.value_hash if isinstance(node, ModelInputJsonValueNode) else None
        ),
        # Keep potentially user-authored inline JSON out of the sidecar.
        inline_json=None,
        total_item_count=(
            node.total_item_count
            if isinstance(node, ModelInputSequenceTailNode)
            else None
        ),
        sequence_hash=(
            node.sequence_hash if isinstance(node, ModelInputSequenceTailNode) else None
        ),
    )


def _deferred_node_json(node: DeferredModelInputNode) -> dict[str, JSONValue]:
    return {
        "ordinal": node.ordinal,
        "nodeKind": node.node_kind,
        "contentHash": node.content_hash,
        "valueHash": node.value_hash,
        "totalItemCount": node.total_item_count,
        "sequenceHash": node.sequence_hash,
    }


def _deferred_nodes(value: object) -> tuple[DeferredModelInputNode, ...]:
    if not isinstance(value, list) or not value:
        raise _CacheMiss("indexed Model Input nodes are invalid")
    nodes = []
    for raw_node in value:
        node = _as_mapping(raw_node, name="indexed Model Input node")
        nodes.append(
            DeferredModelInputNode(
                ordinal=_integer(node, "ordinal"),
                node_kind=cast(ModelInputNodeKind, _text(node, "nodeKind")),
                content_hash=_text(node, "contentHash"),
                value_hash=_optional_text(node, "valueHash"),
                # Inline JSON can contain user content.  The disposable index
                # keeps identities and positions only; actual values remain in
                # the authoritative journal and load lazily when referenced.
                inline_json=None,
                total_item_count=_optional_integer(node, "totalItemCount"),
                sequence_hash=_optional_text(node, "sequenceHash"),
            )
        )
    return tuple(nodes)


def _require_bundle_matches_index(
    bundle: ModelInputNodeBundle,
    indexed_nodes: Sequence[DeferredModelInputNode],
) -> None:
    actual = tuple(
        _deferred_node(node, ordinal=ordinal)
        for ordinal, node in enumerate(bundle.nodes)
    )
    expected = tuple(
        replace(
            node,
            value_hash_verified=False,
        )
        for node in indexed_nodes
    )
    if actual != expected:
        raise ValueError("deferred Model Input bundle changed from its index")


def _read_manifest(
    path: Path,
    *,
    compatibility_token: str,
    read_cache: Callable[[Path], bytes] | None = None,
) -> dict[str, JSONValue]:
    try:
        content = read_cache(path) if read_cache is not None else path.read_text(encoding="utf-8")
        value = json.loads(content, parse_constant=_reject)
        if not isinstance(value, dict):
            raise TypeError("node index must be an object")
        manifest = cast(dict[str, JSONValue], value)
        if _integer(manifest, "version") != _INDEX_VERSION:
            raise ValueError("node index version changed")
        if _text(manifest, "compatibilityToken") != compatibility_token:
            raise ValueError("node index compatibility changed")
        expected = _text(manifest, "checksum")
        body = dict(manifest)
        del body["checksum"]
        if not hmac.compare_digest(expected, _manifest_checksum(body)):
            raise ValueError("node index checksum changed")
        return manifest
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _CacheMiss("node index is unavailable or invalid") from exc


def _write_manifest(
    path: Path, manifest: Mapping[str, JSONValue], *,
    write_cache: Callable[[Path, bytes], None] | None = None,
) -> None:
    payload = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if write_cache is not None:
        write_cache(path, payload)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            os.chmod(temp_name, 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_name is not None:
            with suppress(OSError):
                Path(temp_name).unlink()


def _decode_record_line(
    line: bytes,
    *,
    record_codec: ConversationJsonlRecordCodec,
) -> AgentTranscriptRecord:
    value = _strict_json_mapping(line)
    return cast(AgentTranscriptRecord, record_codec.decode_record(value))


def _strict_json_mapping(line: bytes) -> dict[str, object]:
    value = _json_mapping(line)
    validate_json_value(value, name="journal record")
    return value


def _json_mapping(line: bytes) -> dict[str, object]:
    value = json.loads(line, parse_constant=_reject)
    if not isinstance(value, dict):
        raise TypeError("JSONL value must be an object")
    return cast(dict[str, object], value)


def _line_spans(
    raw: bytes,
    *,
    start: int,
    first_line_number: int,
) -> list[_LineSpan]:
    spans: list[_LineSpan] = []
    position = start
    line_number = first_line_number
    while position < len(raw):
        newline = raw.find(b"\n", position)
        end = len(raw) if newline < 0 else newline + 1
        spans.append(_LineSpan(position, end, line_number))
        position = end
        line_number += 1
    return spans


def _span_json(raw: bytes, span: _LineSpan) -> dict[str, JSONValue]:
    line = raw[span.start : span.end]
    return {
        "start": span.start,
        "end": span.end,
        "lineNumber": span.line_number,
        "lineSha256": _sha256(line),
    }


def _manifest_span(value: Mapping[str, object], *, maximum: int) -> _LineSpan:
    start = _integer(value, "start")
    end = _integer(value, "end")
    line_number = _integer(value, "lineNumber")
    if start < 0 or end <= start or end > maximum or line_number < 1:
        raise _CacheMiss("indexed line span is invalid")
    return _LineSpan(start, end, line_number)


def _require_line_hash(line: bytes, value: Mapping[str, object]) -> None:
    if not hmac.compare_digest(_sha256(line), _text(value, "lineSha256")):
        raise _CacheMiss("indexed journal line changed")


def _manifest_checksum(value: Mapping[str, JSONValue]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + _sha256(encoded)


def _projection_cache_path(path: Path) -> Path:
    return path.with_name(f"{path.name}{_INDEX_SUFFIX}")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: Mapping[str, object], key: str) -> Mapping[str, JSONValue]:
    return _as_mapping(value.get(key), name=key)


def _as_mapping(value: object, *, name: str) -> Mapping[str, JSONValue]:
    if not isinstance(value, dict):
        raise _CacheMiss(f"{name} must be an object")
    return cast(Mapping[str, JSONValue], value)


def _sequence(value: Mapping[str, object], key: str) -> list[JSONValue]:
    field = value.get(key)
    if not isinstance(field, list):
        raise _CacheMiss(f"{key} must be an array")
    return cast(list[JSONValue], field)


def _text(value: Mapping[str, object], key: str) -> str:
    field = value.get(key)
    if not isinstance(field, str) or not field.strip():
        raise _CacheMiss(f"{key} must be non-empty text")
    return field


def _optional_text(value: Mapping[str, object], key: str) -> str | None:
    field = value.get(key)
    if field is None:
        return None
    if not isinstance(field, str) or not field.strip():
        raise _CacheMiss(f"{key} must be non-empty text or null")
    return field


def _integer(value: Mapping[str, object], key: str) -> int:
    field = value.get(key)
    if isinstance(field, bool) or not isinstance(field, int):
        raise _CacheMiss(f"{key} must be an integer")
    return field


def _optional_integer(value: Mapping[str, object], key: str) -> int | None:
    field = value.get(key)
    if field is None:
        return None
    if isinstance(field, bool) or not isinstance(field, int):
        raise _CacheMiss(f"{key} must be an integer or null")
    return field


def _boolean(value: Mapping[str, object], key: str) -> bool:
    field = value.get(key)
    if not isinstance(field, bool):
        raise _CacheMiss(f"{key} must be a boolean")
    return field


def _envelope_text(value: Mapping[str, object], key: str) -> str:
    field = value.get(key)
    if not isinstance(field, str) or not field.strip():
        raise _CacheMiss(f"journal envelope {key} is invalid")
    return field


def _envelope_integer(value: Mapping[str, object], key: str) -> int:
    field = value.get(key)
    if isinstance(field, bool) or not isinstance(field, int) or field < 1:
        raise _CacheMiss(f"journal envelope {key} is invalid")
    return field


def _reject(token: str) -> NoReturn:
    raise ValueError(f"invalid JSON constant {token!r}")


def _milliseconds(duration_ns: int) -> float:
    return round(duration_ns / 1_000_000, 3)


def _log_stats(stats: AgentTranscriptIndexLoadStats) -> None:
    _LOGGER.debug(
        "agent transcript node index status=%s indexed_bytes=%d tail_bytes=%d "
        "record_count=%d verify_ms=%.3f load_ms=%.3f",
        stats.status,
        stats.indexed_bytes,
        stats.tail_bytes,
        stats.record_count,
        stats.verify_ms,
        stats.load_ms,
    )


__all__ = [
    "AgentTranscriptIndexLoadStats",
    "delete_agent_transcript_index",
    "load_agent_transcript_snapshot_with_index",
]
