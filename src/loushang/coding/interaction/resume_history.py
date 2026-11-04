"""Coding history presentation over native screen and Resume owner entries.

The preparer obtains current admission from its original owners. This adapter
owns terminal state only; it creates no Agent, Writer, permission or effect fact.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Literal, TextIO, cast

from loushang.coding.resume_activation_attempt import CodingResumeRecoveryRequired
from loushang.coding.resume_history import (
    CodingResumeHistoryPreview,
    CodingResumeRecentPage,
)
from loushang.coding.resume_input_lookup import CodingResumeInputLookupQueryV1
from loushang.coding.resume_model_outcome import (
    CodingResumeModelOutcomeObservationV1,
    observe_coding_resume_model_outcome,
)
from loushang.coding.runtime.agent_session_runtime import (
    AgentSessionRuntime,
    CodingRuntimePreparedResume,
)
from loushang.coding.ui.product_binding import (
    build_coding_ui_controller,
    build_screen_coding_action_host,
)
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.coding.ui.screen_input import CODING_SCREEN_RUN_PROFILE
from loushang.harness.host.types import HostActionResult
from loushang.harness.session.facade import SessionApprovalInteractionPort
from loushang.harness.session.model_selection import model_identity_data
from loushang.harnesstui.conversation.action_presentation import (
    ConversationActionResultPresenter,
    ConversationTracebackPolicy,
)
from loushang.harnesstui.conversation.agent_application import (
    AgentScreenApprovalSurface,
    bind_agent_screen_approval_presenter,
)
from loushang.harnesstui.conversation.agent_binding import (
    agent_session_history_records,
    build_agent_screen_conversation_projection,
    cooperative_agent_screen_event_listener,
)
from loushang.harnesstui.conversation.application_host import (
    PreparedScreenConversationRun,
    PreparedScreenSurfacePort,
)
from loushang.harnesstui.conversation.control import ConversationTextAction
from loushang.harnesstui.conversation.input_policy import ConversationInputCapabilities
from loushang.harnesstui.conversation.intents import (
    PromptIntent,
    QuitIntent,
    parse_conversation_intent,
)
from loushang.harnesstui.conversation.run_context import RebindableEventSource
from loushang.harnesstui.conversation.source import MaterializedTranscriptSource
from loushang.tui.transcript import DisplayRecord

PrepareHistoryInput = Callable[
    [ConversationTextAction, Callable[[CodingResumeInputLookupQueryV1], None]],
    Awaitable[CodingRuntimePreparedResume],
]


class _HistoryActions:
    def __init__(
        self, *, runtime: AgentSessionRuntime, target: Path,
        history: CodingResumeHistoryPreview | CodingResumeRecentPage,
        app: ScreenCodingTuiApp,
        prepare_input: PrepareHistoryInput | None, stderr: TextIO,
        events: RebindableEventSource,
    ) -> None:
        self._runtime = runtime
        self._target = target
        self._history = history
        self._app = app
        self._prepare_input = prepare_input
        self._events = events
        source_records = (
            history.selected_records
            if isinstance(history, CodingResumeHistoryPreview)
            else history.records
        )
        self._records = agent_session_history_records(source_records)
        self._prepared: CodingRuntimePreparedResume | None = None
        self._query: CodingResumeInputLookupQueryV1 | None = None
        self._recovery: CodingResumeModelOutcomeObservationV1 | None = None
        self._phase: Literal["history", "preparing", "active", "recovery_required", "closed"] = "history"
        self._task: asyncio.Task[object] | None = None
        self._presenter = ConversationActionResultPresenter(
            target=app, stderr=stderr, traceback_policy=ConversationTracebackPolicy(False),
        )
        self._live = build_screen_coding_action_host(
            presenter=app,
            controller=build_coding_ui_controller(
                session=None, runtime=runtime, plugin_workspace=app.state.cwd,
                on_bash_record=app.append_command_execution_record,
            ), stderr=stderr, verbose=False,
        )

    def _error(self, message: str) -> None:
        self._presenter.present(
            HostActionResult(error_message=message), failure_status=lambda value: value,
        )

    def _observe_input(self, query: CodingResumeInputLookupQueryV1) -> None:
        if type(query) is not CodingResumeInputLookupQueryV1 or self._query is not None:
            raise ValueError("Resume input identity observation differs from the first input")
        self._query = query  # Lookup data only, including uncertain commits.

    async def _observe_recovery(self) -> str:
        """Refresh exact persisted history through the original Root read entry.

        Observation grants no retry or execution. Missing input stays unknown;
        only the Transcript owner with a staged record can prove absence.
        """

        self._recovery = None
        if self._query is None:
            return "The submitted input needs recovery before another input."
        try:
            history = await self._runtime.preview_resume_history(self._target)
            prefix = self._history.selected_records
            if (
                history.header_preview.header != self._history.header_preview.header
                or history.selected_records[:len(prefix)] != prefix
            ):
                raise ValueError("Resume recovery history target changed")
            self._recovery = observe_coding_resume_model_outcome(history, self._query)
            if self._recovery.input_record_id is not None:
                self._records = agent_session_history_records(history.selected_records)
        except Exception:
            return "Unable to verify the saved input. Recovery is required before another input."
        observed = self._recovery
        if observed.status == "conflict":
            return "Saved input identity conflicts with history. Recovery is required before another input."
        if observed.input_record_id is None:
            return "Saved input state is unknown. Recovery is required before another input."
        if observed.status == "unknown":
            outcome = "First model result is unknown."
        else:
            outcome = "First model call recorded as " + observed.status.removeprefix("observed_") + "."
        return "Saved input found. " + outcome + " Recovery is required before another input."

    def materialize(self) -> tuple[DisplayRecord, ...]:
        prepared = self._prepared
        if prepared is not None and self._runtime.current_session is prepared.continuation.session:
            self._records = agent_session_history_records(
                prepared.continuation.session.session_manager.get_active_entries(),
            )
        return self._records

    async def submit(self, action: ConversationTextAction) -> int | None:
        intent = parse_conversation_intent(action.text)
        if isinstance(intent, QuitIntent):
            return 0
        if self._phase == "active":
            return await self._live.submit(action)
        if self._phase != "history":
            self._error("The submitted input needs recovery before another input.")
            return None
        if intent is None:
            return None
        if not isinstance(intent, PromptIntent):
            self._error("This command needs an active session.")
            return None
        if not isinstance(self._history, CodingResumeHistoryPreview):
            self._error(
                "Writable continuation is unavailable until the selected "
                "history can be fully verified."
            )
            return None
        if self._prepare_input is None:
            raise RuntimeError("Verified Resume history has no input preparer")
        self._phase = "preparing"
        self._task = asyncio.current_task()
        self._app.begin_run()
        try:
            def current_view() -> None:
                if self._phase != "preparing" or self._task is None or self._task.cancelling():
                    raise asyncio.CancelledError("Resume history view is no longer current")

            with self._runtime.resume_history_view_scope(
                self._target, self._history, require_current_view=current_view,
            ):
                prepared = await self._prepare_input(action, self._observe_input)
            self._prepared = prepared
            manager = prepared.continuation.session._coding_session_manager
            with manager._lifecycle_session.sync_operation_scope():
                attempt, _ = manager._require_committed_resume_input(
                    prepared.continuation.attempt_id, prepared.continuation.input_record_id,
                )
                if (
                    manager.session_file != self._target
                    or attempt.session_id != self._history.header_preview.header.conversation_id
                    or attempt.original_leaf_id != self._history.selected_leaf_id
                    or attempt.ancestry_digest != self._history.selected_ancestry_digest
                    or self._query != prepared.continuation.input_lookup_query
                ):
                    raise CodingResumeRecoveryRequired("input.history_view_changed")
                # The native input commit preceded event subscription. Install
                # persisted history instead of submitting or echoing it again.
                self._records = agent_session_history_records(manager.get_active_entries())
            await self._runtime._consume_resume_preparation(prepared)
            self._app.install_resumed_history(self._records)
            self._app.state.model_label = model_identity_data(prepared.continuation.session.agent.model).label
            self._events.rebind(prepared.continuation.session)
            if self._events.last_rebind_error is not None:
                raise RuntimeError("Unable to subscribe to the current session") from self._events.last_rebind_error
            await prepared.run_first_input()
            self._phase = "active" if prepared.continuation.session.execution_available else "recovery_required"
            if self._phase == "active":
                self._app.state.input_capabilities = ConversationInputCapabilities()
            else:
                message = await self._observe_recovery()
                await self._runtime.dispose_session_runtime()
                self._app.install_resumed_history(self._records)
                self._error(message)
        except BaseException as error:
            if self._phase != "closed":
                self._phase = "recovery_required"
            try:
                message = (
                    await self._observe_recovery() if self._phase != "closed"
                    else "The submitted input needs recovery before another input."
                )
            finally:
                try:
                    if self._prepared is not None:
                        if self._prepared.consumed:
                            # Failed presentation or cancelled recovery must
                            # release the Slot through its original owner.
                            await self._runtime.dispose_session_runtime()
                        else:
                            await self._prepared.abort()
                except BaseException as cleanup:
                    error.add_note(f"Native Resume cleanup retained: {cleanup!r}")
            self._app.install_resumed_history(self._records)
            self._error("Request cancelled." if isinstance(error, asyncio.CancelledError) else str(error))
            if self._phase != "closed":
                self._error(message)
            if isinstance(error, asyncio.CancelledError):
                raise
        finally:
            self._task = None
            self._app.complete_run()
        return None

    async def steer(self, action: ConversationTextAction) -> int | None:
        if self._phase == "active":
            return await self._live.steer(action)
        self._error("Wait for the first continuation input to finish.")
        return None

    async def follow_up(self, action: ConversationTextAction) -> int | None:
        if self._phase == "active":
            return await self._live.follow_up(action)
        self._error("Wait for the first continuation input to finish.")
        return None

    async def abort(self) -> None:
        if self._task is not None:
            self._task.cancel()
        elif self._phase == "active":
            await self._live.abort()

    def close(self) -> None:
        self._phase = "closed"
        if self._task is not None:
            self._task.cancel()


def build_coding_resume_history_screen(
    *, runtime: AgentSessionRuntime, session_ref: str | Path,
    history: CodingResumeHistoryPreview | CodingResumeRecentPage,
    app: ScreenCodingTuiApp,
    prepare_input: PrepareHistoryInput | None, surface: PreparedScreenSurfacePort,
    stderr: TextIO,
    approval_interaction: SessionApprovalInteractionPort | None = None,
) -> PreparedScreenConversationRun:
    """Prepare real history without an Agent or eager model preparation.

    The caller supplies its original current-admission/approval surface and
    Resume preparer. This entry itself issues no permission or replay grant.
    """

    if runtime.current_session is not None:
        raise ValueError("History screen requires an unselected native Root")
    target = runtime.resolve_discovered_session_source(session_ref).path
    events = RebindableEventSource(None)
    actions = _HistoryActions(
        runtime=runtime, target=target, history=history, app=app,
        prepare_input=prepare_input, stderr=stderr, events=events,
    )

    def bind() -> Callable[[], None]:
        approval_cleanup = bind_agent_screen_approval_presenter(
            approval_interaction,
            cast(AgentScreenApprovalSurface, surface),
            default_action="Approve resumed session",
        )

        def cleanup() -> None:
            try:
                approval_cleanup()
            finally:
                actions.close()

        return cleanup

    return PreparedScreenConversationRun(
        app=app, action_host=actions, surface=surface, event_source=events,
        event_listener_factory=lambda: cooperative_agent_screen_event_listener(
            build_agent_screen_conversation_projection(app)
        ),
        interaction_context=nullcontext(), profile=CODING_SCREEN_RUN_PROFILE,
        should_exit=lambda text: isinstance(parse_conversation_intent(text), QuitIntent),
        trace=lambda name, **data: None,
        input_capabilities=ConversationInputCapabilities(steer=False, follow_up=False),
        history_records=agent_session_history_records(
            history.selected_records
            if isinstance(history, CodingResumeHistoryPreview)
            else history.records
        ),
        transcript_source_factory=lambda: MaterializedTranscriptSource(
            materialize_records=actions.materialize, active_window_state=app.state,
        ), bind_presenter=bind,
    )
