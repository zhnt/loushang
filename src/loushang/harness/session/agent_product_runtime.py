"""Standard Agent lifecycle bindings for the Product session runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Generic, TypeVar, cast

from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticPhase
from loushang.harness.extensions.context import (
    SessionActionDecision,
    SessionBeforeForkEvent,
    SessionBeforeSwitchEvent,
    SessionShutdownEvent,
    SessionStartEvent,
)
from loushang.harness.runtime import copy_file_exclusive
from loushang.harness.session.composition import SessionExtensionCompositionPort
from loushang.harness.session.diagnostics import (
    SessionDiagnosticScope,
    SessionDiagnosticsRuntime,
)
from loushang.harness.session.lifecycle import (
    ForkProfile,
    ForkSelection,
    MissingSessionCwdError,
    SessionLifecycleDecision,
    SessionLifecycleHooks,
    SessionLifecycleTransition,
)
from loushang.harness.session.product_runtime import (
    ProductSessionRuntime,
    ProductSessionRuntimePorts,
    dispose_session_only,
    emit_session_shutdown,
    invoke_session_factory,
    resolve_agent_transcript_fork_target,
    resolve_existing_cwd,
    session_file_from_session,
    session_id_from_session,
)
from loushang.harness.session.transcript_lifecycle import (
    ProductTranscriptSessionBinding,
)
from loushang.harness.transcript import ProductTranscriptSession

SessionT = TypeVar("SessionT")
TranscriptT = TypeVar("TranscriptT", bound=ProductTranscriptSession)


def build_agent_session_lifecycle_hooks(
    *,
    runtime_host: object,
    record_shutdown_failure: Callable[[object, SessionShutdownEvent, Exception], None],
) -> SessionLifecycleHooks[object, str]:
    """Bind standard Agent-session effects to the shared lifecycle runtime."""

    async def before_transition(
        current: object | None,
        transition: SessionLifecycleTransition,
    ) -> SessionLifecycleDecision | None:
        if (
            current is None
            or transition.metadata.get("emit_before_transition", True) is False
        ):
            return None
        runner = _session_extension_runner(current)
        if runner is None:
            return None
        manager = getattr(current, "session_manager")
        decision: SessionActionDecision | None
        if transition.reason == "fork":
            entry_id = transition.fork_entry_id
            position = transition.fork_position
            if entry_id is None or position is None:
                raise ValueError("Fork transitions require entry_id and position")
            decision = await runner.before_session_fork(
                SessionBeforeForkEvent(
                    entry_id=entry_id,
                    cwd=manager.get_cwd(),
                    position=position,
                )
            )
        else:
            decision = await runner.before_session_switch(
                SessionBeforeSwitchEvent(
                    reason=transition.reason,
                    cwd=transition.cwd or manager.get_cwd(),
                    target_session_file=transition.target_session_ref,
                )
            )
        _sync_session_extension_diagnostics(current)
        return SessionLifecycleDecision(
            cancelled=decision is not None and decision.cancel
        )

    async def prepare_session(
        session: object,
        _previous: object | None,
        _transition: SessionLifecycleTransition,
    ) -> None:
        stage_approvals = getattr(session, "_stage_session_approvals", None)
        if callable(stage_approvals):
            stage_approvals()
        _bind_session_runtime_host(session, runtime_host)
        prepare_model_calls = getattr(session, "prepare_model_call_runtime", None)
        if callable(prepare_model_calls):
            await prepare_model_calls()

    async def activate_session(
        session: object,
        previous: object | None,
        transition: SessionLifecycleTransition,
    ) -> None:
        _open_session_approvals(session)
        if transition.metadata.get("activate_extensions", True) is False:
            return
        starter = getattr(session, "start_extension_runtime", None)
        if callable(starter):
            reason = (
                "startup"
                if previous is None and transition.reason == "new"
                else transition.reason
            )
            await starter(reason=reason)

    async def before_release(
        session: object,
        target_session: object | None,
        transition: SessionLifecycleTransition,
    ) -> None:
        event = SessionShutdownEvent(
            reason=transition.reason,
            target_session_file=session_file_from_session(target_session),
        )
        try:
            await emit_session_shutdown(session, event)
        except Exception as exc:
            record_shutdown_failure(session, event, exc)
        finally:
            _sync_session_extension_diagnostics(session)

    return SessionLifecycleHooks(
        before_transition=before_transition,
        prepare_session=prepare_session,
        activate_session=activate_session,
        before_release=before_release,
        dispose_session=dispose_session_only,
    )


def build_agent_product_session_runtime_ports(
    *,
    runtime_host: object,
    transcript_session_type: type[TranscriptT],
    session_dir: Path,
    session_factory: Callable[..., SessionT],
    persist: bool,
    diagnostics_runtime: Callable[[SessionT | None], SessionDiagnosticsRuntime] | None,
    record_shutdown_failure: Callable[[object, SessionShutdownEvent, Exception], None],
    copy_file: Callable[[Path, Path], None],
    before_release: Callable[
        [SessionT, SessionT | None, SessionLifecycleTransition],
        Awaitable[None] | None,
    ]
    | None = None,
    translate_missing_cwd_error: Callable[[MissingSessionCwdError], Exception]
    | None = None,
) -> ProductSessionRuntimePorts[SessionT, TranscriptT, str]:
    """Bind standard Agent session conventions to ``ProductSessionRuntime``."""

    transcript = ProductTranscriptSessionBinding(
        session_type=transcript_session_type,
        session_dir=session_dir,
        persist=persist,
        resolve_cwd_override=resolve_existing_cwd,
    )

    def build_session(
        manager: TranscriptT,
        current: SessionT | None,
        transition: SessionLifecycleTransition,
    ) -> SessionT:
        reason = (
            "startup"
            if current is None and transition.reason == "new"
            else transition.reason
        )
        return invoke_session_factory(
            session_factory,
            manager,
            session_start_event=SessionStartEvent(
                reason=reason,
                previous_session_file=session_file_from_session(current),
            ),
        )

    def fork_target(
        session: SessionT,
        entry_id: str,
        position: str,
    ) -> ForkSelection[str]:
        return resolve_agent_transcript_fork_target(
            getattr(session, "session_manager"),
            entry_id,
            position,
        )

    hooks = cast(
        SessionLifecycleHooks[SessionT, str],
        build_agent_session_lifecycle_hooks(
            runtime_host=runtime_host,
            record_shutdown_failure=record_shutdown_failure,
        ),
    )
    if before_release is not None:
        existing_before_release = hooks.before_release

        async def composed_before_release(
            session: SessionT,
            target_session: SessionT | None,
            transition: SessionLifecycleTransition,
        ) -> None:
            result = before_release(session, target_session, transition)
            if result is not None:
                await result
            if existing_before_release is not None:
                result = existing_before_release(
                    session,
                    target_session,
                    transition,
                )
                if result is not None:
                    await result

        hooks = replace(hooks, before_release=composed_before_release)

    return ProductSessionRuntimePorts(
        session_factory=session_factory,
        persist=persist,
        create_transcript=transcript.create,
        restore_transcript=transcript.restore,
        fork_transcript=transcript.fork,
        dispose_transcript=transcript.dispose,
        transcript_for_session=lambda session: cast(
            TranscriptT, getattr(session, "session_manager")
        ),
        transcript_cwd=lambda manager: getattr(manager, "get_cwd")(),
        transcript_session_ref=lambda manager: (
            str(value)
            if (value := getattr(manager, "get_session_file")()) is not None
            else None
        ),
        transcript_leaf_entry_id=lambda manager: getattr(manager, "get_leaf_id")(),
        build_session=build_session,
        validate_restored_transcript=transcript.validate_available_cwd,
        fork_profile=ForkProfile(
            default_position="before",
            supported_positions=frozenset({"at", "before"}),
        ),
        fork_target_resolver=fork_target,
        copy_file=copy_file,
        hooks=hooks,
        diagnostics_runtime=diagnostics_runtime,
        rename_transcript=transcript.rename,
        delete_transcript=transcript.delete,
        current_session_file=session_file_from_session,
        resolve_import_cwd=resolve_existing_cwd,
        translate_missing_cwd_error=translate_missing_cwd_error,
    )


class AgentProductSessionRuntime(
    ProductSessionRuntime[SessionT, TranscriptT, str],
    Generic[SessionT, TranscriptT],
):
    """Standard Agent conventions bound to the shared Product session runtime."""

    def __init__(
        self,
        *,
        transcript_session_type: type[TranscriptT],
        session_dir: Path,
        session_factory: Callable[..., SessionT],
        persist: bool = True,
        current_session: SessionT | None = None,
        diagnostics_service: DiagnosticsService | None = None,
        copy_file: Callable[[Path, Path], None] = copy_file_exclusive,
        before_release: Callable[
            [SessionT, SessionT | None, SessionLifecycleTransition],
            Awaitable[None] | None,
        ]
        | None = None,
        auto_refresh_session_index: bool = False,
        session_index_refresh_interval: float = 0.5,
        session_index_flush_delay: float = 0.25,
    ) -> None:
        self._agent_diagnostics_service = diagnostics_service
        super().__init__(
            session_dir=session_dir,
            ports=build_agent_product_session_runtime_ports(
                runtime_host=self,
                transcript_session_type=transcript_session_type,
                session_dir=session_dir,
                session_factory=session_factory,
                persist=persist,
                copy_file=copy_file,
                diagnostics_runtime=self._agent_session_diagnostics_runtime,
                record_shutdown_failure=self._record_agent_shutdown_failure,
                before_release=before_release,
            ),
            current_session=current_session,
            auto_refresh_session_index=auto_refresh_session_index,
            session_index_refresh_interval=session_index_refresh_interval,
            session_index_flush_delay=session_index_flush_delay,
        )
        if current_session is not None:
            prepare_current_agent_session(current_session, self)

    def _agent_session_diagnostics_runtime(
        self,
        session: SessionT | None = None,
    ) -> SessionDiagnosticsRuntime:
        active_session = session or self.current_session
        diagnostics_service = self._agent_diagnostics_service or getattr(
            active_session,
            "diagnostics_service",
            None,
        )
        session_id = session_id_from_session(active_session) or ""
        return SessionDiagnosticsRuntime(
            diagnostics_service=diagnostics_service,
            get_scope=lambda: SessionDiagnosticScope(session_id=session_id),
            get_extension_diagnostics=lambda: None,
        )

    def _record_agent_shutdown_failure(
        self,
        session: object,
        event: SessionShutdownEvent,
        exc: Exception,
    ) -> None:
        typed_session = cast(SessionT, session)
        self._record_failure_for_session(
            typed_session,
            code="session_shutdown_failed",
            exc=exc,
            details={
                "reason": event.reason,
                "session_file": session_file_from_session(typed_session),
                "target_session_file": event.target_session_file,
            },
        )


def prepare_current_agent_session(session: object, runtime_host: object) -> None:
    """Activate approval and runtime-host bindings for an injected session."""

    _open_session_approvals(session)
    _bind_session_runtime_host(session, runtime_host)


def _bind_session_runtime_host(session: object, runtime_host: object) -> None:
    setter = getattr(session, "set_extension_runtime_host", None)
    if callable(setter):
        setter(runtime_host)


def _open_session_approvals(session: object) -> None:
    callback = getattr(session, "_open_session_approvals", None)
    if callable(callback):
        callback()


def _session_extension_runner(
    session: object,
) -> SessionExtensionCompositionPort | None:
    return cast(
        SessionExtensionCompositionPort | None,
        getattr(
            session,
            "extension_runner",
            getattr(session, "_extension_runner", None),
        ),
    )


def _sync_session_extension_diagnostics(
    session: object,
    *,
    phase: DiagnosticPhase = "runtime",
) -> None:
    sync = getattr(session, "_sync_extension_diagnostics", None)
    if callable(sync):
        sync(phase=phase)
        return
    diagnostics_service = getattr(session, "diagnostics_service", None)
    runner = _session_extension_runner(session)
    get_diagnostics = (
        getattr(runner, "get_diagnostics", None) if runner is not None else None
    )
    if diagnostics_service is None or not callable(get_diagnostics):
        return
    diagnostics = get_diagnostics()
    recorded_attr = "_runtime_synced_extension_diagnostics_count"
    recorded = getattr(session, recorded_attr, 0)
    if not isinstance(recorded, int) or recorded < 0:
        recorded = 0
    if recorded >= len(diagnostics):
        return
    diagnostics_service.record_many(
        diagnostics_service.normalize_diagnostic(
            diagnostic,
            phase=phase,
            source="extensions",
            session_id=session_id_from_session(session),
        )
        for diagnostic in diagnostics[recorded:]
    )
    try:
        setattr(session, recorded_attr, len(diagnostics))
    except Exception:
        return


__all__ = [
    "AgentProductSessionRuntime",
    "build_agent_product_session_runtime_ports",
    "build_agent_session_lifecycle_hooks",
    "prepare_current_agent_session",
]
