"""Catalog, summaries, and query helpers for current Agent transcripts.

This optional Agent/AI profile projects Conversation JSONL transcripts into a
portable session read model. Products choose their roots and presentation, but
do not need to recreate Conversation JSONL discovery, summary indexing, or query logic.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import stat as stat_module
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar, cast

from loushang.agent.types import AgentMessage
from loushang.ai.types import AssistantMessage, TextPart, ToolResultMessage, UserMessage
from loushang.foundation.observability import get_log
from loushang.harness.conversation import (
    ConversationCatalog,
    ConversationHeader,
    ConversationIndex,
    ConversationIndexSnapshot,
    ConversationJsonlHeaderCodec,
    ConversationJsonlRecordCodec,
    ConversationLocator,
    ConversationProviderBinding,
    ConversationRepository,
    ConversationTreeNode,
    FunctionalConversationProjector,
    FunctionalProjectionCodec,
    IndexedProjection,
    JsonConversationIndex,
    ProjectionQuery,
    load_conversation_deletion_receipt,
)
from loushang.harness.transcript.discovery import (
    SessionDiscoveryMetadata,
    SessionSourceMode,
)
from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileLayout,
    create_agent_transcript_file_store,
    load_agent_transcript_file,
    load_agent_transcript_header,
)
from loushang.harness.transcript.kinds import (
    AGENT_MESSAGE_KIND,
    CONVERSATION_METADATA_PATCH_KIND,
    EXTENSION_DATA_KIND,
    MODEL_SELECTION_KIND,
    RECORD_ANNOTATION_PATCH_KIND,
)
from loushang.harness.transcript.profile import AgentTranscriptProfile
from loushang.harness.transcript.types import (
    AgentTranscriptContext,
    AgentTranscriptRecord,
    ApplicationMessage,
    ConversationMetadataPatch,
    ExtensionData,
    ModelSelectionSnapshot,
    RecordAnnotationPatch,
)

RecordT = TypeVar("RecordT")

_LEAF_UNSET = object()
_MISSING = object()
_SESSION_INDEX_VERSION = 3
_SESSION_INDEX_FILENAME = ".session-index.json"
_BOUNDED_SEGMENT_BYTES = 64 * 1024
_BOUNDED_ENRICH_LIMIT = 50
_MAX_PATH_SUMMARY_FILE_BYTES = 8 * 1024 * 1024
_MAX_PATH_SUMMARY_TOTAL_BYTES = 64 * 1024 * 1024
_MAX_PATH_SUMMARY_HEADER_BYTES = 64 * 1024
_PROFILE = AgentTranscriptProfile.default()
_HEADER_CODEC = ConversationJsonlHeaderCodec()
_RECORD_CODEC = ConversationJsonlRecordCodec(_PROFILE.payload_codecs)
log = get_log(__name__).bind(component="AgentTranscriptSessionCatalog")


@dataclass(frozen=True)
class SessionMetadata:
    created_at: str
    updated_at: str
    name: str | None = None


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    cwd: str
    session_file: Path | None
    parent_session: str | None
    leaf_id: str | None
    metadata: SessionMetadata
    locator: ConversationLocator | None = None


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    cwd: str
    session_file: Path | None
    parent_session: str | None
    leaf_id: str | None
    created_at: str
    updated_at: str
    name: str | None
    message_count: int
    entry_count: int
    first_message: str
    all_messages_text: str
    last_message_preview: str | None
    model: dict[str, str] | None
    has_diagnostics: bool = False
    diagnostic_count: int = 0
    last_diagnostic_code: str | None = None
    last_diagnostic_level: str | None = None
    locator: ConversationLocator | None = None
    authority_fingerprint: str | None = None
    bounded: bool = False
    counts_exact: bool = True
    discovery: SessionDiscoveryMetadata | None = None


@dataclass(frozen=True)
class BoundedSessionCatalogSnapshot:
    items: tuple[IndexedProjection[SessionSummary], ...]
    authority_count: int
    enriched_count: int
    bytes_read: int
    complete: bool = True


@dataclass(frozen=True)
class _BoundedSessionCandidate:
    path: Path
    size: int
    mtime_ns: int
    fingerprint: str


@dataclass
class SessionDiscoveryReadBudget:
    """One request-wide compatibility discovery I/O and candidate budget."""

    remaining_candidates: int = 4096
    remaining_bytes: int = _MAX_PATH_SUMMARY_TOTAL_BYTES
    truncated: bool = False

    def reserve(self, *, candidates: int = 0, bytes_: int = 0) -> bool:
        if (
            candidates > self.remaining_candidates
            or bytes_ > self.remaining_bytes
        ):
            self.truncated = True
            return False
        self.remaining_candidates -= candidates
        self.remaining_bytes -= bytes_
        return True

    def mark_incomplete(self) -> None:
        self.truncated = True


@dataclass(frozen=True, kw_only=True)
class SessionQuery:
    cwd: str | None = None
    name: str | None = None
    parent_session: str | None = None
    text: str | None = None
    named: bool | None = None
    sort_by: Literal["recent", "created", "relevance"] = "recent"
    has_diagnostics: bool | None = None
    has_messages: bool | None = None
    limit: int | None = None
    source_mode: SessionSourceMode | None = None


@dataclass(frozen=True)
class SessionTreeNode(Generic[RecordT]):
    record: RecordT
    children: tuple["SessionTreeNode[RecordT]", ...] = ()
    label: str | None = None
    label_timestamp: str | None = None


def project_session_record(record: object) -> dict[str, object]:
    """Project a session catalog record into the portable listing shape."""

    metadata = _safe_session_getattr(record, "metadata", None)
    session_file = _safe_session_getattr(record, "session_file", None)
    normalized: dict[str, object]
    if metadata is not None:
        normalized = {
            "session_id": _session_string_attr(record, "session_id"),
            "cwd": _session_string_attr(record, "cwd"),
            "session_file": _safe_session_string(session_file)
            if session_file is not None
            else None,
            "parent_session": _session_nullable_string_attr(record, "parent_session"),
            "leaf_id": _session_nullable_string_attr(record, "leaf_id"),
            "metadata": {
                "created_at": _session_string_attr(metadata, "created_at"),
                "updated_at": _session_string_attr(metadata, "updated_at"),
                "name": _session_nullable_string_attr(metadata, "name"),
            },
        }
    else:
        normalized = {
            "session_id": _session_string_attr(record, "session_id"),
            "cwd": _session_string_attr(record, "cwd"),
            "session_file": _safe_session_string(session_file)
            if session_file is not None
            else None,
            "parent_session": _session_nullable_string_attr(record, "parent_session"),
            "leaf_id": _session_nullable_string_attr(record, "leaf_id"),
            "metadata": {
                "created_at": _session_string_attr(record, "created_at"),
                "updated_at": _session_string_attr(record, "updated_at"),
                "name": _session_nullable_string_attr(record, "name"),
            },
        }

    for field_name in (
        "message_count",
        "entry_count",
        "first_message",
        "all_messages_text",
        "last_message_preview",
        "model",
        "has_diagnostics",
        "diagnostic_count",
        "last_diagnostic_code",
        "last_diagnostic_level",
    ):
        value = _safe_session_getattr(record, field_name, _MISSING)
        if value is not _MISSING:
            normalized[field_name] = _json_safe_session_value(value)
    discovery = _safe_session_getattr(record, "discovery", None)
    if isinstance(discovery, SessionDiscoveryMetadata):
        normalized["discovery"] = discovery.to_dict()
    return normalized


def try_project_session_record(record: object) -> dict[str, object] | None:
    """Best-effort session projection for catalogs containing bad records."""

    try:
        return project_session_record(record)
    except Exception:
        return None


def _session_string_attr(target: object, name: str) -> str:
    value = _safe_session_getattr(target, name, "")
    return value if isinstance(value, str) else _safe_session_string(value)


def _session_nullable_string_attr(target: object, name: str) -> str | None:
    value = _safe_session_getattr(target, name, None)
    if value is None:
        return None
    return value if isinstance(value, str) else _safe_session_string(value)


def _safe_session_getattr(target: object, name: str, default: object) -> object:
    try:
        return getattr(target, name, default)
    except Exception:
        return default


def _safe_session_string(value: object) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return ""


def _json_safe_session_value(value: Any) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            _safe_session_string(key): _json_safe_session_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_json_safe_session_value(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return _safe_session_string(value)


def agent_transcript_header_cwd(header: ConversationHeader) -> str:
    """Return the Conversation JSONL transcript workspace hint, if present."""

    cwd = header.metadata.get("cwd")
    return cwd if isinstance(cwd, str) else ""


def agent_transcript_header_parent_session(
    header: ConversationHeader,
) -> str | None:
    """Return the Conversation JSONL transcript parent-session reference."""

    parent = header.metadata.get("parentSession")
    return parent if isinstance(parent, str) else None


def build_agent_transcript_label_indexes(
    records: Sequence[AgentTranscriptRecord],
) -> tuple[dict[str, str], dict[str, str]]:
    """Build the standard display-label indexes from append-only annotations."""

    labels_by_target_id: dict[str, str] = {}
    label_timestamps_by_target_id: dict[str, str] = {}
    for record in records:
        patch = record.payload
        if record.kind != RECORD_ANNOTATION_PATCH_KIND or not isinstance(
            patch, RecordAnnotationPatch
        ):
            continue
        if patch.namespace != "display.label":
            continue
        if patch.operation == "set" and isinstance(patch.value, str):
            labels_by_target_id[patch.target_record_id] = patch.value
            label_timestamps_by_target_id[patch.target_record_id] = record.created_at
        else:
            labels_by_target_id.pop(patch.target_record_id, None)
            label_timestamps_by_target_id.pop(patch.target_record_id, None)
    return labels_by_target_id, label_timestamps_by_target_id


def build_agent_transcript_session_context(
    records: Sequence[AgentTranscriptRecord],
    leaf_id: str | None | object = _LEAF_UNSET,
    by_id: dict[str, AgentTranscriptRecord] | None = None,
) -> AgentTranscriptContext:
    """Replay one selected Conversation JSONL transcript branch into Agent context."""

    del by_id
    entries = list(records)
    if leaf_id is _LEAF_UNSET:
        resolved_leaf_id = entries[-1].record_id if entries else None
    elif leaf_id is None:
        return _PROFILE.replay(())
    else:
        resolved_leaf_id = leaf_id if isinstance(leaf_id, str) else None

    if resolved_leaf_id is None:
        return _PROFILE.replay(())
    conversation = ConversationRepository.create(
        header=None,
        records=entries,
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
        mode="compatible",
    )
    if conversation.get(resolved_leaf_id) is None:
        return _PROFILE.replay(())
    conversation.branch(resolved_leaf_id)
    return _PROFILE.replay(conversation.active_records())


def load_agent_transcript_session_metadata(
    header: ConversationHeader,
    records: Sequence[AgentTranscriptRecord],
) -> SessionMetadata:
    state = _PROFILE.replay(records).state
    return SessionMetadata(
        created_at=header.created_at,
        updated_at=_last_activity_timestamp(records, header),
        name=_normalize_nonblank(state.conversation_metadata.get("name")),
    )


def project_agent_transcript_session_summary(
    header: ConversationHeader,
    records: Sequence[AgentTranscriptRecord],
    leaf_id: str | None,
    source_path: Path | None,
    *,
    locator: ConversationLocator | None = None,
    include_all_messages_text: bool = True,
) -> SessionSummary:
    """Project standard Agent transcript facts into one searchable summary."""

    entries = list(records)
    metadata = load_agent_transcript_session_metadata(header, entries)
    context = build_agent_transcript_session_context(entries, leaf_id)
    last_message_preview = next(
        (
            preview
            for message in reversed(context.messages)
            if (preview := _message_preview(message))
        ),
        None,
    )
    message_texts = (
        [text for message in context.messages if (text := _message_text(message))]
        if include_all_messages_text
        else []
    )
    first_message = next(
        (
            text
            for message in context.messages
            if isinstance(message, UserMessage) and (text := _message_text(message))
        ),
        "(no messages)",
    )
    diagnostic_count, last_diagnostic_code, last_diagnostic_level = _diagnostic_index(
        entries
    )
    return SessionSummary(
        session_id=header.conversation_id,
        cwd=agent_transcript_header_cwd(header),
        session_file=source_path,
        parent_session=agent_transcript_header_parent_session(header),
        leaf_id=leaf_id,
        created_at=metadata.created_at,
        updated_at=metadata.updated_at,
        name=metadata.name,
        message_count=len(context.messages),
        entry_count=len(entries),
        first_message=first_message,
        all_messages_text=" ".join(message_texts),
        last_message_preview=last_message_preview,
        model=context.model,
        has_diagnostics=diagnostic_count > 0,
        diagnostic_count=diagnostic_count,
        last_diagnostic_code=last_diagnostic_code,
        last_diagnostic_level=last_diagnostic_level,
        locator=locator,
    )


def build_agent_transcript_session_tree(
    nodes: Sequence[ConversationTreeNode[AgentTranscriptRecord]],
    *,
    labels_by_target_id: dict[str, str] | None = None,
    label_timestamps_by_target_id: dict[str, str] | None = None,
) -> list[SessionTreeNode[AgentTranscriptRecord]]:
    """Project a repository tree with standard display-label annotations."""

    labels = labels_by_target_id or {}
    timestamps = label_timestamps_by_target_id or {}

    def build(
        node: ConversationTreeNode[AgentTranscriptRecord],
    ) -> SessionTreeNode[AgentTranscriptRecord]:
        record = node.record
        return SessionTreeNode(
            record=record,
            children=tuple(build(child) for child in node.children),
            label=labels.get(record.record_id),
            label_timestamp=timestamps.get(record.record_id),
        )

    return [build(node) for node in nodes]


class AgentTranscriptSessionCatalog:
    """Agent projection facade over a provider-bound conversation catalog."""

    def __init__(
        self,
        session_dir: str | Path,
        *,
        index_writable: bool = True,
    ) -> None:
        absolute = Path(os.path.abspath(Path(session_dir).expanduser()))
        resolved_session_dir = absolute.parent.resolve(strict=False) / absolute.name
        layout = AgentTranscriptFileLayout(resolved_session_dir)
        self.session_dir: Path | None = resolved_session_dir
        self._layout: AgentTranscriptFileLayout | None = layout
        self._provider = ConversationProviderBinding(
            provider_id=(f"agent-conversation-jsonl:{resolved_session_dir.as_posix()}"),
            namespace=layout.namespace,
            store=create_agent_transcript_file_store(layout),
        )
        self._external_index: ConversationIndex[SessionSummary, SessionQuery] | None = (
            None
        )
        self._index_writable = index_writable
        self._session_file_for: Callable[[ConversationLocator], Path | None] = (
            lambda locator: layout.resolve_path(locator.key)
        )

    @classmethod
    def from_provider(
        cls,
        provider: ConversationProviderBinding[
            ConversationHeader,
            AgentTranscriptRecord,
        ],
        *,
        index: ConversationIndex[SessionSummary, SessionQuery] | None = None,
        session_file_for: (Callable[[ConversationLocator], Path | None] | None) = None,
    ) -> AgentTranscriptSessionCatalog:
        """Compose Agent projections over any registered Store provider."""

        catalog = cls.__new__(cls)
        catalog.session_dir = None
        catalog._layout = None
        catalog._provider = provider
        catalog._external_index = index
        catalog._index_writable = True
        catalog._session_file_for = session_file_for or (lambda locator: None)
        return catalog

    @property
    def index_path(self) -> Path:
        if self.session_dir is None:
            raise ValueError("provider-backed catalog has no local JSON index path")
        return self.session_dir / _SESSION_INDEX_FILENAME

    def list_records(self) -> list[SessionRecord]:
        return [
            SessionRecord(
                session_id=summary.session_id,
                cwd=summary.cwd,
                session_file=summary.session_file,
                parent_session=summary.parent_session,
                leaf_id=summary.leaf_id,
                metadata=SessionMetadata(
                    created_at=summary.created_at,
                    updated_at=summary.updated_at,
                    name=summary.name,
                ),
                locator=summary.locator,
            )
            for summary in self.list_summaries()
        ]

    def list_summaries(self) -> list[SessionSummary]:
        result = _run_catalog(self._catalog(indexed=False).scan())
        return _sort_summaries(item.projection for item in result.items)

    def list_path_summaries(
        self,
        *,
        session_id_prefix: str | None = None,
        read_budget: SessionDiscoveryReadBudget | None = None,
    ) -> list[SessionSummary]:
        """Project physical paths with bounded reads and no identity collapse."""

        if self._layout is None:
            return self.list_summaries()
        budget = read_budget or SessionDiscoveryReadBudget()
        if budget.remaining_candidates <= 0 or budget.remaining_bytes <= 0:
            budget.mark_incomplete()
            return []
        summaries: list[SessionSummary] = []
        candidates, complete = self._bounded_candidates_with_completeness()
        if not complete:
            budget.mark_incomplete()
        for candidate in candidates:
            header_charge = min(candidate.size, _MAX_PATH_SUMMARY_HEADER_BYTES)
            if not budget.reserve(candidates=1, bytes_=header_charge):
                break
            try:
                header = load_agent_transcript_header(candidate.path)
                if session_id_prefix is not None and not (
                    header.conversation_id.startswith(session_id_prefix)
                    or candidate.path.name == session_id_prefix
                ):
                    continue
                key = self._layout.key(header.conversation_id)
                locator = ConversationLocator(self._provider.provider_id, key)
                if (
                    candidate.size <= _MAX_PATH_SUMMARY_FILE_BYTES
                    and budget.reserve(bytes_=candidate.size - header_charge)
                ):
                    loaded_header, records = load_agent_transcript_file(
                        candidate.path,
                        max_bytes=_MAX_PATH_SUMMARY_FILE_BYTES,
                    )
                    if (
                        loaded_header.conversation_id != header.conversation_id
                        or session_file_authority_fingerprint(candidate.path)
                        != candidate.fingerprint
                    ):
                        continue
                    summary = project_agent_transcript_session_summary(
                        loaded_header,
                        records,
                        records[-1].record_id if records else None,
                        candidate.path,
                        locator=locator,
                    )
                    summaries.append(
                        replace(
                            summary,
                            authority_fingerprint=candidate.fingerprint,
                        )
                    )
                else:
                    summaries.append(
                        _header_only_session_summary(
                            header,
                            candidate,
                            locator=locator,
                        )
                    )
            except (OSError, ValueError):
                continue
        return _sort_summaries(summaries)

    def is_tombstoned(self, session_id: str) -> bool:
        """Return whether a validated local receipt retired this identity.

        Invalid or unreadable receipts raise ``StoreDataError`` so callers can
        fail closed and surface a typed discovery diagnostic.
        """

        if self._layout is None:
            return False
        return load_conversation_deletion_receipt(
            self.tombstone_path(session_id)
        ) is not None

    def list_path_collision_summaries(
        self,
        *,
        read_budget: SessionDiscoveryReadBudget | None = None,
    ) -> list[SessionSummary]:
        """Return header-only projections for physical paths sharing one ID."""

        if self._layout is None:
            return []
        budget = read_budget or SessionDiscoveryReadBudget(
            remaining_bytes=(
                _MAX_PATH_SUMMARY_HEADER_BYTES * 4096
            ),
        )
        by_id: dict[str, list[SessionSummary]] = {}
        candidates, complete = self._bounded_candidates_with_completeness()
        if not complete:
            budget.mark_incomplete()
        for candidate in candidates:
            if not budget.reserve(
                candidates=1,
                bytes_=min(candidate.size, _MAX_PATH_SUMMARY_HEADER_BYTES),
            ):
                break
            try:
                header = load_agent_transcript_header(candidate.path)
                key = self._layout.key(header.conversation_id)
                locator = ConversationLocator(self._provider.provider_id, key)
                summary = _header_only_session_summary(
                    header,
                    candidate,
                    locator=locator,
                )
                if (
                    session_file_authority_fingerprint(candidate.path)
                    != candidate.fingerprint
                ):
                    continue
            except (OSError, ValueError):
                continue
            by_id.setdefault(summary.session_id, []).append(summary)
        return _sort_summaries(
            summary
            for values in by_id.values()
            if len(values) > 1
            for summary in values
        )

    def tombstone_path(self, session_id: str) -> Path:
        """Return the authority-owned receipt path for one logical identity."""

        if self._layout is None:
            raise ValueError("provider-backed catalogs have no local tombstones")
        return self._layout.tombstone_path(self._layout.key(session_id))

    def find_summaries(
        self,
        query: SessionQuery | None = None,
    ) -> list[SessionSummary]:
        return filter_agent_transcript_session_summaries(
            self.list_summaries(), query or SessionQuery()
        )

    def refresh_index(self) -> list[SessionSummary]:
        before, before_complete = self._bounded_candidates_with_completeness()
        if not before_complete:
            raise RuntimeError("session authority scan was truncated")
        collision_budget = SessionDiscoveryReadBudget(
            remaining_bytes=_MAX_PATH_SUMMARY_HEADER_BYTES * 4096,
        )
        collisions = self.list_path_collision_summaries(
            read_budget=collision_budget
        )
        if collision_budget.truncated:
            raise RuntimeError("session authority scan was truncated")
        if collisions:
            raise RuntimeError("session authority contains duplicate identities")
        if self.session_dir is not None:
            self.session_dir.mkdir(parents=True, exist_ok=True)
        result = _run_catalog(self._catalog(indexed=True).refresh())
        after, after_complete = self._bounded_candidates_with_completeness()
        if not after_complete or _bounded_candidate_identities(
            before
        ) != _bounded_candidate_identities(after):
            if self.session_dir is not None:
                self.index_path.unlink(missing_ok=True)
            raise RuntimeError("session authority changed during index refresh")
        return _sort_summaries(item.projection for item in result.items)

    def repair_index(self) -> list[SessionSummary]:
        """Incrementally repair changed local transcripts, rebuilding as fallback."""

        collision_budget = SessionDiscoveryReadBudget(
            remaining_bytes=_MAX_PATH_SUMMARY_HEADER_BYTES * 4096,
        )
        collisions = self.list_path_collision_summaries(
            read_budget=collision_budget
        )
        if collision_budget.truncated:
            raise RuntimeError("session authority scan was truncated")
        if collisions:
            raise RuntimeError("session authority contains duplicate identities")

        if (
            self.session_dir is None
            or self._layout is None
            or not self.index_path.exists()
        ):
            return self.refresh_index()
        index = self._projection_index()
        query_snapshot = getattr(index, "query_snapshot", None)
        if query_snapshot is None:
            return self.refresh_index()
        snapshot = _run_catalog(query_snapshot(SessionQuery()))
        if snapshot.index_state != "fresh":
            return self.refresh_index()
        try:
            index_modified = self.index_path.stat().st_mtime_ns
            changed_paths = self._layout.transcript_paths_modified_after(index_modified)
            repaired = _run_catalog(
                self._repair_local_index(
                    snapshot.items,
                    changed_paths,
                )
            )
        except Exception:
            return self.refresh_index()
        return _sort_summaries(item.projection for item in repaired)

    def load_index(self) -> list[SessionSummary]:
        items = _run_catalog(self._projection_index().query(SessionQuery()))
        return [replace(item.projection, locator=item.locator) for item in items]

    def try_query_index_snapshot(
        self,
        query: SessionQuery | None = None,
        *,
        ignore_modified_paths: Sequence[str | Path] = (),
    ) -> ConversationIndexSnapshot[SessionSummary]:
        """Read the current projection index without scanning transcript authority."""

        index = self._projection_index()
        requested = query or SessionQuery()
        ignored_paths = tuple(
            Path(path).expanduser().resolve(strict=False)
            for path in ignore_modified_paths
        )
        query_snapshot = getattr(index, "query_snapshot", None)
        if query_snapshot is None:
            items = tuple(_run_catalog(index.query(requested)))
            snapshot = ConversationIndexSnapshot(
                items=items,
                index_state="unknown",
                index_generation="unknown",
                query_snapshot="unknown",
            )
        else:
            snapshot = _run_catalog(query_snapshot(requested))
        index_state = snapshot.index_state
        valid_items = tuple(
            item for item in snapshot.items if self._local_index_item_is_valid(item)
        )
        if len(valid_items) != len(snapshot.items):
            index_state = "stale"
        if (
            index_state == "fresh"
            and self.session_dir is not None
            and (
                any(
                    not _indexed_summary_authority_is_current(
                        item.projection, ignore_paths=ignored_paths
                    )
                    for item in valid_items
                )
                or self._local_index_is_older_than_authority(
                    ignore_modified_paths=ignored_paths,
                )
            )
        ):
            index_state = "stale"
        return ConversationIndexSnapshot(
            items=tuple(
                IndexedProjection(
                    locator=item.locator,
                    source_revision=item.source_revision,
                    projection=replace(item.projection, locator=item.locator),
                )
                for item in valid_items
            ),
            index_state=index_state,
            index_generation=snapshot.index_generation,
            query_snapshot=snapshot.query_snapshot,
        )

    def _local_index_item_is_valid(
        self,
        item: IndexedProjection[SessionSummary],
    ) -> bool:
        if self.session_dir is None or self._layout is None:
            return True
        summary = item.projection
        path = summary.session_file
        if (
            item.locator.provider_id != self._provider.provider_id
            or item.locator.key.namespace != self._layout.namespace
            or item.locator.key.conversation_id != summary.session_id
            or path is None
            or summary.authority_fingerprint is None
        ):
            return False
        absolute = Path(os.path.abspath(path.expanduser()))
        return (
            absolute.parent == self.session_dir
            and absolute.suffix == ".jsonl"
            and not absolute.name.endswith("-export.jsonl")
        )

    def bounded_index_snapshot(
        self,
        query: SessionQuery | None = None,
        *,
        enrich_limit: int = _BOUNDED_ENRICH_LIMIT,
        segment_bytes: int = _BOUNDED_SEGMENT_BYTES,
        read_budget: SessionDiscoveryReadBudget | None = None,
    ) -> BoundedSessionCatalogSnapshot:
        """Build a bounded resume view without replaying transcript authority.

        Every candidate is discovered with directory metadata, but only the most
        recent ``enrich_limit`` files are opened. Each opened file contributes at
        most one head and one tail segment. The result is deliberately partial and
        is never written to the authoritative projection index.
        """

        if self._layout is None or self.session_dir is None:
            return BoundedSessionCatalogSnapshot((), 0, 0, 0)
        if type(enrich_limit) is not int or enrich_limit < 1:
            raise ValueError("bounded catalog enrich limit must be positive")
        if type(segment_bytes) is not int or segment_bytes < 1:
            raise ValueError("bounded catalog segment size must be positive")

        budget = read_budget
        if budget is not None and (
            budget.remaining_candidates <= 0 or budget.remaining_bytes <= 0
        ):
            budget.mark_incomplete()
            return BoundedSessionCatalogSnapshot((), 0, 0, 0, complete=False)
        candidates, complete = self._bounded_candidates_with_completeness()
        if budget is not None:
            allowed = min(len(candidates), budget.remaining_candidates)
            if allowed < len(candidates):
                budget.mark_incomplete()
            budget.reserve(candidates=allowed)
            candidates = candidates[:allowed]
            enriched: list[_BoundedSessionCandidate] = []
            for candidate in candidates[:enrich_limit]:
                charge = min(candidate.size, segment_bytes * 2)
                if not budget.reserve(bytes_=charge):
                    break
                enriched.append(candidate)
            selected_candidates: Sequence[_BoundedSessionCandidate] = enriched
        else:
            selected_candidates = candidates[:enrich_limit]
        projected, bytes_read = self._project_bounded_candidates(
            selected_candidates,
            segment_bytes=segment_bytes,
        )

        selected = _query_indexed_summaries(query or SessionQuery(), projected)
        return BoundedSessionCatalogSnapshot(
            items=selected,
            authority_count=len(candidates),
            enriched_count=len(selected_candidates),
            bytes_read=bytes_read,
            complete=complete and not (budget is not None and budget.truncated),
        )

    def refresh_bounded_index(
        self,
        *,
        segment_bytes: int = _BOUNDED_SEGMENT_BYTES,
    ) -> list[SessionSummary]:
        """Replace a missing/stale local index without replaying transcript bodies.

        The scan may read at most one head and one tail segment per authority file.
        It publishes only if the directory's stat identities remain stable for the
        complete scan, preventing a racing append from being mistaken for a fresh
        index. Individual invalid transcript candidates remain omitted just as they
        are from the authoritative catalog scan.
        """

        if self._layout is None or self.session_dir is None:
            raise ValueError("provider-backed catalogs cannot build a bounded index")
        if type(segment_bytes) is not int or segment_bytes < 1:
            raise ValueError("bounded catalog segment size must be positive")
        self.session_dir.mkdir(parents=True, exist_ok=True)
        before, before_complete = self._bounded_candidates_with_completeness()
        if not before_complete:
            raise RuntimeError("session authority scan was truncated")
        projected, _bytes_read = self._project_bounded_candidates(
            before,
            segment_bytes=segment_bytes,
        )
        if len({item.projection.session_id for item in projected}) != len(projected):
            raise RuntimeError("session authority contains duplicate identities")
        after, after_complete = self._bounded_candidates_with_completeness()
        if not after_complete:
            raise RuntimeError("session authority scan was truncated")
        if _bounded_candidate_identities(before) != _bounded_candidate_identities(
            after
        ):
            raise RuntimeError("session authority changed during bounded index refresh")
        published = _run_catalog(self._projection_index().replace(projected))
        return _sort_summaries(item.projection for item in published)

    def _project_bounded_candidates(
        self,
        candidates: Sequence[_BoundedSessionCandidate],
        *,
        segment_bytes: int,
    ) -> tuple[list[IndexedProjection[SessionSummary]], int]:
        if self._layout is None:
            raise ValueError("provider-backed catalogs have no local file layout")
        projected: list[IndexedProjection[SessionSummary]] = []
        bytes_read = 0
        for candidate in candidates:
            result = _project_bounded_session_summary(
                candidate,
                segment_bytes=segment_bytes,
            )
            if result is None:
                continue
            summary, consumed = result
            bytes_read += consumed
            key = self._layout.key(summary.session_id)
            self._layout.bind_path(key, candidate.path)
            locator = ConversationLocator(self._provider.provider_id, key)
            projected.append(
                IndexedProjection(
                    locator=locator,
                    source_revision=summary.entry_count,
                    projection=replace(summary, locator=locator),
                )
            )
        return projected, bytes_read

    def _bounded_candidates(self) -> tuple[_BoundedSessionCandidate, ...]:
        return self._bounded_candidates_with_completeness()[0]

    def _bounded_candidates_with_completeness(
        self,
    ) -> tuple[tuple[_BoundedSessionCandidate, ...], bool]:
        if self._layout is None:
            return (), True
        scan = self._layout.scan_candidate_path_snapshot(self._layout.namespace)
        return _bounded_session_candidates(scan.paths), scan.complete

    async def upsert_summary(
        self,
        summary: SessionSummary,
        *,
        source_revision: int,
    ) -> bool:
        """Incrementally publish one authoritative local transcript summary."""

        if self.session_dir is None or self._layout is None:
            raise ValueError("provider-backed catalogs require an explicit locator")
        if summary.session_file is None:
            raise ValueError("local session summary has no transcript path")
        if source_revision != summary.entry_count:
            raise ValueError("session summary revision must equal its entry count")
        key = self._layout.bind_existing_path(summary.session_file)
        if key.conversation_id != summary.session_id:
            raise ValueError("session summary identity does not match its transcript")
        locator = ConversationLocator(self._provider.provider_id, key)
        indexed_summary = _summary_with_authority_fingerprint(summary)
        return await self._projection_index().upsert(
            IndexedProjection(
                locator=locator,
                source_revision=source_revision,
                projection=replace(indexed_summary, locator=locator),
            )
        )

    def load_authoritative_revision(self, locator: ConversationLocator) -> int:
        """Load one selected authority object and return its current revision."""

        if locator.provider_id != self._provider.provider_id:
            raise ValueError("conversation locator belongs to another provider")
        if locator.key.namespace != self._provider.namespace:
            raise ValueError("conversation locator belongs to another namespace")
        result = _run_catalog(self._provider.store.load(locator.key))
        return result.snapshot.revision

    def list_indexed_summaries(self, *, refresh: bool = False) -> list[SessionSummary]:
        if self._external_index is not None:
            summaries = self.refresh_index() if refresh else self.load_index()
            return summaries or self.refresh_index()
        if refresh:
            return self.refresh_index()
        snapshot = self.try_query_index_snapshot()
        if snapshot.index_state == "fresh":
            return [item.projection for item in snapshot.items]
        return [item.projection for item in self.bounded_index_snapshot().items]

    def find_indexed_summaries(
        self,
        query: SessionQuery | None = None,
    ) -> list[SessionSummary]:
        return filter_agent_transcript_session_summaries(
            self.list_indexed_summaries(), query or SessionQuery()
        )

    def _catalog(
        self,
        *,
        indexed: bool,
    ) -> ConversationCatalog[
        ConversationHeader,
        AgentTranscriptRecord,
        SessionSummary,
        SessionQuery,
    ]:
        return ConversationCatalog(
            providers=(self._provider,),
            projector=FunctionalConversationProjector(
                self._project_index_summary if indexed else self._project_summary
            ),
            record_id=lambda record: record.record_id,
            index=self._projection_index() if indexed else None,
            query_items=_query_indexed_summaries,
            publish_partial=True,
        )

    def _project_summary(
        self,
        header: ConversationHeader,
        records: Sequence[AgentTranscriptRecord],
        leaf_id: str | None,
        locator: ConversationLocator,
    ) -> SessionSummary:
        return project_agent_transcript_session_summary(
            header,
            records,
            leaf_id,
            self._session_file_for(locator),
            locator=locator,
        )

    def _project_index_summary(
        self,
        header: ConversationHeader,
        records: Sequence[AgentTranscriptRecord],
        leaf_id: str | None,
        locator: ConversationLocator,
    ) -> SessionSummary:
        return _summary_with_authority_fingerprint(
            project_agent_transcript_session_summary(
                header,
                records,
                leaf_id,
                self._session_file_for(locator),
                locator=locator,
                include_all_messages_text=False,
            )
        )

    def _projection_index(
        self,
    ) -> ConversationIndex[SessionSummary, SessionQuery]:
        if self._external_index is not None:
            return self._external_index
        return JsonConversationIndex(
            self.index_path,
            version=_SESSION_INDEX_VERSION,
            codec=FunctionalProjectionCodec(
                encoder=_summary_to_index_item,
                decoder=_decode_summary_index_item,
            ),
            query_items=_query_indexed_summaries,
            writable=self._index_writable,
        )

    async def _repair_local_index(
        self,
        indexed: Sequence[IndexedProjection[SessionSummary]],
        changed_paths: Sequence[Path],
    ) -> tuple[IndexedProjection[SessionSummary], ...]:
        if self._layout is None:
            raise ValueError("provider-backed catalogs cannot repair a local index")
        index = self._projection_index()
        replacement = {item.locator: item for item in indexed}
        updated_locators: set[ConversationLocator] = set()
        for path in changed_paths:
            key = self._layout.bind_existing_path(path)
            locator = ConversationLocator(self._provider.provider_id, key)
            load_result = await self._provider.store.load(key)
            authority = load_result.snapshot
            leaf_id = authority.records[-1].record_id if authority.records else None
            summary = self._project_index_summary(
                authority.header,
                authority.records,
                leaf_id,
                locator,
            )
            replacement[locator] = IndexedProjection(
                locator=locator,
                source_revision=authority.revision,
                projection=summary,
            )
            updated_locators.add(locator)

        changed = bool(changed_paths)
        for item in indexed:
            session_file = item.projection.session_file
            if item.locator not in updated_locators and (
                session_file is None or not session_file.is_file()
            ):
                replacement.pop(item.locator, None)
                changed = True
        repaired = (
            await index.replace(tuple(replacement.values()))
            if changed
            else tuple(replacement.values())
        )
        return tuple(
            IndexedProjection(
                locator=item.locator,
                source_revision=item.source_revision,
                projection=replace(item.projection, locator=item.locator),
            )
            for item in repaired
        )

    def _local_index_is_older_than_authority(
        self,
        *,
        ignore_modified_paths: Sequence[str | Path] = (),
    ) -> bool:
        if self.session_dir is None or self._layout is None:
            return False
        try:
            index_modified = self.index_path.stat().st_mtime_ns
            ignored = tuple(
                Path(path).expanduser().resolve(strict=False)
                for path in ignore_modified_paths
            )
            return any(
                not any(
                    same_agent_transcript_session_path(path, ignored_path)
                    for ignored_path in ignored
                )
                for path in self._layout.transcript_paths_modified_after(
                    index_modified,
                )
            )
        except OSError:
            return True


def list_all_agent_transcript_session_summaries(
    sessions_root: str | Path,
) -> list[SessionSummary]:
    root = Path(sessions_root)
    if not root.exists():
        return []
    summaries = AgentTranscriptSessionCatalog(root).list_summaries()
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if child.is_dir():
            summaries.extend(AgentTranscriptSessionCatalog(child).list_summaries())
    summaries.sort(key=lambda summary: summary.updated_at, reverse=True)
    return summaries


def find_all_agent_transcript_session_summaries(
    sessions_root: str | Path,
    query: SessionQuery | None = None,
) -> list[SessionSummary]:
    return filter_agent_transcript_session_summaries(
        list_all_agent_transcript_session_summaries(sessions_root),
        query or SessionQuery(),
    )


def refresh_all_agent_transcript_session_indexes(
    sessions_root: str | Path,
) -> list[SessionSummary]:
    root = Path(sessions_root)
    root.mkdir(parents=True, exist_ok=True)
    summaries = AgentTranscriptSessionCatalog(root).refresh_index()
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if child.is_dir():
            summaries.extend(AgentTranscriptSessionCatalog(child).refresh_index())
    summaries.sort(key=lambda summary: summary.updated_at, reverse=True)
    return summaries


def list_all_indexed_agent_transcript_session_summaries(
    sessions_root: str | Path,
    *,
    refresh: bool = False,
) -> list[SessionSummary]:
    if refresh:
        return refresh_all_agent_transcript_session_indexes(sessions_root)
    root = Path(sessions_root)
    if not root.exists():
        return []
    summaries = AgentTranscriptSessionCatalog(root).list_indexed_summaries()
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if child.is_dir():
            summaries.extend(
                AgentTranscriptSessionCatalog(child).list_indexed_summaries()
            )
    summaries.sort(key=lambda summary: summary.updated_at, reverse=True)
    return summaries


def find_all_indexed_agent_transcript_session_summaries(
    sessions_root: str | Path,
    query: SessionQuery | None = None,
) -> list[SessionSummary]:
    return filter_agent_transcript_session_summaries(
        list_all_indexed_agent_transcript_session_summaries(sessions_root),
        query or SessionQuery(),
    )


def session_summary_revision(
    summary: SessionSummary,
    source_revision: int,
) -> str:
    """Return the opaque revision used by continuity selection."""

    return summary.authority_fingerprint or str(source_revision)


def session_summary_authority_is_current(summary: SessionSummary) -> bool:
    """Revalidate a fingerprinted summary without parsing its transcript."""

    if summary.authority_fingerprint is None:
        return True
    if summary.session_file is None:
        return False
    try:
        current = _bounded_candidate(summary.session_file)
    except OSError:
        return False
    return current is not None and current.fingerprint == summary.authority_fingerprint


def session_file_authority_fingerprint(path: str | Path) -> str:
    """Return a no-follow stat identity suitable for copy-time revalidation."""

    candidate = _bounded_candidate(Path(path))
    if candidate is None:
        raise OSError("session source must be a direct regular file")
    return candidate.fingerprint


def _summary_with_authority_fingerprint(summary: SessionSummary) -> SessionSummary:
    if summary.session_file is None:
        return summary
    try:
        candidate = _bounded_candidate(summary.session_file)
    except OSError:
        return summary
    if candidate is None:
        return summary
    return replace(summary, authority_fingerprint=candidate.fingerprint)


def _header_only_session_summary(
    header: ConversationHeader,
    candidate: _BoundedSessionCandidate,
    *,
    locator: ConversationLocator,
) -> SessionSummary:
    updated_at = (
        datetime.fromtimestamp(candidate.mtime_ns / 1_000_000_000, UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return SessionSummary(
        session_id=header.conversation_id,
        cwd=agent_transcript_header_cwd(header),
        session_file=candidate.path,
        parent_session=agent_transcript_header_parent_session(header),
        leaf_id=None,
        created_at=header.created_at,
        updated_at=updated_at,
        name=_normalize_nonblank(header.metadata.get("name")),
        message_count=0,
        entry_count=0,
        first_message="(preview unavailable)",
        all_messages_text="",
        last_message_preview=None,
        model=None,
        locator=locator,
        authority_fingerprint=candidate.fingerprint,
        bounded=True,
        counts_exact=False,
    )


def _bounded_session_candidates(
    paths: Sequence[Path],
) -> tuple[_BoundedSessionCandidate, ...]:
    candidates: list[_BoundedSessionCandidate] = []
    for path in paths:
        try:
            candidate = _bounded_candidate(path)
        except OSError:
            continue
        if candidate is not None:
            candidates.append(candidate)
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (candidate.mtime_ns, candidate.path.name),
            reverse=True,
        )
    )


def _bounded_candidate(path: Path) -> _BoundedSessionCandidate | None:
    status = path.lstat()
    if not stat_module.S_ISREG(status.st_mode) or _status_is_link_or_reparse(status):
        return None
    fingerprint = _status_fingerprint(status)
    return _BoundedSessionCandidate(
        path=path,
        size=status.st_size,
        mtime_ns=status.st_mtime_ns,
        fingerprint=fingerprint,
    )


def _status_fingerprint(status: os.stat_result) -> str:
    return (
        f"stat-v1:{status.st_dev}:{status.st_ino}:{status.st_size}:"
        f"{status.st_mtime_ns}:{status.st_ctime_ns}"
    )


def _status_is_link_or_reparse(status: os.stat_result) -> bool:
    return stat_module.S_ISLNK(status.st_mode) or bool(
        getattr(status, "st_file_attributes", 0)
        & getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _open_file_no_follow(path: Path) -> tuple[int, int]:
    flags = os.O_RDONLY
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


def _bounded_candidate_identities(
    candidates: Sequence[_BoundedSessionCandidate],
) -> tuple[tuple[Path, str], ...]:
    return tuple((candidate.path, candidate.fingerprint) for candidate in candidates)


def _project_bounded_session_summary(
    candidate: _BoundedSessionCandidate,
    *,
    segment_bytes: int,
) -> tuple[SessionSummary, int] | None:
    try:
        head, tail = _read_bounded_segments(candidate, segment_bytes=segment_bytes)
        current = _bounded_candidate(candidate.path)
    except OSError:
        return None
    if current is None or current.fingerprint != candidate.fingerprint:
        return None

    lines = {
        offset: line
        for offset, line in (
            *_complete_segment_lines(
                head,
                start=0,
                total_size=candidate.size,
                drop_first=False,
            ),
            *_complete_segment_lines(
                tail,
                start=max(0, candidate.size - len(tail)),
                total_size=candidate.size,
                drop_first=candidate.size > len(tail),
            ),
        )
    }
    header: ConversationHeader | None = None
    records: list[AgentTranscriptRecord] = []
    for _offset, line in sorted(lines.items()):
        try:
            value = json.loads(
                line.decode("utf-8"), parse_constant=_reject_json_constant
            )
        except (UnicodeError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(value, dict):
            continue
        if value.get("type") == "conversation" and header is None:
            try:
                header = _HEADER_CODEC.decode_header(value)
            except Exception:
                return None
            continue
        if value.get("type") != "record":
            continue
        try:
            records.append(
                cast(AgentTranscriptRecord, _RECORD_CODEC.decode_record(value))
            )
        except Exception:
            continue
    if header is None:
        return None

    name = _normalize_nonblank(header.metadata.get("name"))
    messages: list[AgentMessage] = []
    model: dict[str, str] | None = None
    for record in records:
        if record.kind == AGENT_MESSAGE_KIND and isinstance(
            record.payload,
            UserMessage | AssistantMessage | ToolResultMessage,
        ):
            messages.append(record.payload)
        elif record.kind == CONVERSATION_METADATA_PATCH_KIND and isinstance(
            record.payload,
            ConversationMetadataPatch,
        ):
            if "name" in record.payload.removed_keys:
                name = None
            if "name" in record.payload.values:
                name = _normalize_nonblank(record.payload.values["name"])
        elif record.kind == MODEL_SELECTION_KIND and isinstance(
            record.payload,
            ModelSelectionSnapshot,
        ):
            model = {
                "provider": record.payload.provider,
                "endpoint_id": record.payload.endpoint_id,
                "model_id": record.payload.model_id,
            }

    message_texts = [text for item in messages if (text := _message_text(item))]
    first_message = next(
        (
            text
            for item in messages
            if isinstance(item, UserMessage) and (text := _message_text(item))
        ),
        message_texts[0] if message_texts else "(preview unavailable)",
    )
    last_message_preview = next(
        (preview for item in reversed(messages) if (preview := _message_preview(item))),
        None,
    )
    diagnostic_count, last_diagnostic_code, last_diagnostic_level = _diagnostic_index(
        records
    )
    updated_at = (
        datetime.fromtimestamp(candidate.mtime_ns / 1_000_000_000, UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return (
        SessionSummary(
            session_id=header.conversation_id,
            cwd=agent_transcript_header_cwd(header),
            session_file=candidate.path,
            parent_session=agent_transcript_header_parent_session(header),
            leaf_id=records[-1].record_id if records else None,
            created_at=header.created_at,
            updated_at=updated_at,
            name=name,
            message_count=len(messages),
            entry_count=len(records),
            first_message=first_message,
            all_messages_text="",
            last_message_preview=last_message_preview,
            model=model,
            has_diagnostics=diagnostic_count > 0,
            diagnostic_count=diagnostic_count,
            last_diagnostic_code=last_diagnostic_code,
            last_diagnostic_level=last_diagnostic_level,
            authority_fingerprint=candidate.fingerprint,
            bounded=True,
            counts_exact=candidate.size <= segment_bytes * 2,
        ),
        len(head) + len(tail),
    )


def _read_bounded_segments(
    candidate: _BoundedSessionCandidate,
    *,
    segment_bytes: int,
) -> tuple[bytes, bytes]:
    before = candidate.path.lstat()
    if not stat_module.S_ISREG(before.st_mode) or _status_is_link_or_reparse(before):
        raise OSError("session candidate must be a direct regular file")
    if _status_fingerprint(before) != candidate.fingerprint:
        raise OSError("session candidate identity changed")
    descriptor = -1
    parent_descriptor = -1
    try:
        descriptor, parent_descriptor = _open_file_no_follow(candidate.path)
        opened = os.fstat(descriptor)
        if not _same_file_status(before, opened):
            raise OSError("session candidate identity changed")
        head = _read_descriptor_bytes(
            descriptor,
            min(segment_bytes, candidate.size),
        )
        tail = b""
        if candidate.size > segment_bytes:
            tail_size = min(segment_bytes, candidate.size)
            os.lseek(descriptor, candidate.size - tail_size, os.SEEK_SET)
            tail = _read_descriptor_bytes(descriptor, tail_size)
        after = os.fstat(descriptor)
        current = candidate.path.lstat()
        if not _same_file_status(before, after) or not _same_file_status(
            before, current
        ):
            raise OSError("session candidate changed while reading")
        return head, tail
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def _read_descriptor_bytes(descriptor: int, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = os.read(descriptor, remaining)
        if not chunk:
            raise OSError("session candidate was truncated while reading")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _complete_segment_lines(
    data: bytes,
    *,
    start: int,
    total_size: int,
    drop_first: bool,
) -> tuple[tuple[int, bytes], ...]:
    lines: list[tuple[int, bytes]] = []
    offset = start
    for index, line in enumerate(data.splitlines(keepends=True)):
        line_start = offset
        offset += len(line)
        if drop_first and index == 0:
            continue
        complete = line.endswith((b"\n", b"\r")) or offset == total_size
        if not complete:
            continue
        stripped = line.strip()
        if stripped:
            lines.append((line_start, stripped))
    return tuple(lines)


def _reject_json_constant(token: str) -> None:
    raise ValueError(f"invalid JSON constant {token!r}")


def filter_agent_transcript_session_summaries(
    summaries: Sequence[SessionSummary],
    query: SessionQuery,
) -> list[SessionSummary]:
    def matches(summary: SessionSummary) -> bool:
        if query.cwd is not None and not _same_session_cwd(summary.cwd, query.cwd):
            return False
        if query.source_mode is not None and (
            summary.discovery is None
            or summary.discovery.mode != query.source_mode
        ):
            return False
        if (
            query.name is not None
            and query.name.lower() not in (summary.name or "").lower()
        ):
            return False
        if (
            query.named is not None
            and bool(_normalize_nonblank(summary.name)) is not query.named
        ):
            return False
        if query.parent_session is not None and not _same_session_reference(
            summary.parent_session, query.parent_session
        ):
            return False
        if (
            query.has_diagnostics is not None
            and summary.has_diagnostics is not query.has_diagnostics
        ):
            return False
        if (
            query.has_messages is not None
            and (summary.message_count > 0) is not query.has_messages
        ):
            return False
        if query.text is not None and _session_query_score(summary, query.text) is None:
            return False
        return True

    sort_key = None
    reverse = False
    if query.sort_by == "relevance" and query.text is not None:
        query_text = query.text

        def relevance_sort_key(summary: SessionSummary) -> tuple[int, str]:
            return _session_query_score(summary, query_text) or 0, summary.updated_at

        sort_key = relevance_sort_key
        reverse = True
    return list(
        ProjectionQuery(
            predicate=matches,
            sort_key=sort_key,
            reverse=reverse,
            limit=query.limit,
        ).apply(summaries)
    )


def _same_session_cwd(left: str, right: str) -> bool:
    if left == right:
        return True
    if not left or not right:
        return False
    try:
        normalized_left = os.path.normcase(os.path.realpath(os.path.expanduser(left)))
        normalized_right = os.path.normcase(os.path.realpath(os.path.expanduser(right)))
    except (OSError, ValueError):
        return False
    return normalized_left == normalized_right


def _message_preview(message: AgentMessage) -> str | None:
    if isinstance(message, UserMessage | AssistantMessage | ToolResultMessage):
        parts = getattr(message, "content", None)
        if isinstance(parts, str):
            text = parts
        elif isinstance(parts, list):
            text = " ".join(part.text for part in parts if isinstance(part, TextPart))
        else:
            text = ""
        normalized = " ".join(text.split())
        return normalized[:160] if normalized else None
    if isinstance(message, ApplicationMessage) and isinstance(message.content, str):
        return " ".join(message.content.split())[:160] or None
    return None


def _message_text(message: AgentMessage) -> str | None:
    if not isinstance(message, UserMessage | AssistantMessage):
        return None
    parts = getattr(message, "content", None)
    if isinstance(parts, str):
        text = parts
    elif isinstance(parts, list):
        text = " ".join(part.text for part in parts if isinstance(part, TextPart))
    else:
        text = ""
    normalized = " ".join(text.split())
    return normalized or None


def _last_activity_timestamp(
    records: Sequence[AgentTranscriptRecord],
    header: ConversationHeader,
) -> str:
    last_message_timestamp: float | None = None
    last_record_timestamp: str | None = None
    for record in records:
        if record.kind != AGENT_MESSAGE_KIND or not isinstance(
            record.payload, UserMessage | AssistantMessage
        ):
            continue
        timestamp = getattr(record.payload, "timestamp", None)
        if isinstance(timestamp, int | float) and timestamp > 0:
            last_message_timestamp = max(
                last_message_timestamp or 0,
                _normalize_unix_timestamp_seconds(float(timestamp)),
            )
        else:
            last_record_timestamp = record.created_at
    if last_message_timestamp is not None:
        return (
            datetime.fromtimestamp(last_message_timestamp, UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
    return last_record_timestamp or header.created_at


def _normalize_unix_timestamp_seconds(timestamp: float) -> float:
    # Agent messages normally use milliseconds; tolerate older second values.
    if timestamp <= 32_503_680_000:
        return timestamp
    normalized = timestamp / 1000
    log.problem(
        "session_timestamp_normalized",
        severity="warning",
        source="session",
        message=(
            "Session message timestamp looked like milliseconds and was normalized "
            "to seconds."
        ),
        recoverable=True,
        original_timestamp=timestamp,
        normalized_timestamp=normalized,
        unit="milliseconds",
    )
    return normalized


def _diagnostic_index(
    records: Sequence[AgentTranscriptRecord],
) -> tuple[int, str | None, str | None]:
    diagnostics = [
        record.payload
        for record in records
        if record.kind == EXTENSION_DATA_KIND
        and isinstance(record.payload, ExtensionData)
        and record.payload.extension_type in {"diagnostic", "diagnostics"}
    ]
    if not diagnostics:
        return 0, None, None
    last = diagnostics[-1].data
    code = last.get("code") if isinstance(last, dict) else None
    level = last.get("level", last.get("type")) if isinstance(last, dict) else None
    return (
        len(diagnostics),
        code if isinstance(code, str) and code else None,
        level if isinstance(level, str) and level else None,
    )


def _summary_to_index_item(summary: SessionSummary) -> dict[str, object]:
    return {
        "session_id": summary.session_id,
        "cwd": summary.cwd,
        "session_file": summary.session_file.as_posix()
        if summary.session_file is not None
        else None,
        "parent_session": summary.parent_session,
        "leaf_id": summary.leaf_id,
        "created_at": summary.created_at,
        "updated_at": summary.updated_at,
        "name": summary.name,
        "message_count": summary.message_count,
        "entry_count": summary.entry_count,
        "first_message": summary.first_message,
        "last_message_preview": summary.last_message_preview,
        "model": dict(summary.model) if summary.model is not None else None,
        "has_diagnostics": summary.has_diagnostics,
        "diagnostic_count": summary.diagnostic_count,
        "last_diagnostic_code": summary.last_diagnostic_code,
        "last_diagnostic_level": summary.last_diagnostic_level,
        "authority_fingerprint": summary.authority_fingerprint,
        "bounded": summary.bounded,
        "counts_exact": summary.counts_exact,
    }


def _decode_summary_index_item(value: Mapping[str, object]) -> SessionSummary:
    session_id = _string(value.get("session_id"))
    if not session_id:
        raise ValueError("session index summary is invalid")
    return SessionSummary(
        session_id=session_id,
        cwd=_string(value.get("cwd")),
        session_file=_optional_path(value.get("session_file")),
        parent_session=_optional_string(value.get("parent_session")),
        leaf_id=_optional_string(value.get("leaf_id")),
        created_at=_string(value.get("created_at")),
        updated_at=_string(value.get("updated_at")),
        name=_optional_string(value.get("name")),
        message_count=_int(value.get("message_count")),
        entry_count=_int(value.get("entry_count")),
        first_message=_string(value.get("first_message")),
        all_messages_text="",
        last_message_preview=_optional_string(value.get("last_message_preview")),
        model=_model(value.get("model")),
        has_diagnostics=_bool(value.get("has_diagnostics")),
        diagnostic_count=_int(value.get("diagnostic_count")),
        last_diagnostic_code=_optional_string(value.get("last_diagnostic_code")),
        last_diagnostic_level=_optional_string(value.get("last_diagnostic_level")),
        authority_fingerprint=_optional_string(value.get("authority_fingerprint")),
        bounded=_bool(value.get("bounded")),
        counts_exact=_bool(value.get("counts_exact", True)),
    )


def _indexed_summary_authority_is_current(
    summary: SessionSummary,
    *,
    ignore_paths: Sequence[Path],
) -> bool:
    session_file = summary.session_file
    if session_file is None:
        return False
    if any(
        same_agent_transcript_session_path(
            session_file,
            path,
        )
        for path in ignore_paths
    ):
        return True
    if summary.authority_fingerprint is not None:
        return session_summary_authority_is_current(summary)
    return session_file.is_file()


def _session_haystack(summary: SessionSummary) -> str:
    return " ".join(
        value
        for value in (
            summary.session_id,
            summary.cwd,
            summary.name or "",
            summary.first_message,
            summary.last_message_preview or "",
            summary.last_diagnostic_code or "",
            summary.last_diagnostic_level or "",
            summary.session_file.name if summary.session_file is not None else "",
        )
        if value
    )


def _session_query_score(summary: SessionSummary, text: str) -> int | None:
    query = text.strip()
    if not query:
        return 0
    haystack = _normalize_query_text(_session_haystack(summary))
    if query.startswith("re:"):
        try:
            match = re.search(query[3:], haystack, flags=re.IGNORECASE)
        except re.error:
            return None
        return 1000 - match.start() if match else None
    needle = (
        _normalize_query_text(query[1:-1])
        if len(query) >= 2 and query[0] == query[-1] == '"'
        else _normalize_query_text(query)
    )
    index = haystack.lower().find(needle.lower())
    return 1000 - index if index >= 0 else None


def _normalize_nonblank(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _normalize_query_text(text: str) -> str:
    return " ".join(text.split())


def _same_session_reference(left: str | None, right: str | None) -> bool:
    if left == right:
        return True
    if not left or not right:
        return False
    return same_agent_transcript_session_path(
        Path(left).expanduser(), Path(right).expanduser()
    )


def same_agent_transcript_session_path(left: Path, right: Path) -> bool:
    """Compare canonical existing transcript paths without requiring existence."""

    try:
        return left.resolve(strict=False) == right.resolve(strict=False)
    except OSError:
        return left == right


def _optional_path(value: object) -> Path | None:
    return Path(value) if isinstance(value, str) and value else None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _bool(value: object) -> bool:
    return value if isinstance(value, bool) else False


def _model(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    provider = value.get("provider")
    endpoint_id = value.get("endpoint_id") or value.get("endpointId")
    model_id = value.get("model_id")
    if (
        not isinstance(provider, str)
        or not isinstance(endpoint_id, str)
        or not isinstance(model_id, str)
    ):
        return None
    return {
        "provider": provider,
        "endpoint_id": endpoint_id,
        "model_id": model_id,
    }


def _sort_summaries(summaries) -> list[SessionSummary]:
    return sorted(summaries, key=lambda summary: summary.updated_at, reverse=True)


def _query_indexed_summaries(
    query: SessionQuery,
    items: Sequence[IndexedProjection[SessionSummary]],
) -> tuple[IndexedProjection[SessionSummary], ...]:
    timestamp_field = "created_at" if query.sort_by == "created" else "updated_at"
    ordered = sorted(
        items,
        key=lambda item: getattr(item.projection, timestamp_field),
        reverse=True,
    )
    selected = filter_agent_transcript_session_summaries(
        [item.projection for item in ordered],
        query,
    )
    by_identity = {id(item.projection): item for item in ordered}
    return tuple(by_identity[id(summary)] for summary in selected)


def _run_catalog(awaitable):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, awaitable).result()


__all__ = [
    "AgentTranscriptSessionCatalog",
    "BoundedSessionCatalogSnapshot",
    "SessionMetadata",
    "SessionQuery",
    "SessionRecord",
    "SessionSummary",
    "SessionDiscoveryReadBudget",
    "SessionTreeNode",
    "agent_transcript_header_cwd",
    "agent_transcript_header_parent_session",
    "build_agent_transcript_label_indexes",
    "build_agent_transcript_session_context",
    "build_agent_transcript_session_tree",
    "filter_agent_transcript_session_summaries",
    "find_all_agent_transcript_session_summaries",
    "find_all_indexed_agent_transcript_session_summaries",
    "list_all_agent_transcript_session_summaries",
    "list_all_indexed_agent_transcript_session_summaries",
    "load_agent_transcript_session_metadata",
    "project_agent_transcript_session_summary",
    "refresh_all_agent_transcript_session_indexes",
    "same_agent_transcript_session_path",
    "session_summary_authority_is_current",
    "session_file_authority_fingerprint",
    "session_summary_revision",
]
