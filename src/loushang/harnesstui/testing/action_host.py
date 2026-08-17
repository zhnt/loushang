from __future__ import annotations

from loushang.harnesstui.conversation.control import ConversationTextAction
from loushang.harnesstui.conversation.screen_runner import (
    AbortHandler,
    PromptHandler,
    TextHandler,
    maybe_await,
    supports_keyword,
)


class CallbackConversationActionHost:
    """Adapt playback callbacks to the canonical conversation action port."""

    def __init__(
        self,
        *,
        submit: PromptHandler | None = None,
        steer: TextHandler | None = None,
        follow_up: TextHandler | None = None,
        abort: AbortHandler | None = None,
    ) -> None:
        self._submit = submit
        self._steer = steer
        self._follow_up = follow_up
        self._abort = abort

    async def submit(self, action: ConversationTextAction) -> int | None:
        return await _call_text(self._submit, action)

    async def steer(self, action: ConversationTextAction) -> int | None:
        return await _call_text(self._steer, action)

    async def follow_up(self, action: ConversationTextAction) -> int | None:
        return await _call_text(self._follow_up, action)

    async def abort(self) -> None:
        if self._abort is not None:
            await maybe_await(self._abort())


async def _call_text(
    callback: TextHandler | None,
    action: ConversationTextAction,
) -> int | None:
    if callback is None:
        return None
    if action.attachments and supports_keyword(callback, "attachments"):
        result = await maybe_await(
            callback(action.text, attachments=action.attachments)
        )
    else:
        result = await maybe_await(callback(action.text))
    return result if isinstance(result, int) else None


__all__ = ["CallbackConversationActionHost"]
