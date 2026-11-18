import copy
import pickle
from dataclasses import fields, is_dataclass, replace
from typing import get_args

import pytest

from loushang.agent import (
    AfterToolCallContext,
    AfterToolCallResult,
    Agent,
    AgentContext,
    AgentEvent,
    AgentLoopConfig,
    AgentMessage,
    AgentOptions,
    AgentState,
    AgentToolResult,
    BeforeToolCallContext,
    BeforeToolCallResult,
    ProxyAssistantMessageEvent,
    ProxyStreamOptions,
    ThinkingLevel,
    ToolExecutionMode,
    ToolOutputPreviewPolicy,
    ToolOutputProjectionError,
    ToolOutputProjector,
    agent_loop,
    agent_loop_continue,
    stream_proxy,
)
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import UserMessage


class _HostileTruthValue:
    def __bool__(self) -> bool:
        raise AssertionError("boolean truthiness must not be evaluated")


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=False,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def test_public_types_are_exported() -> None:
    assert isinstance(
        AgentState(system_prompt="", model=_model(), thinking_level="off"), AgentState
    )
    assert is_dataclass(AgentContext)
    assert is_dataclass(AgentLoopConfig)
    assert is_dataclass(AgentOptions)
    assert is_dataclass(AgentToolResult)
    assert is_dataclass(ProxyStreamOptions)
    assert BeforeToolCallResult.__annotations__["block"] == "bool | None"
    assert AfterToolCallResult.__annotations__["is_error"] == "bool | None"
    assert AfterToolCallResult.__annotations__["terminate"] == "bool | None"
    assert AgentToolResult(content=[], details={}).terminate is False
    assert ToolOutputProjector is not None
    assert ToolOutputProjectionError is not None
    assert ToolOutputPreviewPolicy().max_bytes == 2048


def test_after_tool_call_result_distinguishes_omitted_and_null_details() -> None:
    omitted = AfterToolCallResult()
    explicit_null = AfterToolCallResult(details=None)

    assert omitted.details is None
    assert omitted.details_provided is False
    assert explicit_null.details_provided is True
    assert explicit_null.details is None

    for cloned_omitted, cloned_null in (
        (copy.deepcopy(omitted), copy.deepcopy(explicit_null)),
        (
            pickle.loads(pickle.dumps(omitted)),
            pickle.loads(pickle.dumps(explicit_null)),
        ),
        (replace(omitted, terminate=True), replace(explicit_null, terminate=True)),
    ):
        assert cloned_omitted.details is None
        assert cloned_omitted.details_provided is False
        assert cloned_null.details is None
        assert cloned_null.details_provided is True


@pytest.mark.parametrize("field_name", ["is_error", "terminate"])
@pytest.mark.parametrize("value", [0, object(), _HostileTruthValue()])
def test_after_tool_call_result_requires_exact_optional_booleans(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(TypeError, match=rf"{field_name} must be bool or None"):
        AfterToolCallResult(**{field_name: value})


def test_agent_transport_option_is_removed() -> None:
    assert "transport" not in {field.name for field in fields(AgentOptions)}
    with pytest.raises(TypeError, match="transport"):
        Agent(transport="websocket")


def test_public_literal_and_union_types_are_defined() -> None:
    assert set(get_args(ToolExecutionMode)) == {"sequential", "parallel"}
    assert set(get_args(ThinkingLevel)) == {
        "off",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }
    assert get_args(AgentMessage)
    assert get_args(AgentEvent)
    assert get_args(ProxyAssistantMessageEvent)


def test_hook_contexts_reference_agent_types() -> None:
    before_annotations = BeforeToolCallContext.__annotations__
    after_annotations = AfterToolCallContext.__annotations__

    assert before_annotations["context"] == "AgentContext"
    assert after_annotations["context"] == "AgentContext"
    assert after_annotations["hook_details"] == "JSONValue"


def test_stream_proxy_is_exported() -> None:
    assert callable(stream_proxy)


def test_agent_loop_facades_are_exported() -> None:
    assert callable(agent_loop)
    assert callable(agent_loop_continue)


def test_agent_state_setters_copy_top_level_messages_and_tools_lists() -> None:
    state = AgentState(system_prompt="", model=_model(), thinking_level="off")
    original_message = UserMessage(role="user", content="hi", timestamp=0.0)
    original_messages = [original_message]
    original_tools = [{"name": "demo"}]

    state.set_messages(original_messages)
    state.set_tools(original_tools)

    original_messages.append(UserMessage(role="user", content="later", timestamp=1.0))
    original_tools.append({"name": "late-tool"})

    assert state.messages == [original_message]
    assert state.tools == [{"name": "demo"}]


def test_agent_state_getters_expose_live_messages_and_tools_lists() -> None:
    state = AgentState(system_prompt="", model=_model(), thinking_level="off")
    message = UserMessage(role="user", content="hi", timestamp=0.0)
    tool = {"name": "demo"}

    live_messages = state.messages
    live_tools = state.tools
    live_messages.append(message)
    live_tools.append(tool)

    assert state.messages[-1] is message
    assert state.tools[-1] is tool
