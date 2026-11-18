"""Internal Worker Session reader over the real Transcript discovery owner.

The reader carries no activation authority. A Product receipt owner binds its
GC gate and Session identity, then rechecks this read for each policy witness.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.transcript._attached_discovery import _AttachedDiscoveryMethods
from loushang.harness.transcript.directory import AgentTranscriptDirectoryRuntime

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
        super().__init__(
            directory=directory,
            gc_gate=gc_gate,
            session_id=session_id,
            selected_session_file=selected_session_file,
            attached_session=attached_session,
            gc_gate_type=PluginPackageGcReservationJournal,
            attached_session_type=SessionManager,
        )

    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal:
        return cast(PluginPackageGcReservationJournal, self._gc_gate)

    @property
    def session_id(self) -> str:
        return self._session_id

    def _discovery_error(self, suffix: str) -> CodingWorkerPolicySelectionError:
        return CodingWorkerPolicySelectionError(f"coding_worker_{suffix}")

    def _attached_read_limit(self) -> int:
        return _MAX_ATTACHED_TRANSCRIPT_BYTES


__all__ = ["CodingWorkerTranscriptDiscoveryReader"]
