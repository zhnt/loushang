"""Active-session facade for Products using the Agent transcript profile.

The transcript directory runtime owns discovery and index scheduling, while
``SessionLifecycleRuntime`` owns replacement transactions. This facade joins
those existing mechanisms into the standard Product-facing lifecycle surface
without selecting a store, transcript binding, Product hooks, or presentation.
"""

from __future__ import annotations

import errno
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from inspect import isawaitable
from pathlib import Path
from typing import Any, Generic, TypeVar

from loushang.harness.diagnostics.types import (
    DiagnosticRecord,
    DiagnosticsQuery,
    DiagnosticSummary,
    ErrorReport,
)
from loushang.harness.runtime import SessionOperationResult
from loushang.harness.session.diagnostics import SessionDiagnosticsRuntime
from loushang.harness.session.lifecycle import (
    MissingCwdPolicy,
    MissingSessionCwdError,
    PreparedSessionLifecycleOperation,
    SessionCwdIssue,
    SessionLifecycleRuntime,
    SessionLifecycleTransition,
)
from loushang.harness.transcript.directory import (
    AgentTranscriptDirectoryRuntime,
)
from loushang.harness.transcript.product_session import (
    ProductTranscriptSession,
)
from loushang.harness.transcript.session_catalog import SessionSummary

SessionT = TypeVar("SessionT")
PayloadT = TypeVar("PayloadT")
TranscriptSessionT = TypeVar("TranscriptSessionT")
ProductTranscriptSessionT = TypeVar(
    "ProductTranscriptSessionT",
    bound=ProductTranscriptSession[Any, Any],
)
ValueT = TypeVar("ValueT")

SessionCallback = Callable[[SessionT], Awaitable[None] | None]
LifecycleCallback = Callable[[], Awaitable[None] | None]
SessionDiagnosticsProvider = Callable[[SessionT | None], SessionDiagnosticsRuntime]
TranscriptSessionBuilder = Callable[
    [TranscriptSessionT, SessionT | None, SessionLifecycleTransition],
    SessionT | Awaitable[SessionT],
]
TranscriptSessionValidator = Callable[[TranscriptSessionT], None | Awaitable[None]]


@dataclass(frozen=True)
class ProductTranscriptSessionLifecyclePorts(Generic[TranscriptSessionT, SessionT]):
    """Product transcript storage operations used by the lifecycle store.

    The ports deliberately deal in a Product's transcript-session type rather
    than Agent or provider types. The generic store joins those transcript
    operations to ``SessionLifecycleRuntime`` and releases a transcript if the
    Product runtime session cannot be built.
    """

    create_transcript: Callable[
        [str, str | None], Awaitable[TranscriptSessionT] | TranscriptSessionT
    ]
    restore_transcript: Callable[
        [str | Path, str | None], Awaitable[TranscriptSessionT] | TranscriptSessionT
    ]
    fork_transcript: Callable[
        [TranscriptSessionT, str | None],
        Awaitable[TranscriptSessionT] | TranscriptSessionT,
    ]
    dispose_transcript: Callable[[TranscriptSessionT], Awaitable[None] | None]
    transcript_for_session: Callable[[SessionT], TranscriptSessionT]
    transcript_cwd: Callable[[TranscriptSessionT], str]
    transcript_session_ref: Callable[[TranscriptSessionT], str | None]
    transcript_leaf_entry_id: Callable[[TranscriptSessionT], str | None]


