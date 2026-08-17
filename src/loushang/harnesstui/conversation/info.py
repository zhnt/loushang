"""Product-neutral presentation of local conversation information."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from loushang.harnesstui.conversation.run_context import StableEmit
from loushang.tui import InfoPanel

InfoPanelPresenter = Callable[[InfoPanel], bool | Awaitable[bool]]
IntentT = TypeVar("IntentT")


@dataclass(frozen=True, slots=True)
class ConversationInfoPresenter:
    """Present local information inline or through an optional modal port."""

    emit: StableEmit
    render_status: Callable[[str], None]
    render_panel: Callable[[InfoPanel], None] | None = None
    present_panel: InfoPanelPresenter | None = None

    async def show(
        self,
        title: str,
        text: str,
        *,
        label: str,
        modal: bool = False,
    ) -> None:
        if modal and self.present_panel is not None:
            panel = InfoPanel.from_text(
                title=title,
                text=text,
                footer="Press Enter to continue.",
            )
            handled = self.present_panel(panel)
            if inspect.isawaitable(handled):
                handled = await handled
            if handled:
                return
        await self.emit(lambda: self._render(title, text), label=label)

    def _render(self, title: str, text: str) -> None:
        if self.render_panel is None:
            self.render_status(text)
            return
        self.render_panel(InfoPanel.from_text(title=title, text=text, footer=""))


@dataclass(frozen=True, slots=True)
class ConversationLocalActionResult:
    """Presentation-ready result of one Product-bound local action."""

    text: str | None = None
    exit_code: int | None = None


LocalActionHandler = Callable[
    [IntentT],
    Awaitable[ConversationLocalActionResult],
]


@dataclass(frozen=True, slots=True)
class ConversationLocalActionBinding(Generic[IntentT]):
    """Bind an intent type to a local action and optional information panel."""

    key: str
    intent_type: type[object]
    handle: LocalActionHandler[IntentT]
    title: str = ""
    label: str = ""
    modal: bool = False
    deferred: bool = False


class ConversationLocalActionRegistry(Generic[IntentT]):
    """Resolve and present declarative local Product actions."""

    def __init__(
        self,
        *,
        bindings: tuple[ConversationLocalActionBinding[IntentT], ...],
        presenter: ConversationInfoPresenter,
    ) -> None:
        self._bindings = bindings
        self._presenter = presenter
        self._by_key = {binding.key: binding for binding in bindings}
        if len(self._by_key) != len(bindings):
            raise ValueError("conversation local action keys must be unique")

    def immediate_action(self, intent: IntentT) -> str | None:
        return self._action(intent, deferred=False)

    def deferred_action(self, intent: IntentT) -> str | None:
        return self._action(intent, deferred=True)

    async def handle(
        self,
        _text_action: object,
        intent: IntentT,
        action: str | None,
    ) -> int | None:
        if action is None:
            return None
        binding = self._by_key.get(action)
        if binding is None or not isinstance(intent, binding.intent_type):
            return None
        result = await binding.handle(intent)
        if result.text is not None:
            await self._presenter.show(
                binding.title,
                result.text,
                label=binding.label,
                modal=binding.modal,
            )
        return result.exit_code

    def _action(self, intent: IntentT, *, deferred: bool) -> str | None:
        for binding in self._bindings:
            if binding.deferred is deferred and isinstance(intent, binding.intent_type):
                return binding.key
        return None


__all__ = [
    "ConversationInfoPresenter",
    "ConversationLocalActionBinding",
    "ConversationLocalActionRegistry",
    "ConversationLocalActionResult",
    "InfoPanelPresenter",
    "LocalActionHandler",
]
