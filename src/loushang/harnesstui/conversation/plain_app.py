"""Product-neutral composition for a plain conversation application."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TextIO, TypeVar

from loushang.harnesstui.conversation.action_presentation import (
    ConversationTracebackPolicy,
)
from loushang.harnesstui.conversation.control import (
    AbortActionHandler,
    ActionResult,
    ConversationActionHost,
    ConversationRunControl,
    ConversationTextAction,
    FollowUpActionHandler,
    InterruptionRenderer,
    SteerActionHandler,
)
from loushang.harnesstui.conversation.dispatch import (
    ConversationDispatchHandler,
    ConversationDispatchOutcome,
    ConversationResultPresenter,
    DispatchResult,
    ResultRenderer,
)
from loushang.harnesstui.conversation.host import (
    ConversationHostPorts,
    ConversationHostProfile,
    RoutedConversationActionHost,
)
from loushang.harnesstui.conversation.info import (
    ConversationInfoPresenter,
    InfoPanelPresenter,
)
from loushang.harnesstui.conversation.run_context import StableEmit, TraceFn
from loushang.harnesstui.status.persistence import (
    statusline_settings_from_store,
    statusline_settings_persistence_callback,
)
from loushang.harnesstui.status.provider import StatusProvider
from loushang.tui import CompletionProvider, InfoPanel

IntentT = TypeVar("IntentT")
IntentT_contra = TypeVar("IntentT_contra", contravariant=True)
LocalT = TypeVar("LocalT")
PendingT = TypeVar("PendingT")


class PlainConversationController(Protocol[IntentT_contra]):
    async def dispatch(self, intent: IntentT_contra) -> DispatchResult: ...

    async def steer(self, text: str) -> ActionResult: ...

    async def follow_up(self, text: str) -> ActionResult: ...


class PlainConversationRenderer(
    InterruptionRenderer,
    ResultRenderer,
    Protocol,
):
    pass


@dataclass(frozen=True, slots=True)
class PlainConversationProfile:
    """Prepared neutral facts and product-owned copy for one plain app."""

    abort_settling_message: str
    idle_follow_up_message: str
    queued_follow_up_message: str
    statusline_settings_store: object | None = None
    traceback_enabled: bool = False
    now: Callable[[], float] = time.monotonic


@dataclass(frozen=True, slots=True)
class PlainConversationAssembly:
    """Shared components exposed once for a product-specific binding."""

    lifecycle: ConversationRunControl
    settings_text: Callable[[], str]
    info: ConversationInfoPresenter


@dataclass(frozen=True, slots=True)
class PlainConversationProductBinding(Generic[IntentT, LocalT]):
    """Product behavior bound to shared components for one plain app."""

    host_profile: ConversationHostProfile[IntentT, LocalT]
    controller: PlainConversationController[IntentT]
    abort_action: Callable[[], Awaitable[Any]]
    is_work_intent: Callable[[IntentT], bool]
    local: Callable[
        [ConversationTextAction, IntentT, LocalT | None],
        Awaitable[int | None],
    ]
    fallback_error_message: Callable[[], str | None]
    suppress_aborted_error: Callable[[str | None], bool]


@dataclass(frozen=True, slots=True)
class PlainConversationPorts(Generic[IntentT, LocalT, PendingT]):
    """Product policy and effects composed by the shared plain app builder."""

    bind_product: Callable[
        [PlainConversationAssembly],
        PlainConversationProductBinding[IntentT, LocalT],
    ]
    renderer: PlainConversationRenderer
    emit: StableEmit
    trace: TraceFn
    stderr: TextIO
    session_running: Callable[[], bool]
    last_error_message: Callable[[], str | None]
    restore_queue: Callable[[str], Awaitable[str | None]]
    pending_messages: Callable[[], PendingT]
    render_info_panel: Callable[[InfoPanel], None] | None = None
    present_info_panel: InfoPanelPresenter | None = None
    completion_provider: CompletionProvider | None = None


@dataclass(frozen=True)
class PlainConversationApp:
    lifecycle: ConversationRunControl
    action_host: ConversationActionHost
    completion_provider: CompletionProvider | None = None

    async def handle_prompt(self, text: str) -> int | None:
        return await self.action_host.submit(
            ConversationTextAction(text=text, source="plain_prompt")
        )


def build_plain_conversation_app(
    *,
    profile: PlainConversationProfile,
    ports: PlainConversationPorts[IntentT, LocalT, PendingT],
) -> PlainConversationApp:
    """Compose neutral lifecycle, status, information, and action handling."""

    lifecycle = ConversationRunControl()
    status_provider = StatusProvider(
        model_label=None,
        cwd="",
        branch=None,
        session_label=lambda: None,
        thinking_level=lambda: None,
        running=ports.session_running,
        statusline_settings=statusline_settings_from_store(
            profile.statusline_settings_store
        ),
        on_statusline_settings_changed=statusline_settings_persistence_callback(
            profile.statusline_settings_store
        ),
    )
    info = ConversationInfoPresenter(
        emit=ports.emit,
        render_status=ports.renderer.render_status,
        render_panel=ports.render_info_panel,
        present_panel=ports.present_info_panel,
    )
    product = ports.bind_product(
        PlainConversationAssembly(
            lifecycle=lifecycle,
            settings_text=status_provider.settings_summary_text,
            info=info,
        )
    )

    async def abort_settling(
        _action: ConversationTextAction,
        _intent: IntentT,
    ) -> None:
        await ports.emit(
            lambda: ports.renderer.render_status(profile.abort_settling_message),
            label="abort:pending_input",
        )

    follow_up = FollowUpActionHandler(
        lifecycle=lifecycle,
        controller=product.controller,
        renderer=ports.renderer,
        emit=ports.emit,
        trace=ports.trace,
        idle_status_message=profile.idle_follow_up_message,
        queued_status_message=profile.queued_follow_up_message,
    )
    steer = SteerActionHandler(
        lifecycle=lifecycle,
        controller=product.controller,
        renderer=ports.renderer,
        emit=ports.emit,
        trace=ports.trace,
    )
    abort = AbortActionHandler(
        run_control=lifecycle,
        abort_action=product.abort_action,
        renderer=ports.renderer,
        emit=ports.emit,
        session_running=ports.session_running,
        trace=ports.trace,
    )
    dispatch = ConversationDispatchHandler[IntentT](
        lifecycle=lifecycle,
        controller=product.controller,
        is_work_intent=product.is_work_intent,
        session_running=ports.session_running,
        now=profile.now,
        trace=ports.trace,
    )
    presenter = ConversationResultPresenter(
        renderer=ports.renderer,
        emit=ports.emit,
        stderr=ports.stderr,
        traceback_policy=ConversationTracebackPolicy(enabled=profile.traceback_enabled),
        last_error_message=ports.last_error_message,
        now=profile.now,
        trace=ports.trace,
    )

    async def present_result(
        outcome: ConversationDispatchOutcome,
        _action: ConversationTextAction,
        _intent: IntentT,
        prompt_started: float,
    ) -> int | None:
        error_message = outcome.result.error_message or product.fallback_error_message()
        if (
            outcome.run_id is not None
            and lifecycle.aborted_id == outcome.run_id
            and product.suppress_aborted_error(error_message)
        ):
            lifecycle.clear_aborted(outcome.run_id)
            ports.trace(
                "prompt.suppressed_cancelled",
                run_id=outcome.run_id,
                error_message=error_message,
            )
            return outcome.result.exit_code
        return await presenter.handle(
            outcome,
            prompt_started=prompt_started,
            error_message=error_message,
        )

    host = RoutedConversationActionHost(
        profile=product.host_profile,
        ports=ConversationHostPorts[
            IntentT,
            ConversationDispatchOutcome,
            LocalT,
            PendingT,
        ](
            abort_settling=abort_settling,
            follow_up=lambda action: follow_up.queue(
                action.text,
                source=action.source,
            ),
            steer=lambda action: steer.steer(action.text),
            local=product.local,
            dispatch=lambda _action, intent: dispatch.dispatch(intent),
            result=present_result,
            abort=abort.abort,
            restore_queue=ports.restore_queue,
            pending_messages=ports.pending_messages,
        ),
    )
    return PlainConversationApp(
        lifecycle=lifecycle,
        action_host=host,
        completion_provider=ports.completion_provider,
    )


__all__ = [
    "PlainConversationApp",
    "PlainConversationAssembly",
    "PlainConversationController",
    "PlainConversationPorts",
    "PlainConversationProductBinding",
    "PlainConversationProfile",
    "PlainConversationRenderer",
    "build_plain_conversation_app",
]
