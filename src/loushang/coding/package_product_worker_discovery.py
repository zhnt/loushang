"""Internal Worker Session reader over the real Transcript discovery owner.

The reader carries no activation authority. A Product receipt owner binds its
GC gate and Session identity, then rechecks this read for each policy witness.
"""

from __future__ import annotations

from pathlib import Path

from loushang.harness.conversation import StoreDataError
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.transcript.directory import AgentTranscriptDirectoryRuntime
from loushang.harness.transcript.discovery import SessionDiscoveryMetadata

from .package_product_worker_policy import CodingWorkerPolicySelectionError


class CodingWorkerTranscriptDiscoveryReader:
    """Rejoin one resumed Session to current bounded Transcript discovery."""

    def __init__(
        self,
        *,
        directory: AgentTranscriptDirectoryRuntime,
        gc_gate: PluginPackageGcReservationJournal,
        session_id: str,
        selected_session_file: Path | None = None,
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

    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal:
        return self._gc_gate

    @property
    def session_id(self) -> str:
        return self._session_id

    def current_discovery(self) -> SessionDiscoveryMetadata:
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

    def _require_sources_current(self) -> None:
        if (
            self._directory.authority_session_source != self._authority_source
            or self._directory.discovery_session_sources != self._discovery_sources
        ):
            raise CodingWorkerPolicySelectionError(
                "coding_worker_session_discovery_sources_changed"
            )


__all__ = ["CodingWorkerTranscriptDiscoveryReader"]