@dataclass(frozen=True)
class ProductTranscriptSessionBinding(Generic[ProductTranscriptSessionT]):
    """Bind the standard Product transcript session API to lifecycle ports."""

    session_type: type[ProductTranscriptSessionT]
    session_dir: Path
    persist: bool
    resolve_cwd_override: Callable[[str | Path], str]

    async def create(
        self,
        cwd: str,
        parent_session_ref: str | None,
    ) -> ProductTranscriptSessionT:
        return await self.session_type.new(
            session_dir=self.session_dir,
            cwd=cwd,
            persist=self.persist,
            parent_session=parent_session_ref,
        )

    async def restore(
        self,
        session_ref: str | Path,
        cwd_override: str | None,
    ) -> ProductTranscriptSessionT:
        return await self.session_type.open(
            session_ref,
            session_dir=self.session_dir,
            cwd_override=(
                self.resolve_cwd_override(cwd_override)
                if cwd_override is not None
                else None
            ),
            persist=self.persist,
        )

    async def fork(
        self,
        transcript: ProductTranscriptSessionT,
        target_entry_id: str | None,
    ) -> ProductTranscriptSessionT:
        if target_entry_id is not None:
            return await transcript.fork(target_entry_id)
        session_ref = transcript.get_session_file()
        return await self.create(
            transcript.get_cwd(),
            str(session_ref) if session_ref is not None else None,
        )

    @staticmethod
    async def dispose(transcript: ProductTranscriptSessionT) -> None:
        await transcript.dispose_runtime_profile()

    async def rename(
        self,
        path: Path,
        name: str | None,
    ) -> SessionSummary:
        return await self.session_type.rename_session(path, name)

    async def delete(
        self,
        path: Path,
        current_session_file: str | None,
    ) -> bool:
        return await self.session_type.delete_session(
            path,
            current_session_file=current_session_file,
        )

    @staticmethod
    def validate_available_cwd(transcript: ProductTranscriptSessionT) -> None:
        session_cwd = transcript.get_cwd()
        candidate = Path(session_cwd).expanduser()
        if candidate.exists() and candidate.is_dir():
            return
        session_file = transcript.get_session_file()
        raise MissingSessionCwdError(
            SessionCwdIssue(
                session_cwd=session_cwd,
                session_ref=str(session_file) if session_file is not None else None,
            )
        )


class ProductTranscriptSessionLifecycleStore(Generic[TranscriptSessionT, SessionT]):
    """Adapt Product transcript sessions to the common lifecycle store port.

    A Product supplies transcript persistence and runtime-session construction.
    This class owns the common create, restore, fork, association, and failed
    construction cleanup path without selecting a transcript format, store, or
    Product runtime.
    """

    def __init__(
        self,
        *,
        ports: ProductTranscriptSessionLifecyclePorts[TranscriptSessionT, SessionT],
        build_session: TranscriptSessionBuilder[TranscriptSessionT, SessionT],
        validate_restored_transcript: TranscriptSessionValidator[TranscriptSessionT]
        | None = None,
    ) -> None:
        self._ports = ports
        self._build_session = build_session
        self._validate_restored_transcript = validate_restored_transcript
        self._transcripts_by_session_id: dict[int, TranscriptSessionT] = {}

    async def create(
        self,
        current_session: SessionT | None,
        transition: SessionLifecycleTransition,
        *,
        cwd: str,
        parent_session_ref: str | None,
    ) -> SessionT:
        transcript = await _maybe_await(
            self._ports.create_transcript(cwd, parent_session_ref)
        )
        return await self._build_or_dispose(transcript, current_session, transition)

    async def restore(
        self,
        current_session: SessionT | None,
        transition: SessionLifecycleTransition,
        session_ref: str | Path,
        *,
        cwd_override: str | None = None,
    ) -> SessionT:
        transcript = await _maybe_await(
            self._ports.restore_transcript(session_ref, cwd_override)
        )
        try:
            if self._validate_restored_transcript is not None:
                await _maybe_await(self._validate_restored_transcript(transcript))
        except BaseException:
            await _maybe_await(self._ports.dispose_transcript(transcript))
            raise
        return await self._build_or_dispose(transcript, current_session, transition)

    async def fork(
        self,
        session: SessionT,
        transition: SessionLifecycleTransition,
        target_entry_id: str | None,
    ) -> SessionT:
        transcript = await _maybe_await(
            self._ports.fork_transcript(
                self._transcript_for_session(session), target_entry_id
            )
        )
        return await self._build_or_dispose(transcript, session, transition)

    def get_cwd(self, session: SessionT) -> str:
        return self._ports.transcript_cwd(self._transcript_for_session(session))

    def get_session_ref(self, session: SessionT) -> str | None:
        return self._ports.transcript_session_ref(self._transcript_for_session(session))

    def get_leaf_entry_id(self, session: SessionT) -> str | None:
        return self._ports.transcript_leaf_entry_id(
            self._transcript_for_session(session)
        )

    async def _build_or_dispose(
        self,
        transcript: TranscriptSessionT,
        current_session: SessionT | None,
        transition: SessionLifecycleTransition,
    ) -> SessionT:
        try:
            session = await _maybe_await(
                self._build_session(transcript, current_session, transition)
            )
        except BaseException:
            await _maybe_await(self._ports.dispose_transcript(transcript))
            raise
        self._transcripts_by_session_id[id(session)] = transcript
        return session

    def _transcript_for_session(self, session: SessionT) -> TranscriptSessionT:
        try:
            return self._transcripts_by_session_id[id(session)]
        except KeyError:
            return self._ports.transcript_for_session(session)


