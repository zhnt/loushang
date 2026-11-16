"""The single pending business question owned by a real Hosted Coding Session."""

from __future__ import annotations

from secrets import token_hex
from typing import TYPE_CHECKING, Any

from loushang.agent.types import (
    AgentToolResult,
    BeforeToolCallContext,
    BeforeToolCallResult,
)
from loushang.ai.types import TextPart, ToolCall
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

if TYPE_CHECKING:
    from .session.agent_session import AgentSession

ASK_USER = "ask_user"
_STANDALONE = "Call ask_user by itself in an assistant message, with no other tool calls."


class HostedUserChoice:
    def __init__(self) -> None:
        self.pending: UserChoicePromptV1 | None = None

    def clear(self) -> None:
        self.pending = None

    def install(self, session: AgentSession) -> None:
        if session.get_tool_definition(ASK_USER) is not None:
            return
        session._register_extension_runtime_tool(self.definition())
        previous = session.agent.before_tool_call

        async def guard(context: BeforeToolCallContext, signal: object | None) -> BeforeToolCallResult | None:
            name = context.tool_call.name
            if name == ASK_USER and sum(
                isinstance(part, ToolCall) for part in context.assistant_message.content
            ) != 1:
                return BeforeToolCallResult(block=True, reason=_STANDALONE)
            result = await previous(context, signal) if previous is not None else None
            if result is not None and result.tool_name not in (None, name) and ASK_USER in (name, result.tool_name):
                return BeforeToolCallResult(block=True, reason=_STANDALONE)
            return result

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
        arguments = call.arguments
        options = tuple(UserChoiceOptionV1(**item) for item in arguments["options"])
        self.pending = UserChoicePromptV1(token_hex(16), arguments["question"], options)
        return AgentToolResult(
            content=[TextPart(type="text", text="Question presented. Continue when the user answers in the next turn.")],
            details=None,
            terminate=True,
        )
