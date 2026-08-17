"""Agent-backed implementation of transient one-shot side questions."""

from __future__ import annotations

import asyncio
import inspect
from typing import Protocol, cast

from loushang.agent import Agent, BeforeToolCallResult
from loushang.ai.types import AssistantMessage
from loushang.harness.runtime.side_question import (
    SideQuestionAnswer,
    SideQuestionUpdate,
)
from loushang.harness.transcript import AgentTranscriptContext, assistant_message_text

SIDE_QUESTION_BOUNDARY_PROMPT = """\
You are answering a one-shot side question that is separate from the main task.
Treat the inherited conversation as reference only. Do not continue its plans or
perform work on its behalf. Tool use is disabled, and you must not claim to have
changed state. Answer the side question directly and say when the inherited
context is insufficient."""


class AgentSideQuestionProvider:
    """Run an in-memory child Agent without a transcript or SessionManager."""

    def __init__(self, *, session: object, boundary_prompt: str) -> None:
        self._session = session
        self._boundary_prompt = boundary_prompt
        self._active_agent: Agent | None = None

    async def ask(
        self,
        question: str,
        *,
        on_update: SideQuestionUpdate | None = None,
    ) -> SideQuestionAnswer:
        if self._active_agent is not None:
            raise RuntimeError("A side question is already running.")
        parent = _require_agent(self._session)
        manager = _require_session_manager(self._session)
        context = manager.build_session_context()
        context_messages = list(getattr(context, "messages", ()))
        revision = _context_revision(manager)
        child = Agent(
            initial_state={
                # Keep the parent's cacheable request prefix byte-for-byte
                # compatible. The side-question boundary is appended as the
                # new user turn instead of changing the system prompt.
                "system_prompt": parent.system_prompt,
                "model": parent.model,
                "thinking_level": parent.thinking_level,
                "tools": parent.tools,
                "messages": context_messages,
            },
            convert_to_llm=parent.convert_to_llm,
            transform_context=parent.transform_context,
            stream_fn=parent.stream_fn,
            call_options=parent.call_options,
            prepare_model_call=parent.prepare_model_call,
            before_tool_call=_block_side_question_tool_call,
            steering_mode=parent.steering_mode,
            follow_up_mode=parent.follow_up_mode,
            session_id=parent.session_id,
            thinking_budgets=parent.thinking_budgets,
            max_retry_delay_ms=parent.max_retry_delay_ms,
            tool_execution=parent.tool_execution,
        )
        self._active_agent = child
        unsubscribe = child.subscribe(
            lambda event, _signal: _publish_side_question_update(event, on_update)
        )
        try:
            await child.prompt(
                _side_question_prompt(self._boundary_prompt, question),
                model_call_purpose="side_question",
            )
            message = _last_assistant_message(child)
            if message.stop_reason in {"aborted", "error"}:
                raise RuntimeError(
                    message.error_message
                    or f"Side question request {message.stop_reason}."
                )
            text = assistant_message_text(message)
            if text is None:
                raise RuntimeError("Side question returned no text.")
            return SideQuestionAnswer(
                text=text,
                context_revision=revision,
                usage=message.usage,
            )
        except asyncio.CancelledError:
            child.abort()
            raise
        finally:
            unsubscribe()
            if self._active_agent is child:
                self._active_agent = None

    def cancel(self) -> None:
        child = self._active_agent
        if child is not None:
            child.abort()


def _require_agent(session: object) -> Agent:
    agent = getattr(session, "agent", None)
    if not isinstance(agent, Agent):
        raise TypeError("Side questions require an Agent-backed Product session.")
    return agent


class _SessionContextProvider(Protocol):
    def build_session_context(self) -> AgentTranscriptContext: ...

    def get_leaf_id(self) -> str | None: ...


def _require_session_manager(session: object) -> _SessionContextProvider:
    manager = getattr(session, "session_manager", None)
    if manager is None or not callable(getattr(manager, "build_session_context", None)):
        raise TypeError("Side questions require a session context provider.")
    return cast(_SessionContextProvider, manager)


def _context_revision(manager: object) -> str | None:
    get_leaf_id = getattr(manager, "get_leaf_id", None)
    if not callable(get_leaf_id):
        return None
    revision = get_leaf_id()
    return revision if isinstance(revision, str) and revision else None


def _side_question_prompt(boundary_prompt: str, question: str) -> str:
    return f"{boundary_prompt.strip()}\n\nQuestion:\n{question.strip()}"


async def _block_side_question_tool_call(
    _context: object,
    _signal: object | None,
) -> BeforeToolCallResult:
    return BeforeToolCallResult(
        block=True,
        reason="Side questions cannot use tools.",
    )


async def _publish_side_question_update(
    event: object,
    on_update: SideQuestionUpdate | None,
) -> None:
    if on_update is None or not isinstance(event, dict):
        return
    if event.get("type") != "message_update":
        return
    message = event.get("message")
    if not isinstance(message, AssistantMessage):
        return
    text = assistant_message_text(message)
    if not text:
        return
    result = on_update(text)
    if inspect.isawaitable(result):
        await result


def _last_assistant_message(agent: Agent) -> AssistantMessage:
    for message in reversed(agent.state.messages):
        if isinstance(message, AssistantMessage):
            return message
    raise RuntimeError("Side question returned no assistant message.")


__all__ = [
    "AgentSideQuestionProvider",
    "SIDE_QUESTION_BOUNDARY_PROMPT",
]
