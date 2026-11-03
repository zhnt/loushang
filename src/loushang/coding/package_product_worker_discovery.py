"""Internal Worker Session reader over the real Transcript discovery owner.

The reader carries no activation authority. A Product receipt owner binds its
GC gate and Session identity, then rechecks this read for each policy witness.
"""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from loushang.harness.conversation import StoreDataError
from loushang.harness.conversation.jsonl_codec import ConversationJsonlRecordCodec
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.transcript.directory import AgentTranscriptDirectoryRuntime
from loushang.harness.transcript.discovery import SessionDiscoveryMetadata
from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileError,
    load_agent_transcript_file,
)
from loushang.harness.transcript.profile import AgentTranscriptProfile

from .package_product_worker_policy import CodingWorkerPolicySelectionError
from .session_manager import SessionManager

_MAX_ATTACHED_TRANSCRIPT_BYTES = 64 * 1024 * 1024


class CodingWorkerTranscriptDiscoveryReader:
    """Rejoin one resumed Session to current bounded Transcript discovery."""

    def __init__(
        self,
        *,
        directory: AgentTranscriptDirectoryRuntime,
        gc_gate: PluginPackageGcReservationJournal,
        session_id: str,
        selected_session_file: Path | None = None,
        attached_session: SessionManager | None = None,
    ) -> None:
        if not isinstance(directory, AgentTranscriptDirectoryRuntime):
            raise TypeError("Worker Session requires a Transcript directory owner")
        if not isinstance(gc_gate, PluginPackageGcReservationJournal):
            raise TypeError("Worker Session requires the Product GC gate")
        if not isinstance(session_id, str) or not session_id or session_id.strip() != session_id:
            raise ValueError("Worker Session identity is invalid")
        if selected_session_file is not None and (
            not isinstance(selected_session_file, Path)
            or not selected_session_file.is_absolute()
            or selected_session_file.parent != selected_session_file.parent.resolve(strict=True)
        ):
            raise ValueError("Worker selected Transcript path is invalid")
        self._directory = directory
        self._gc_gate = gc_gate
        self._session_id = session_id
        self._selected_session_file = selected_session_file
        self._authority_source = directory.authority_session_source
        self._discovery_sources = directory.discovery_session_sources
        self._attached_session = attached_session
        self._attached_identity: tuple[int, int] | None = None
        self._attached_source: tuple[str, str, str, str, Path] | None = None
        self._attached_revision: str | None = None
        self._record_codec = ConversationJsonlRecordCodec(
            AgentTranscriptProfile.default().payload_codecs
        )
        if attached_session is not None:
            if (
                not isinstance(attached_session, SessionManager)
                or not attached_session.is_persisted()
                or attached_session.get_header().conversation_id != session_id
                or selected_session_file is None
                or attached_session.get_session_file() != selected_session_file
            ):
                raise ValueError("Worker attached Session owner changed")
            initial = self._read_current_discovery()
            if initial.aliases:
                raise CodingWorkerPolicySelectionError(
                    "coding_worker_session_discovery_conflict"
                )
            try:
                status = selected_session_file.lstat()
            except OSError as exc:
                raise CodingWorkerPolicySelectionError(
                    "coding_worker_attached_transcript_changed"
                ) from exc
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

    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal:
        return self._gc_gate

    @property
    def session_id(self) -> str:
        return self._session_id

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
            raise CodingWorkerPolicySelectionError(
                "coding_worker_session_discovery_conflict"
            )
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
            raise CodingWorkerPolicySelectionError(
                "coding_worker_session_discovery_unavailable"
            ) from exc
        self._require_sources_current()
        if issues:
            raise CodingWorkerPolicySelectionError(
                "coding_worker_session_discovery_incomplete"
            )
        matches = tuple(
            summary
            for summary in summaries
            if summary.session_id == self._session_id
        )
        if len(matches) != 1 or not isinstance(
            matches[0].discovery, SessionDiscoveryMetadata
        ):
            raise CodingWorkerPolicySelectionError("coding_worker_session_discovery_missing")
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
            raise CodingWorkerPolicySelectionError("coding_worker_session_discovery_conflict")
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
                raise CodingWorkerPolicySelectionError(
                    "coding_worker_attached_transcript_changed"
                )
            header, records = load_agent_transcript_file(
                selected_file,
                max_bytes=_MAX_ATTACHED_TRANSCRIPT_BYTES,
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
                raise CodingWorkerPolicySelectionError(
                    "coding_worker_attached_transcript_changed"
                )
            after = selected_file.lstat()
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise CodingWorkerPolicySelectionError(
                    "coding_worker_attached_transcript_changed"
                )
            if self._read_current_discovery() != discovery:
                raise CodingWorkerPolicySelectionError(
                    "coding_worker_attached_transcript_changed"
                )
        except (OSError, StoreDataError, AgentTranscriptFileError, TypeError, ValueError) as exc:
            raise CodingWorkerPolicySelectionError(
                "coding_worker_attached_transcript_changed"
            ) from exc

    def _require_sources_current(self) -> None:
        if (
            self._directory.authority_session_source != self._authority_source
            or self._directory.discovery_session_sources != self._discovery_sources
        ):
            raise CodingWorkerPolicySelectionError(
                "coding_worker_session_discovery_sources_changed"
            )


__all__ = ["CodingWorkerTranscriptDiscoveryReader"]
