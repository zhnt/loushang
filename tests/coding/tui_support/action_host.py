from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TextIO

from loushang.coding.ui.product_binding import (
    build_screen_coding_action_host,
)
from loushang.harnesstui.conversation.action_presentation import (
    ConversationActionPresentationPort,
)
from loushang.harnesstui.conversation.control import ConversationTextAction
from loushang.harnesstui.conversation.controller import ConversationUiController


def coding_screen_prompt_handler(
    *,
    presenter: ConversationActionPresentationPort,
    controller: ConversationUiController,
    stderr: TextIO,
    verbose: bool,
) -> Callable[[str], Awaitable[int | None]]:
    """Bind the production Coding action host to a playback prompt callback."""

    host = build_screen_coding_action_host(
        presenter=presenter,
        controller=controller,
        stderr=stderr,
        verbose=verbose,
    )

    async def handle(text: str) -> int | None:
        return await host.submit(ConversationTextAction(text=text, source="prompt"))

    return handle


__all__ = ["coding_screen_prompt_handler"]
