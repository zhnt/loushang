"""A hosted Session tool for one pending user choice and its committed evidence."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Sequence
from copy import deepcopy
from hashlib import sha256
from secrets import token_hex
from typing import TYPE_CHECKING, Any, ClassVar

from loushang.agent.types import (
    AgentToolResult,
    BeforeToolCallContext,
    BeforeToolCallResult,
)
from loushang.ai.types import (
    AssistantMessage,
    TextPart,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from loushang.appserver.protocol import UserChoiceOptionV1, UserChoicePromptV1
from loushang.appserver.protocol.model import (
    USER_CHOICE_DESCRIPTION_CHARS,
    USER_CHOICE_ID_CHARS,
    USER_CHOICE_LABEL_CHARS,
    USER_CHOICE_MAX_OPTIONS,
    USER_CHOICE_QUESTION_CHARS,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import DirectExecution, DirectToolContext
from loushang.harness.transcript import AgentTranscriptRecord

if TYPE_CHECKING:
    from loushang.harness.session.agent_product import AgentProductSession

ASK_USER = "ask_user"
_STANDALONE = "Call ask_user by itself in an assistant message, with no other tool calls."


class _UnverifiableChoice(ValueError):
    """A redacted diagnostic for ambiguous or invalid transcript evidence."""


def _choice_prompt(question_id: str, arguments: dict[str, Any]) -> UserChoicePromptV1:
    if set(arguments) != {"question", "options"}:
        raise ValueError("invalid business question fields")
    options = arguments["options"]
    if type(options) is not list or not 2 <= len(options) <= USER_CHOICE_MAX_OPTIONS:
        raise ValueError("invalid business question options")
    return UserChoicePromptV1(
        question_id,
        arguments["question"],
        tuple(UserChoiceOptionV1(**option) for option in options),
    )


def _latest_turn_messages(
    selected_records: Sequence[AgentTranscriptRecord],
) -> Iterator[AgentTranscriptRecord]:
    for record in reversed(selected_records):
        if isinstance(record.payload, UserMessage):
            return
        if isinstance(record.payload, AssistantMessage | ToolResultMessage):
            yield record


def _tool_calls(message: object) -> tuple[ToolCall, ...]:
    if not isinstance(message, AssistantMessage):
        return ()
    return tuple(part for part in message.content if isinstance(part, ToolCall))


def _owns_tool_call(message: object, call_id: str) -> bool:
    if isinstance(message, ToolResultMessage):
        return message.tool_call_id == call_id
    return any(call.id == call_id for call in _tool_calls(message))


def _preserve_choice_arguments(
    context: BeforeToolCallContext,
    result: BeforeToolCallResult | None,
    original: dict[str, Any] | None,
) -> BeforeToolCallResult | None:
    name = context.tool_call.name
    if result is not None and result.tool_name not in (None, name) and ASK_USER in (name, result.tool_name):
        return BeforeToolCallResult(block=True, reason=_STANDALONE)
    effective = result.arguments if result is not None and result.arguments is not None else context.args
    if original is not None and effective != original:
        # The committed Assistant call must describe the exact published question.
        return BeforeToolCallResult(block=True, reason="ask_user arguments cannot be rewritten.")
    return result


class HostedUserChoiceRuntime:
    """Run one Session's user choice using the Product's persisted result tag."""

    _result_kind: ClassVar[str]
    _logger: ClassVar[logging.Logger] = logging.getLogger(__name__)
    _evidence_error: ClassVar[type[ValueError]] = _UnverifiableChoice

    def __init__(self) -> None:
        self.pending: UserChoicePromptV1 | None = None

    @classmethod
    def _recovered_question_id(
        cls, details: object, session_id: str, record_id: str, call_id: str
    ) -> str:
        if details is None:
            # Historical results had no details. The committed record and Session
            # identify the question even when a provider reuses its call ID.
            identity = json.dumps((session_id, record_id, call_id), separators=(",", ":"))
            return "legacy-" + sha256(identity.encode("ascii")).hexdigest()
        if type(details) is not dict or set(details) != {"kind", "questionId"}:
            raise cls._evidence_error("invalid_result_details")
        if details["kind"] != cls._result_kind or type(details["questionId"]) is not str:
            raise cls._evidence_error("invalid_result_details")
        return details["questionId"]

    @classmethod
    def _completed_choice_result(cls, result: object) -> ToolResultMessage | None:
        if isinstance(result, AssistantMessage):
            if any(call.name == ASK_USER for call in _tool_calls(result)):
                raise cls._evidence_error("missing_choice_result")
            return None
        if not isinstance(result, ToolResultMessage) or result.tool_name != ASK_USER:
            return None
        if result.is_error is not False or result.terminate is not True:
            return None
        return result

    @classmethod
    def _matched_choice_call(
        cls, assistant: AgentTranscriptRecord | None, result: ToolResultMessage,
    ) -> tuple[str, ToolCall]:
        if assistant is None or not isinstance(assistant.payload, AssistantMessage):
            raise cls._evidence_error("missing_choice_call")
        calls = _tool_calls(assistant.payload)
        if (
            assistant.payload.stop_reason not in {"stop", "toolUse"}
            or len(calls) != 1
            or calls[0].name != ASK_USER
            or not result.tool_call_id
            or calls[0].id != result.tool_call_id
        ):
            raise cls._evidence_error("invalid_choice_call")
        return assistant.record_id, calls[0]

    @classmethod
    def recover_pending_choice(
        cls, selected_records: Sequence[AgentTranscriptRecord], session_id: str
    ) -> UserChoicePromptV1 | None:
        """Project the latest committed question in an already validated active branch.

        Inconsistent choice evidence raises a redacted diagnostic. Non-message
        records can follow the result, including model or Session metadata.
        """
        messages = _latest_turn_messages(selected_records)
        last = next(messages, None)
        if last is None:
            return None
        result = cls._completed_choice_result(last.payload)
        if result is None:
            return None

        record_id, call = cls._matched_choice_call(next(messages, None), result)
        if any(_owns_tool_call(record.payload, call.id) for record in messages):
            raise cls._evidence_error("ambiguous_choice_call")
        question_id = cls._recovered_question_id(result.details, session_id, record_id, call.id)
        try:
            return _choice_prompt(question_id, call.arguments)
        except (ValueError, TypeError):
            raise cls._evidence_error("invalid_choice_prompt") from None

    @classmethod
    def pending_choice_from_transcript(
        cls, selected_records: Sequence[AgentTranscriptRecord], session_id: str
    ) -> UserChoicePromptV1 | None:
        try:
            return cls.recover_pending_choice(selected_records, session_id)
        except cls._evidence_error as evidence:
            cls._logger.warning("Hosted user choice recovery skipped (%s)", evidence)
            return None

    def clear(self) -> None:
        self.pending = None

    def install(self, session: AgentProductSession) -> None:
        if session.get_tool_definition(ASK_USER) is not None:
            return
        self.pending = self.pending_choice_from_transcript(
            session.session_manager.get_active_entries(), session.session_id,
        )
        session._register_extension_runtime_tool(self.definition())
        previous = session.agent.before_tool_call

        async def guard(context: BeforeToolCallContext, signal: object | None) -> BeforeToolCallResult | None:
            name = context.tool_call.name
            if name == ASK_USER and len(_tool_calls(context.assistant_message)) != 1:
                return BeforeToolCallResult(block=True, reason=_STANDALONE)
            original = deepcopy(context.tool_call.arguments) if name == ASK_USER else None
            result = await previous(context, signal) if previous is not None else None
            return _preserve_choice_arguments(context, result, original)

        session.agent.before_tool_call = guard

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=ASK_USER,
            label="Ask the user to choose",
            description=(
                "Ask the user to choose a business direction before continuing. "
                f"{_STANDALONE} Ends this turn. The user can answer in the next turn. "
                "This tool does not grant permission to use other tools."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "minLength": 1, "maxLength": USER_CHOICE_QUESTION_CHARS},
                    "options": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": USER_CHOICE_MAX_OPTIONS,
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string", "maxLength": USER_CHOICE_ID_CHARS,
                                    "pattern": "^[A-Za-z0-9][A-Za-z0-9._~-]*$",
                                },
                                "label": {"type": "string", "minLength": 1, "maxLength": USER_CHOICE_LABEL_CHARS},
                                "description": {
                                    "type": "string", "minLength": 1, "maxLength": USER_CHOICE_DESCRIPTION_CHARS,
                                },
                            },
                            "required": ["id", "label"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["question", "options"],
                "additionalProperties": False,
            },
            execution=DirectExecution(self._ask),
            execution_mode="sequential",
        )

    async def _ask(self, call: ToolCall, context: DirectToolContext) -> AgentToolResult[Any]:
        del context
        if self.pending is not None:
            raise ValueError("Only one user choice can be pending in a Session.")
        prompt = _choice_prompt(token_hex(16), call.arguments)
        self.pending = prompt
        return AgentToolResult(
            content=[TextPart(type="text", text="Question presented. Continue when the user answers in the next turn.")],
            details={"kind": self._result_kind, "questionId": prompt.question_id},
            terminate=True,
        )
