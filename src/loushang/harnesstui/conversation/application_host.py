"""Prepared application hosts for screen and plain conversations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol, TextIO

from loushang.harnesstui.conversation.control import ConversationActionHost
from loushang.harnesstui.conversation.host import (
    ConversationScreenRunProfile,
)
from loushang.harnesstui.conversation.input_policy import (
    ConversationInputCapabilities,
)
from loushang.harnesstui.conversation.plain_app import PlainConversationApp
from loushang.harnesstui.conversation.run_context import (
    InteractionContext,
    StableEmit,
    TraceFn,
    open_interaction_run_context,
    subscribe_events,
)
from loushang.harnesstui.conversation.screen_app import ScreenConversationApp
from loushang.harnesstui.conversation.screen_runner import (
    ConversationScreenPort,
    LocalCommandPredicate,
    ShouldExit,
    SurfaceIntentHandler,
    TextHandler,
)
from loushang.harnesstui.conversation.source import TranscriptSource
from loushang.tui import InputIntent
from loushang.tui.keybindings import KeybindingConfig, KeybindingManager
from loushang.tui.transcript import DisplayRecord

Cleanup = Callable[[], None]
CleanupBinder = Callable[[], Cleanup]


class PreparedScreenSurfacePort(Protocol):
    """Prepared surface callbacks consumed by the screen host."""

    async def handle_text(self, text: str) -> int | None: ...

    async def handle_surface_intent(self, intent: InputIntent[str]) -> int | None: ...

    def is_local_command(self, text: str) -> bool: ...

    def clear_approval_surfaces(self) -> None: ...


class ActionHostScreenRunner(Protocol):
    """Structural runner contract used to keep terminal mechanics injectable."""

    def __call__(
        self,
        *,
        app: ConversationScreenPort,
        stdin: TextIO,
        stdout: TextIO,
        action_host: ConversationActionHost,
        profile: ConversationScreenRunProfile,
        handle_local: TextHandler | None = None,
        handle_surface_intent: SurfaceIntentHandler | None = None,
        should_exit: ShouldExit,
        is_local_command: LocalCommandPredicate | None = None,
        keybindings: KeybindingManager | KeybindingConfig | None = None,
    ) -> Awaitable[int]: ...


@dataclass(frozen=True, slots=True)
class InstalledConversationHistory:
    """Neutral result of installing one prepared active history window."""

    record_count: int
    active_record_count: int
    evicted_record_count: int

    @property
    def trimmed(self) -> bool:
        return self.evicted_record_count > 0


def _no_cleanup() -> None:
    return None


def _bind_no_cleanup() -> Cleanup:
    return _no_cleanup


def _ignore_history(_history: InstalledConversationHistory) -> None:
    return None


def _ignore_exit_code(_exit_code: int) -> None:
    return None


@dataclass(frozen=True, slots=True)
class PreparedScreenConversationRun:
    """Product-prepared values and effects for one screen interaction.

    The host deliberately receives no Session, runtime, model, Agent event, or
    approval policy. Products prepare those concerns behind structural ports
    and callbacks before crossing this boundary.
    """

    app: ScreenConversationApp
    action_host: ConversationActionHost
    surface: PreparedScreenSurfacePort
    event_source: object
    event_listener_factory: Callable[[], object]
    interaction_context: InteractionContext
    profile: ConversationScreenRunProfile
    should_exit: ShouldExit
    trace: TraceFn
    keybindings: KeybindingManager | KeybindingConfig | None = None
    input_capabilities: ConversationInputCapabilities = field(
        default_factory=ConversationInputCapabilities
    )
    history_records: tuple[DisplayRecord, ...] = ()
    transcript_source_factory: Callable[[], TranscriptSource] | None = None
    completion_provider: object | None = None
    bind_presenter: CleanupBinder = _bind_no_cleanup
    bind_transition: CleanupBinder = _bind_no_cleanup
    on_history_installed: Callable[[InstalledConversationHistory], None] = (
        _ignore_history
    )
    on_start: Callable[[], None] = _no_cleanup
    on_clean_exit: Callable[[int], None] = _ignore_exit_code


async def run_prepared_screen_conversation(
    run: PreparedScreenConversationRun,
    *,
    stdin: TextIO,
    stdout: TextIO,
    screen_runner: ActionHostScreenRunner,
) -> int:
    """Install prepared state, run the screen, and unwind in exact reverse."""

    _install_screen_state(run)
    unbind_presenter = run.bind_presenter()
    unbind_transition = _no_cleanup
    try:
        unbind_transition = run.bind_transition()
        listener = run.event_listener_factory()
        with run.interaction_context:
            unsubscribe = _no_cleanup
            try:
                run.on_start()
                unsubscribe = subscribe_events(run.event_source, listener)
                exit_code = await screen_runner(
                    app=run.app,
                    stdin=stdin,
                    stdout=stdout,
                    action_host=run.action_host,
                    profile=run.profile,
                    handle_local=run.surface.handle_text,
                    handle_surface_intent=run.surface.handle_surface_intent,
                    should_exit=run.should_exit,
                    is_local_command=run.surface.is_local_command,
                    keybindings=run.keybindings,
                )
                run.on_clean_exit(exit_code)
                return exit_code
            finally:
                try:
                    run.trace("tui.end")
                finally:
                    unsubscribe()
    finally:
        try:
            unbind_transition()
        finally:
            try:
                run.surface.clear_approval_surfaces()
            finally:
                unbind_presenter()


def _install_screen_state(run: PreparedScreenConversationRun) -> None:
    run.app.state.input_capabilities = run.input_capabilities
    run.app.transcript_source_factory = run.transcript_source_factory
    if run.history_records:
        run.app.replace_transcript_window(run.history_records, reason="resume")
        run.app.trim_active_transcript_window()
        run.on_history_installed(
            InstalledConversationHistory(
                record_count=len(run.history_records),
                active_record_count=len(run.app.state.records),
                evicted_record_count=run.app.state.evicted_prefix_record_count,
            )
        )
    if run.completion_provider is not None:
        run.app.composer.set_completion_provider(run.completion_provider)


class PlainPromptRunner(Protocol):
    """Line-oriented prompt loop accepted by the prepared plain host."""

    def __call__(
        self,
        *,
        stdin: TextIO,
        stdout: TextIO,
        handle_prompt: Callable[[str], Awaitable[int | None]],
    ) -> Awaitable[int]: ...


@dataclass(frozen=True, slots=True)
class PreparedPlainConversationRun:
    """Opaque listener/context and prepared product callbacks for plain mode."""

    event_source: object
    event_listener: object
    interaction_context: InteractionContext
    build_app: Callable[[StableEmit], PlainConversationApp]
    render_header: Callable[[], None]
    trace: TraceFn
    on_start: Callable[[], None] = _no_cleanup


async def run_prepared_plain_conversation(
    run: PreparedPlainConversationRun,
    *,
    stdin: TextIO,
    stdout: TextIO,
    prompt_runner: PlainPromptRunner,
) -> int:
    """Run one prepared plain interaction through the shared run context."""

    run_context = open_interaction_run_context(
        event_source=run.event_source,
        listener=run.event_listener,
        interactive_listener_factory=lambda _emit: run.event_listener,
        exit_context=run.interaction_context,
        interactive=False,
        trace=run.trace,
        on_open=run.on_start,
    )
    try:
        app = run.build_app(run_context.emit)
        run.render_header()
        return await prompt_runner(
            stdin=stdin,
            stdout=stdout,
            handle_prompt=app.handle_prompt,
        )
    finally:
        run_context.close()


__all__ = [
    "ActionHostScreenRunner",
    "InstalledConversationHistory",
    "PlainPromptRunner",
    "PreparedPlainConversationRun",
    "PreparedScreenConversationRun",
    "PreparedScreenSurfacePort",
    "run_prepared_plain_conversation",
    "run_prepared_screen_conversation",
]
