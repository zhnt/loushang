from __future__ import annotations

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest

from loushang.agent.types import BeforeToolCallContext, BeforeToolCallResult
from loushang.ai.types import (
    AssistantMessage,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from loushang.coding.hosted_user_choice import (
    HostedUserChoice,
    pending_choice_from_transcript,
    recover_pending_choice,
)
from loushang.harness.conversation import ConversationRecord
from loushang.harness.transcript import AGENT_MESSAGE_KIND


def _call(**changes):
    return replace(ToolCall("toolCall", "ask-1", "ask_user", {
        "question": "Choose a plan",
        "options": [{"id": "a", "label": "Gradual"}, {"id": "b", "label": "Rewrite"}],
    }), **changes)


def _assistant(*calls, stop="toolUse"):
    return AssistantMessage(
        "assistant", list(calls), "anthropic-messages", "faux", "anthropic-messages",
        "faux-model", None, Usage(input=0, output=0, cache_read=0, cache_write=0,
                                  total_tokens=0, cost={}),
        stop, None, 0.0,
    )


def _result(**changes):
    return replace(ToolResultMessage("toolResult", "ask-1", "ask_user", [], False, 0.0, terminate=True), **changes)


def _branch(*messages):
    return tuple(ConversationRecord(
        f"r{i}", f"r{i - 1}" if i else None, AGENT_MESSAGE_KIND, 1,
        "2026-01-01T00:00:00Z", payload,
    ) for i, payload in enumerate(messages))


def test_legacy_question_id_uses_the_committed_session_and_call_identity():
    branch = _branch(_assistant(_call()), _result())
    original = recover_pending_choice(branch, "session-a")
    assert original == recover_pending_choice(branch, "session-a")
    assert original.question == "Choose a plan"
    assert original.question_id != recover_pending_choice(branch, "session-b").question_id

    # The next turn may reuse a provider call ID without reusing an old question.
    later = _branch(
        _assistant(_call()), _result(), UserMessage("user", "I choose A", 0.0),
        _assistant(_call()), _result(),
    )
    assert recover_pending_choice(later, "session-a").question_id != original.question_id


@pytest.mark.parametrize("case", [
    "missing-result", "error", "nonterminating", "mixed", "aborted", "wrong-result-id",
    "duplicate-result", "duplicate-call", "answered", "different-tool", "invalid-details", "invalid-options",
])
def test_only_unambiguous_completed_unanswered_choices_are_recovered(case, caplog):
    assistant = _assistant(_call())
    result = _result(details={"kind": "coding.user_choice/v1", "questionId": "persisted"})
    messages = {
        "missing-result": (assistant,),
        "error": (assistant, replace(result, is_error=True)),
        "nonterminating": (assistant, replace(result, terminate=False)),
        "mixed": (_assistant(_call(), _call(id="other", name="read")), result),
        "aborted": (replace(assistant, stop_reason="aborted"), result),
        "wrong-result-id": (assistant, replace(result, tool_call_id="other")),
        "duplicate-result": (assistant, result, result),
        "duplicate-call": (assistant, assistant, result),
        "answered": (assistant, result, UserMessage("user", "I choose B", 0.0)),
        "different-tool": (assistant, replace(result, tool_name="other")),
        "invalid-details": (assistant, replace(result, details={
            "kind": "coding.user_choice/v1", "questionId": "contains whitespace",
        })),
        "invalid-options": (_assistant(_call(arguments={"question": "one", "options": []})), result),
    }[case]
    assert pending_choice_from_transcript(_branch(*messages), "session-a") is None
    if case == "invalid-details":
        assert "invalid_choice_prompt" in caplog.text
        assert "contains whitespace" not in caplog.text


def test_active_install_recovers_pending_and_keeps_its_persisted_call_arguments():
    call = _call()
    assistant = _assistant(call)
    result = _result(details={"kind": "coding.user_choice/v1", "questionId": "persisted"})
    session = Mock()
    session.session_id = "session-a"
    session.session_manager.get_active_entries.return_value = _branch(assistant, result)
    session.get_tool_definition.return_value = None
    previous = AsyncMock(return_value=BeforeToolCallResult(arguments={
        **call.arguments, "question": "A different question",
    }))
    session.agent.before_tool_call = previous

    choice = HostedUserChoice()
    choice.install(session)
    assert choice.pending.question_id == "persisted"
    session.session_manager.get_active_entries.assert_called_once_with()
    context = BeforeToolCallContext(assistant, call, call.arguments, Mock())
    blocked = asyncio.run(session.agent.before_tool_call(context, None))
    assert blocked.block is True
    previous.assert_awaited_once_with(context, None)
