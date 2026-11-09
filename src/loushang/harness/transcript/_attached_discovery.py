"""Pinned discovery and attached-owner observation over original Transcript IO."""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from loushang.harness.conversation import ConversationHeader, StoreDataError
from loushang.harness.conversation.jsonl_codec import ConversationJsonlRecordCodec
from loushang.harness.transcript.directory import AgentTranscriptDirectoryRuntime
from loushang.harness.transcript.discovery import (
    SessionDiscoveryMetadata,
    SessionDiscoverySource,
)
from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileError,
    load_agent_transcript_file,
)
from loushang.harness.transcript.types import AgentTranscriptRecord


class _AttachedTranscriptReadPort(Protocol):
    def get_header(self) -> ConversationHeader: ...

    def get_entries(self) -> list[AgentTranscriptRecord]: ...

    def get_session_file(self) -> Path | None: ...


class _AttachedDiscoveryMethods:
    """No second state or writer: use the original facade's borrowed owners."""

    _directory: AgentTranscriptDirectoryRuntime
    _session_id: str
    _selected_session_file: Path | None
    _authority_source: SessionDiscoverySource
    _discovery_sources: tuple[SessionDiscoverySource, ...]
    _attached_session: _AttachedTranscriptReadPort | None
    _attached_identity: tuple[int, int] | None
    _attached_source: tuple[str, str, str, str, Path] | None
    _attached_revision: str | None
    _record_codec: ConversationJsonlRecordCodec

    def _discovery_error(self, suffix: str) -> RuntimeError:
        raise NotImplementedError("the original Product diagnostic value is required")

    def _attached_read_limit(self) -> int:
        raise NotImplementedError("the original Product read limit is required")

    def _capture_attached_discovery(
        self,
        attached_session: _AttachedTranscriptReadPort,
        selected_session_file: Path,
        session_id: str,
    ) -> None:
        initial = self._read_current_discovery()
        if initial.aliases:
            raise self._discovery_error("session_discovery_conflict")
        try:
            status = selected_session_file.lstat()
        except OSError as exc:
            raise self._discovery_error("attached_transcript_changed") from exc
        self._attached_identity = (status.st_dev, status.st_ino)
        self._assert_attached_owner_matches_disk(initial)
        locator = initial.locator
        self._attached_source = (
            locator.source_id,
            initial.mode,
            initial.origin,
            initial.health,
            locator.session_file,
        )
        encoded = json.dumps(
            {
                "sourceId": locator.source_id,
                "sessionId": session_id,
                "sessionFile": str(locator.session_file),
                "device": status.st_dev,
                "inode": status.st_ino,
                "header": {
                    "version": attached_session.get_header().version,
                    "createdAt": attached_session.get_header().created_at,
                    "parentSessionId": (
                        attached_session.get_header().parent_conversation_id
                    ),
                    "metadata": dict(attached_session.get_header().metadata),
                },
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self._attached_revision = "attached-v1:" + sha256(encoded).hexdigest()

    def current_discovery(self) -> SessionDiscoveryMetadata:
        discovery = self._read_current_discovery()
        attached = self._attached_session
        if attached is None:
            return discovery
        locator = discovery.locator
        if (
            discovery.aliases
            or self._attached_source
            != (
                locator.source_id,
                discovery.mode,
                discovery.origin,
                discovery.health,
                locator.session_file,
            )
            or attached.get_session_file() != locator.session_file
        ):
            raise self._discovery_error("session_discovery_conflict")
        self._assert_attached_owner_matches_disk(discovery)
        assert self._attached_revision is not None
        return replace(
            discovery,
            locator=replace(locator, revision=self._attached_revision),
        )

    def _read_current_discovery(self) -> SessionDiscoveryMetadata:
        self._require_sources_current()
        try:
            summaries = self._directory.list_discovered_session_summaries(
                session_id_prefix=self._session_id
            )
            issues = self._directory.session_discovery_issues
        except (OSError, StoreDataError, ValueError) as exc:
            raise self._discovery_error("session_discovery_unavailable") from exc
        self._require_sources_current()
        if issues:
            raise self._discovery_error("session_discovery_incomplete")
        matches = tuple(
            summary for summary in summaries if summary.session_id == self._session_id
        )
        if len(matches) != 1 or not isinstance(
            matches[0].discovery, SessionDiscoveryMetadata
        ):
            raise self._discovery_error("session_discovery_missing")
        discovery = matches[0].discovery
        if (
            discovery.locator.conversation_id != self._session_id
            or (
                self._selected_session_file is not None
                and discovery.locator.session_file != self._selected_session_file
            )
            or not discovery.resumable
            or discovery.conflicts
        ):
            raise self._discovery_error("session_discovery_conflict")
        return discovery

    def _assert_attached_owner_matches_disk(
        self, discovery: SessionDiscoveryMetadata
    ) -> None:
        attached = self._attached_session
        selected_file = self._selected_session_file
        assert attached is not None and selected_file is not None
        try:
            before = selected_file.lstat()
            if (
                self._attached_identity is not None
                and (before.st_dev, before.st_ino) != self._attached_identity
            ):
                raise self._discovery_error("attached_transcript_changed")
            header, records = load_agent_transcript_file(
                selected_file,
                max_bytes=self._attached_read_limit(),
                read_only=True,
            )
            # The persistence codec normalizes some message fields on read.
            # Compare canonical records rather than their in-memory objects.
            if header != attached.get_header() or [
                self._record_codec.encode_record(record) for record in records
            ] != [
                self._record_codec.encode_record(record)
                for record in attached.get_entries()
            ]:
                raise self._discovery_error("attached_transcript_changed")
            after = selected_file.lstat()
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise self._discovery_error("attached_transcript_changed")
            if self._read_current_discovery() != discovery:
                raise self._discovery_error("attached_transcript_changed")
        except (
            OSError,
            StoreDataError,
            AgentTranscriptFileError,
            TypeError,
            ValueError,
        ) as exc:
            raise self._discovery_error("attached_transcript_changed") from exc

    def _require_sources_current(self) -> None:
        if (
            self._directory.authority_session_source != self._authority_source
            or self._directory.discovery_session_sources != self._discovery_sources
        ):
            raise self._discovery_error("session_discovery_sources_changed")
