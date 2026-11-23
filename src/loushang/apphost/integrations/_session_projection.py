"""Project hosted conversation state and events for AppService clients."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable, Mapping
from secrets import token_hex
from typing import Generic, Protocol, TypeVar, cast

from loushang.ai.types import AssistantMessage, ToolCall, UserMessage
from loushang.appserver.protocol import (
    SessionEventKindV1,
    TranscriptRecordKindV1,
    TranscriptRecordV1,
)
from loushang.harness.events import RuntimeEvent
from loushang.harness.events.runtime_projection import project_session_runtime_event

_TEXT_LIMIT = 16_384
_MAX_INTERACTIONS = 16
_MAX_TRANSCRIPT_ROWS = 128
EventT = TypeVar("EventT", covariant=True)


class _EventFactory(Protocol[EventT]):
    def __call__(
        self,
        kind: SessionEventKindV1,
        text: str | None = None,
        interaction_id: str | None = None,
        truncated: bool = False,
    ) -> EventT: ...


class _HostedConversationProjection(Generic[EventT]):
    def __init__(self, event_factory: _EventFactory[EventT]) -> None:
        self._event = event_factory
        self.revision = 0
        self._interrupted = False

    def project_event(
        self, event: RuntimeEvent[object], *, on_user_message: Callable[[], None],
    ) -> EventT | None:
        self.revision += 1
        payload = project_session_runtime_event(event)
        if payload is None:
            return None
        kind = payload.get("type")
        if kind == "session_info_changed":
            return self._event(SessionEventKindV1.STATUS)
        if kind == "agent_start":
            self._interrupted = False
            return self._event(SessionEventKindV1.TURN_STARTED)
        if kind == "agent_end":
            return self._event(
                SessionEventKindV1.TURN_INTERRUPTED
                if self._interrupted else SessionEventKindV1.TURN_COMPLETED
            )
        if kind == "message_end":
            message = payload.get("message")
            if isinstance(message, AssistantMessage) and message.stop_reason == "aborted":
                self._interrupted = True
            if isinstance(message, UserMessage):
                on_user_message()
            projected = _transcript_record(message)
            if projected is not None:
                record, _ = projected
                return self._event(
                    SessionEventKindV1.USER_MESSAGE if record.kind is TranscriptRecordKindV1.USER
                    else SessionEventKindV1.ASSISTANT_MESSAGE,
                    record.text,
                )
        if kind == "message_update":
            update = payload.get("assistant_message_event")
            if isinstance(update, Mapping) and update.get("type") == "text_delta":
                delta = update.get("delta")
                if isinstance(delta, str):
                    return self._event(
                        SessionEventKindV1.ASSISTANT_DELTA, _bounded(delta),
                        truncated=len(delta) > _TEXT_LIMIT,
                    )
        return _HostedApprovalPresentation._project_approval_event(payload, self._event)


def _hosted_transcript_window(
    newest_first: Iterable[object], *, flag_clipped_rows: bool = True,
) -> tuple[tuple[TranscriptRecordV1, ...], bool]:
    records: list[TranscriptRecordV1] = []
    remaining = _TEXT_LIMIT
    clipped = False
    for message in newest_first:
        projected = _transcript_record(message)
        if projected is None:
            continue
        record, row_clipped = projected
        if len(records) >= _MAX_TRANSCRIPT_ROWS or len(record.text) > remaining:
            records.append(TranscriptRecordV1(
                TranscriptRecordKindV1.STATUS,
                "Earlier messages omitted from this bounded snapshot; "
                "the canonical transcript is unchanged.",
            ))
            return tuple(reversed(records)), True
        records.append(record)
        remaining -= len(record.text)
        clipped |= row_clipped
    return tuple(reversed(records)), flag_clipped_rows and clipped


def _first_user_prompt(messages: Iterable[object]) -> str | None:
    for message in messages:
        if isinstance(message, UserMessage) and (text := _message_text(message).strip()):
            return text
    return None


def _hosted_session_title(name: str | None, messages: Iterable[object]) -> str:
    if name and name.strip():
        return _bounded(name.strip(), limit=256)
    prompt = _first_user_prompt(messages)
    if prompt is None:
        return "New Session"
    title = " ".join(prompt.split())
    if len(title) <= 48:
        return title
    prefix = title[:47].rstrip()
    word_boundary = prefix.rfind(" ")
    if word_boundary >= 30:
        prefix = prefix[:word_boundary]
    return f"{prefix}…"


def _transcript_record(message: object) -> tuple[TranscriptRecordV1, bool] | None:
    if not isinstance(message, UserMessage | AssistantMessage):
        return None
    text = _message_text(message)
    if (
        isinstance(message, AssistantMessage)
        and message.stop_reason not in {"error", "aborted"}
        and not text
        and any(isinstance(part, ToolCall) for part in message.content)
    ):
        return None
    kind = (
        TranscriptRecordKindV1.USER if isinstance(message, UserMessage)
        else TranscriptRecordKindV1.ASSISTANT
    )
    return TranscriptRecordV1(kind, _bounded(text)), len(text) > _TEXT_LIMIT


def _message_text(message: UserMessage | AssistantMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return "".join(
        getattr(part, "text", "")
        for part in message.content
        if getattr(part, "type", None) == "text"
    )


def _bounded(text: str, *, limit: int = _TEXT_LIMIT) -> str:
    marker = " … [truncated]"
    return text if len(text) <= limit else text[: limit - len(marker)] + marker


class _HostedApprovalPresentation:
    """Present broker requests without exposing their underlying action IDs."""

    _interactions: dict[str, str]
    _approval_action: str
    _approval_publish_rollback: bool

    @staticmethod
    def _project_approval_event(
        payload: Mapping[str, object], event_factory: _EventFactory[EventT],
    ) -> EventT | None:
        kind = payload.get("type")
        if payload.get("hosted_presentation") is True and kind in {
            "tool_approval_requested", "tool_approval_resolved",
        }:
            return event_factory(
                SessionEventKindV1.INTERACTION_REQUESTED if kind == "tool_approval_requested"
                else SessionEventKindV1.INTERACTION_DISMISSED,
                cast(str | None, payload.get("text")),
                cast(str, payload["interaction_id"]),
            )
        return None

    def _approval_dispatcher(self) -> Callable[[RuntimeEvent[object]], Awaitable[None]]:
        raise NotImplementedError

    async def _present_approval(self, request: dict[str, object]) -> None:
        action_id = request.get("action_id")
        if (
            not isinstance(action_id, str)
            or len(self._interactions) >= _MAX_INTERACTIONS
        ):
            raise RuntimeError("hosted_approval_unavailable")
        text = "\n".join(
            (
                str(request.get("action", self._approval_action)),
                str(request.get("risk", "")),
                json.dumps(
                    request.get("arguments", {}), ensure_ascii=False, sort_keys=True
                ),
            )
        )
        if len(text) > _TEXT_LIMIT:
            raise RuntimeError("hosted_approval_too_large")
        interaction_id = token_hex(16)
        self._interactions[interaction_id] = action_id
        rollback_on_failure = self._approval_publish_rollback
        try:
            await self._publish_approval_event(interaction_id, text=text)
        except BaseException:
            if rollback_on_failure:
                self._interactions.pop(interaction_id, None)
            raise

    async def _publish_approval_event(
        self, interaction_id: str, *, text: str | None = None,
    ) -> None:
        # Resolve the real dispatcher only after inserting the original alias.
        event: dict[str, object] = {
            "type": "tool_approval_resolved" if text is None else "tool_approval_requested",
            "hosted_presentation": True,
            "interaction_id": interaction_id,
        }
        if text is not None:
            event["text"] = text
        await self._approval_dispatcher()(cast(RuntimeEvent[object], event))

    async def _dismiss_approval(self, action_id: str) -> None:
        for interaction_id, pending in tuple(self._interactions.items()):
            if pending == action_id:
                self._interactions.pop(interaction_id, None)
                await self._publish_approval_event(interaction_id)
