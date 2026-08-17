from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from loushang.coding.session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.runtime import copy_file_exclusive
from loushang.harness.session import AgentProductSessionRuntime
from loushang.harness.session.multiagent import compose_multiagent_before_release

SessionFactory = Callable[..., AgentSession]
_copy_import_file = copy_file_exclusive


class AgentSessionRuntime(
    AgentProductSessionRuntime[AgentSession, SessionManager],
):
    """Coding type binding for the shared Agent Product runtime."""

    def __init__(
        self,
        *,
        session_dir: Path,
        session_factory: SessionFactory,
        persist: bool = True,
        current_session: AgentSession | None = None,
        diagnostics_service: DiagnosticsService | None = None,
        auto_refresh_session_index: bool = False,
        session_index_refresh_interval: float = 0.5,
        session_index_flush_delay: float = 0.25,
    ) -> None:
        super().__init__(
            transcript_session_type=SessionManager,
            session_dir=session_dir,
            session_factory=session_factory,
            persist=persist,
            current_session=current_session,
            diagnostics_service=diagnostics_service,
            copy_file=lambda source, destination: _copy_import_file(
                source,
                destination,
            ),
            before_release=compose_multiagent_before_release(
                resolve_runtime=lambda session: getattr(
                    session,
                    "multiagent_runtime",
                    None,
                )
            ),
            auto_refresh_session_index=auto_refresh_session_index,
            session_index_refresh_interval=session_index_refresh_interval,
            session_index_flush_delay=session_index_flush_delay,
        )

    async def dispose_session_runtime(
        self,
        *,
        metadata: dict[str, object] | None = None,
    ) -> None:
        from loushang.coding.continuity import shutdown_coding_continuity

        try:
            await super().dispose_session_runtime(metadata=metadata)
        finally:
            await shutdown_coding_continuity(self)
