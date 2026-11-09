"""Internal Worker Session reader over the real Transcript discovery owner.

The reader carries no activation authority. A Product receipt owner binds its
GC gate and Session identity, then rechecks this read for each policy witness.
"""

from __future__ import annotations

from pathlib import Path

from loushang.harness.conversation.jsonl_codec import ConversationJsonlRecordCodec
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.transcript._attached_discovery import _AttachedDiscoveryMethods
from loushang.harness.transcript.directory import AgentTranscriptDirectoryRuntime
from loushang.harness.transcript.profile import AgentTranscriptProfile

from .package_product_worker_policy import CodingWorkerPolicySelectionError
from .session_manager import SessionManager

_MAX_ATTACHED_TRANSCRIPT_BYTES = 64 * 1024 * 1024


class CodingWorkerTranscriptDiscoveryReader(_AttachedDiscoveryMethods):
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
        if (
            not isinstance(session_id, str)
            or not session_id
            or session_id.strip() != session_id
        ):
            raise ValueError("Worker Session identity is invalid")
        if selected_session_file is not None and (
            not isinstance(selected_session_file, Path)
            or not selected_session_file.is_absolute()
            or selected_session_file.parent
            != selected_session_file.parent.resolve(strict=True)
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
            self._capture_attached_discovery(
                attached_session, selected_session_file, session_id
            )

    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal:
        return self._gc_gate

    @property
    def session_id(self) -> str:
        return self._session_id

    def _discovery_error(self, suffix: str) -> CodingWorkerPolicySelectionError:
        return CodingWorkerPolicySelectionError(f"coding_worker_{suffix}")

    def _attached_read_limit(self) -> int:
        return _MAX_ATTACHED_TRANSCRIPT_BYTES


__all__ = ["CodingWorkerTranscriptDiscoveryReader"]
