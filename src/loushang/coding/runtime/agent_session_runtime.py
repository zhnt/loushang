from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from loushang.coding.session import AgentSession
from loushang.coding.session_manager import (
    SessionManager,
    _bind_owned_session_manager,
    _create_owned_session_factory,
)
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.runtime import copy_file_exclusive
from loushang.harness.session import AgentProductSessionRuntime
from loushang.harness.session.multiagent import compose_multiagent_before_release

SessionFactory = Callable[..., AgentSession]
_copy_import_file = copy_file_exclusive


def _copy_session_import(
    source: Path,
    destination: Path,
    *,
    expected_source_fingerprint: str | None = None,
) -> None:
    if expected_source_fingerprint is None:
        _copy_import_file(source, destination)
    else:
        _copy_import_file(
            source,
            destination,
            expected_source_fingerprint=expected_source_fingerprint,
        )


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
        owned_transcripts: bool = False,
        store_state_root: Path | None = None,
        enroll_legacy_shared_store: bool = False,
    ) -> None:
        if type(owned_transcripts) is not bool or type(enroll_legacy_shared_store) is not bool:
            raise TypeError("invalid owned transcript activation")
        if owned_transcripts and current_session is not None:
            raise ValueError("owned runtime must construct its own initial Session")
        if store_state_root is not None and not owned_transcripts:
            raise ValueError("store admission requires owned transcripts")
        if enroll_legacy_shared_store and store_state_root is None:
            raise ValueError("legacy store enrollment requires store admission")
        self._owned_transcript_factory = (
            _create_owned_session_factory(
                store_state_root=store_state_root,
                enroll_legacy_shared_store=enroll_legacy_shared_store,
            ) if owned_transcripts else None
        )
        transcript_type = (
            _bind_owned_session_manager(self._owned_transcript_factory)
            if self._owned_transcript_factory is not None else SessionManager
        )
        super().__init__(
            transcript_session_type=transcript_type,
            session_dir=session_dir,
            session_factory=session_factory,
            persist=persist,
            current_session=current_session,
            diagnostics_service=diagnostics_service,
            copy_file=_copy_session_import,
            verified_copy_file=_copy_session_import,
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

        failure: BaseException | None = None
        factory = self._owned_transcript_factory
        if factory is not None:
            factory._on_loop()
            try:
                factory.fence()
            except BaseException as error:
                failure = error
        try:
            await super().dispose_session_runtime(metadata=metadata)
        except BaseException as error:
            if failure is None:
                failure = error
            else:
                failure.add_note(f"Session cleanup retained: {type(error).__name__}")
        if factory is not None:
            try:
                await factory.close()
            except BaseException as error:
                if failure is None:
                    failure = error
                else:
                    failure.add_note(f"transcript factory cleanup retained: {type(error).__name__}")
        try:
            await shutdown_coding_continuity(self)
        except BaseException as error:
            if failure is None:
                failure = error
            else:
                failure.add_note(f"continuity cleanup retained: {type(error).__name__}")
        if failure is not None:
            raise failure