class AgentTranscriptSessionRuntime(
    AgentTranscriptDirectoryRuntime,
    Generic[SessionT, PayloadT],
):
    """Expose common active-session operations over one Agent transcript root.

    Products configure the lifecycle store, fork profile, lifecycle hooks, and
    metadata on the supplied ``SessionLifecycleRuntime``. This facade only
    delegates standard new, restore, fork, import, replacement, and disposal
    operations, together with Conversation JSONL session-reference resolution.
    """

    def __init__(
        self,
        *,
        session_dir: str | Path,
        lifecycle: SessionLifecycleRuntime[SessionT, PayloadT],
        auto_refresh_session_index: bool = False,
        session_index_refresh_interval: float = 0.5,
        session_index_flush_delay: float = 0.25,
        record_index_refresh_failure: Callable[[Exception, bool], None] | None = None,
        diagnostics_runtime: SessionDiagnosticsProvider[SessionT] | None = None,
    ) -> None:
        super().__init__(
            session_dir=session_dir,
            auto_refresh_session_index=auto_refresh_session_index,
            session_index_refresh_interval=session_index_refresh_interval,
            session_index_flush_delay=session_index_flush_delay,
            record_index_refresh_failure=record_index_refresh_failure,
        )
        self._lifecycle = lifecycle
        self._diagnostics_runtime = diagnostics_runtime

    @property
    def lifecycle(self) -> SessionLifecycleRuntime[SessionT, PayloadT]:
        """Return the Product-configured transaction runtime."""

        return self._lifecycle

    @property
    def current_session(self) -> SessionT | None:
        return self._lifecycle.current_session

    @property
    def session(self) -> SessionT:
        return self._lifecycle.session

    @property
    def cwd(self) -> str:
        return self._lifecycle.store.get_cwd(self.session)

    def set_rebind_session(self, callback: SessionCallback[SessionT] | None) -> None:
        self._lifecycle.set_rebind_session(callback)

    def set_before_session_invalidate(
        self,
        callback: LifecycleCallback | None,
    ) -> None:
        self._lifecycle.set_before_session_invalidate(callback)

    def subscribe_before_session_invalidate(
        self,
        callback: LifecycleCallback,
    ) -> Callable[[], None]:
        return self._lifecycle.subscribe_before_session_invalidate(callback)

    def subscribe_after_session_invalidate(
        self,
        callback: LifecycleCallback,
    ) -> Callable[[], None]:
        return self._lifecycle.subscribe_after_session_invalidate(callback)

    async def new_session_operation(
        self,
        *,
        cwd: str | None = None,
        parent_session_ref: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> SessionOperationResult[SessionT, PayloadT | None]:
        return await self._lifecycle.new(
            cwd=cwd,
            parent_session_ref=parent_session_ref,
            metadata=metadata,
        )

    async def restore_session_operation(
        self,
        session_ref: str | Path,
        *,
        fallback_cwd: str | None = None,
        missing_cwd: MissingCwdPolicy = "error",
        metadata: dict[str, object] | None = None,
    ) -> SessionOperationResult[SessionT, PayloadT | None]:
        return await self._lifecycle.restore(
            session_ref,
            fallback_cwd=fallback_cwd,
            missing_cwd=missing_cwd,
            metadata=metadata,
        )

    async def prepare_restore_session_operation(
        self,
        session_ref: str | Path,
        *,
        fallback_cwd: str | None = None,
        missing_cwd: MissingCwdPolicy = "error",
        metadata: dict[str, object] | None = None,
    ) -> PreparedSessionLifecycleOperation[SessionT, PayloadT]:
        return await self._lifecycle.prepare_restore(
            session_ref,
            fallback_cwd=fallback_cwd,
            missing_cwd=missing_cwd,
            metadata=metadata,
        )

    async def fork_session_operation(
        self,
        entry_id: str | None,
        *,
        position: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> SessionOperationResult[SessionT, PayloadT | None]:
        return await self._lifecycle.fork(
            entry_id,
            position=position,
            metadata=metadata,
        )

    async def import_session_operation(
        self,
        input_path: str | Path,
        *,
        cwd_override: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> SessionOperationResult[SessionT, PayloadT | None]:
        return await self._lifecycle.import_file(
            input_path,
            destination_dir=self.session_dir,
            cwd_override=cwd_override,
            metadata=metadata,
        )

    async def replace_current_session(
        self,
        session: SessionT,
        *,
        metadata: dict[str, object] | None = None,
    ) -> None:
        await self._lifecycle.replace(session, metadata=metadata)

    async def dispose_session_runtime(
        self,
        *,
        metadata: dict[str, object] | None = None,
    ) -> None:
        await self.drain_session_index_flush()
        await self._lifecycle.dispose(reason="quit", metadata=metadata)

    def get_current_session(self) -> SessionT | None:
        return self.current_session

    def get_current_session_ref(self) -> str | None:
        current = self.current_session
        if current is None:
            return None
        return self._lifecycle.store.get_session_ref(current)

    def _session_diagnostics(self) -> SessionDiagnosticsRuntime | None:
        if self._diagnostics_runtime is None:
            return None
        return self._diagnostics_runtime(self.current_session)

    def get_last_diagnostics(self, limit: int = 50) -> list[DiagnosticRecord]:
        runtime = self._session_diagnostics()
        return runtime.get_last_diagnostics(limit=limit) if runtime else []

    def get_diagnostics(
        self, query: DiagnosticsQuery | None = None
    ) -> list[DiagnosticRecord]:
        runtime = self._session_diagnostics()
        return runtime.get_diagnostics(query=query) if runtime else []

    def get_session_diagnostics(
        self, query: DiagnosticsQuery | None = None
    ) -> list[DiagnosticRecord]:
        runtime = self._session_diagnostics()
        return runtime.get_session_diagnostics(query=query) if runtime else []

    def get_diagnostics_summary(
        self, query: DiagnosticsQuery | None = None
    ) -> DiagnosticSummary:
        runtime = self._session_diagnostics()
        return (
            runtime.get_diagnostics_summary(query=query)
            if runtime
            else DiagnosticSummary(0, 0, 0, 0)
        )

    def get_session_diagnostics_summary(
        self, query: DiagnosticsQuery | None = None
    ) -> DiagnosticSummary:
        runtime = self._session_diagnostics()
        return (
            runtime.get_session_diagnostics_summary(query=query)
            if runtime
            else DiagnosticSummary(0, 0, 0, 0)
        )

    def get_last_error_report(self) -> ErrorReport | None:
        runtime = self._session_diagnostics()
        return runtime.get_last_error_report() if runtime else None

    def resolve_session_file(self, session_ref: str | Path) -> Path:
        """Resolve an exact path, filename, or unambiguous current-session id."""

        candidate = Path(session_ref).expanduser()
        if candidate.exists():
            return candidate.resolve()

        session_name = candidate.name
        matches = sorted(self.session_dir.glob(f"*_{session_name}.jsonl"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"Ambiguous session reference: {session_name}")
        prefix_matches = [
            summary
            for summary in self.list_session_summaries()
            if summary.session_file is not None
            and summary.session_id.startswith(session_name)
        ]
        if len(prefix_matches) == 1 and prefix_matches[0].session_file is not None:
            return prefix_matches[0].session_file
        if len(prefix_matches) > 1:
            raise ValueError(f"Ambiguous session reference: {session_name}")
        raise FileNotFoundError(
            errno.ENOENT,
            "No such file or directory",
            str(candidate),
        )


def require_session_operation_session(
    result: SessionOperationResult[SessionT, PayloadT],
) -> SessionT:
    """Return a completed operation's active session with a stable error."""

    if result.current is None:
        raise RuntimeError("Session operation completed without an active session")
    return result.current


async def _maybe_await(value: ValueT | Awaitable[ValueT]) -> ValueT:
    if isawaitable(value):
        return await value
    return value


__all__ = [
    "AgentTranscriptSessionRuntime",
    "ProductTranscriptSessionBinding",
    "ProductTranscriptSessionLifecyclePorts",
    "ProductTranscriptSessionLifecycleStore",
    "require_session_operation_session",
    "SessionDiagnosticsProvider",
]
