from __future__ import annotations

from typing import get_args

from loushang.agent import AgentEvent
from loushang.harness.tools.execution import direct_execution


def test_agent_session_event_accepts_core_agent_event() -> None:
    from loushang.harness.session import AgentSessionEvent

    event: AgentSessionEvent = {"type": "agent_start"}
    assert event["type"] == "agent_start"


def test_agent_session_event_accepts_compaction_extension_event() -> None:
    from loushang.harness.session import AgentSessionEvent

    event: AgentSessionEvent = {
        "type": "compaction_start",
        "reason": "manual",
    }
    assert event["type"] == "compaction_start"


def test_agent_session_event_accepts_branch_summary_events() -> None:
    from loushang.harness.session import AgentSessionEvent

    start: AgentSessionEvent = {
        "type": "branch_summary_start",
        "target_id": "t1",
        "old_leaf_id": "l1",
        "summarize": True,
    }
    end: AgentSessionEvent = {
        "type": "branch_summary_end",
        "target_id": "t1",
        "old_leaf_id": "l1",
        "new_leaf_id": "n1",
        "summary_entry_id": "s1",
        "cancelled": False,
        "aborted": False,
    }

    assert start["type"] == "branch_summary_start"
    assert end["type"] == "branch_summary_end"


def test_agent_session_event_accepts_auto_retry_events() -> None:
    from loushang.harness.session import AgentSessionEvent

    start: AgentSessionEvent = {
        "type": "auto_retry_start",
        "attempt": 1,
        "max_attempts": 2,
        "delay_ms": 250,
        "error_message": "503 service unavailable",
    }
    end: AgentSessionEvent = {
        "type": "auto_retry_end",
        "success": False,
        "attempt": 2,
        "final_error": "503 service unavailable",
    }

    assert start["type"] == "auto_retry_start"
    assert end["type"] == "auto_retry_end"


def test_agent_session_event_accepts_queue_update() -> None:
    from loushang.harness.session import AgentSessionEvent

    event: AgentSessionEvent = {
        "type": "queue_update",
        "steering": ["a"],
        "follow_up": ["b"],
    }
    assert event["steering"] == ["a"]


def test_agent_session_event_accepts_session_info_changed() -> None:
    from loushang.harness.session import AgentSessionEvent

    event: AgentSessionEvent = {
        "type": "session_info_changed",
        "name": "Demo",
    }
    assert event["name"] == "Demo"


def test_agent_session_event_extends_base_agent_event_union() -> None:
    from loushang.harness.session import AgentSessionEvent

    assert len(get_args(AgentSessionEvent)) > len(get_args(AgentEvent))


def test_serialize_session_event_uses_snake_case_json_keys() -> None:
    from loushang.harness.session import serialize_session_event

    payload = serialize_session_event(
        {
            "type": "queue_update",
            "steering": ["a"],
            "follow_up": ["b"],
        }
    )

    assert payload == {
        "type": "queue_update",
        "steering": ["a"],
        "follow_up": ["b"],
    }

    assert serialize_session_event(
        {"type": "session_info_changed", "name": "Demo"}
    ) == {
        "type": "session_info_changed",
        "name": "Demo",
    }


def test_serialize_session_event_uses_snake_case_for_branch_summary_events() -> None:
    from loushang.harness.session import serialize_session_event

    start_payload = serialize_session_event(
        {
            "type": "branch_summary_start",
            "target_id": "t1",
            "old_leaf_id": "l1",
            "summarize": True,
        }
    )
    end_payload = serialize_session_event(
        {
            "type": "branch_summary_end",
            "target_id": "t1",
            "old_leaf_id": "l1",
            "new_leaf_id": "n1",
            "summary_entry_id": "s1",
            "cancelled": False,
            "aborted": False,
            "error_message": "boom",
        }
    )

    assert start_payload == {
        "type": "branch_summary_start",
        "target_id": "t1",
        "old_leaf_id": "l1",
        "summarize": True,
    }
    assert end_payload == {
        "type": "branch_summary_end",
        "target_id": "t1",
        "old_leaf_id": "l1",
        "new_leaf_id": "n1",
        "summary_entry_id": "s1",
        "cancelled": False,
        "aborted": False,
        "error_message": "boom",
    }


def test_serialize_session_event_uses_snake_case_for_compaction_usage() -> None:
    from loushang.harness.session import serialize_session_event
    from loushang.harness.transcript import ContextUsageSnapshot

    usage = ContextUsageSnapshot(
        tokens=85,
        context_window=100,
        reserve_tokens=10,
        compact_percent=80,
        keep_recent_tokens=32,
        percent_threshold_tokens=80,
        reserve_threshold_tokens=90,
        threshold_tokens=80,
        threshold_reason="compact_percent",
        percent=85.0,
        source="assistant_usage",
        last_usage_index=0,
        stale_after_compaction=False,
        compactable=True,
        reason="threshold",
    )

    start_payload = serialize_session_event(
        {
            "type": "compaction_start",
            "reason": "threshold",
            "usage": usage,
        }
    )
    end_payload = serialize_session_event(
        {
            "type": "compaction_end",
            "reason": "threshold",
            "result": {"ok": True},
            "aborted": False,
            "will_retry": False,
            "usage_before": usage,
            "usage_after": {
                **usage.__dict__,
                "tokens": None,
                "percent": None,
                "stale_after_compaction": True,
            },
        }
    )

    assert start_payload["usage"]["context_window"] == 100
    assert start_payload["usage"]["compact_percent"] == 80
    assert start_payload["usage"]["keep_recent_tokens"] == 32
    assert start_payload["usage"]["threshold_reason"] == "compact_percent"

    assert end_payload["usage_before"]["threshold_tokens"] == 80
    assert end_payload["usage_after"]["tokens"] is None
    assert end_payload["usage_after"]["stale_after_compaction"] is True


def test_serialize_session_event_uses_snake_case_for_auto_retry_events() -> None:
    from loushang.harness.session import serialize_session_event

    start_payload = serialize_session_event(
        {
            "type": "auto_retry_start",
            "attempt": 1,
            "max_attempts": 3,
            "delay_ms": 250,
            "error_message": "network error",
        }
    )
    end_payload = serialize_session_event(
        {
            "type": "auto_retry_end",
            "success": False,
            "attempt": 2,
            "final_error": "503 service unavailable",
        }
    )

    assert start_payload == {
        "type": "auto_retry_start",
        "attempt": 1,
        "max_attempts": 3,
        "delay_ms": 250,
        "error_message": "network error",
    }
    assert end_payload == {
        "type": "auto_retry_end",
        "success": False,
        "attempt": 2,
        "final_error": "503 service unavailable",
    }


def test_serialize_session_event_uses_snake_case_for_package_progress_events() -> None:
    from loushang.harness.session import serialize_session_event

    payload = serialize_session_event(
        {
            "type": "package_progress",
            "progress_type": "start",
            "action": "install",
            "source": "pypi:acme-review-pack==1.2.3",
            "message": "Installing pypi:acme-review-pack==1.2.3...",
            "target_path": "/tmp/packages/python/acme-review-pack",
        }
    )

    assert payload == {
        "type": "package_progress",
        "progress_type": "start",
        "action": "install",
        "source": "pypi:acme-review-pack==1.2.3",
        "message": "Installing pypi:acme-review-pack==1.2.3...",
        "target_path": "/tmp/packages/python/acme-review-pack",
    }


def test_serialize_session_event_uses_snake_case_for_base_agent_events() -> None:
    from loushang.ai.types import AssistantMessage, TextPart, Usage
    from loushang.harness.session import serialize_session_event

    payload = serialize_session_event(
        {
            "type": "message_update",
            "message": AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="hello")],
                api="anthropic-messages",
                provider="anthropic",
                model="claude-sonnet",
                response_id="resp-1",
                usage=Usage(
                    input=1,
                    output=2,
                    cache_read=3,
                    cache_write=4,
                    total_tokens=5,
                    cost={
                        "input": 0.0,
                        "output": 0.0,
                        "cacheRead": 0.0,
                        "cacheWrite": 0.0,
                        "total": 0.0,
                    },
                ),
                stop_reason="stop",
                error_message=None,
                timestamp=1.0,
            ),
            "assistant_message_event": {
                "type": "text_delta",
                "content_index": 0,
                "delta": "he",
                "partial": AssistantMessage(
                    endpoint="test-endpoint",
                    role="assistant",
                    content=[TextPart(type="text", text="he")],
                    api="anthropic-messages",
                    provider="anthropic",
                    model="claude-sonnet",
                    response_id="resp-1",
                    usage=Usage(
                        input=1,
                        output=2,
                        cache_read=3,
                        cache_write=4,
                        total_tokens=5,
                        cost={
                            "input": 0.0,
                            "output": 0.0,
                            "cacheRead": 0.0,
                            "cacheWrite": 0.0,
                            "total": 0.0,
                        },
                    ),
                    stop_reason="stop",
                    error_message=None,
                    timestamp=1.0,
                ),
            },
        }
    )

    assert payload["assistant_message_event"]["content_index"] == 0
    assert payload["message"]["response_id"] == "resp-1"
    assert payload["message"]["stop_reason"] == "stop"


def test_project_session_event_can_attach_rendered_tool_payloads() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.harness.presentation import ToolRenderRuntime
    from loushang.harness.session import project_session_event
    from loushang.harness.tools.workspace import ToolDefinition

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[TextPart(type="text", text="ok")], details={})

    def render_call(args, theme, context):
        del theme
        context.state["path"] = args["path"]
        return {"text": f"call {args['path']}"}

    def render_result(result, options, theme, context):
        del theme
        return {
            "text": f"{context.state['path']} {result.content[0].text} partial={options.is_partial} expanded={options.expanded}",
            "class_name": "tool-row",
        }

    definition = ToolDefinition(
        name="read",
        label="Read",
        description="Read files",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        execution=direct_execution(execute),
        render_call=render_call,
        render_result=render_result,
    )
    runtime = ToolRenderRuntime()

    def resolver(name):
        return definition if name == "read" else None

    start_event = {
        "type": "tool_execution_start",
        "tool_call_id": "tc1",
        "tool_name": "read",
        "args": {"path": "README.md"},
    }
    update_event = {
        "type": "tool_execution_update",
        "tool_call_id": "tc1",
        "tool_name": "read",
        "args": {"path": "README.md"},
        "partial_result": AgentToolResult(
            content=[TextPart(type="text", text="partial")], details={}
        ),
    }
    end_event = {
        "type": "tool_execution_end",
        "tool_call_id": "tc1",
        "tool_name": "read",
        "result": AgentToolResult(
            content=[TextPart(type="text", text="final")],
            details={"full_output_path": "/tmp/read-full.txt"},
        ),
        "is_error": False,
    }

    default_payload = project_session_event(start_event, event_view="tools")[0]
    start_payload = project_session_event(
        start_event,
        event_view="tools",
        tool_render_runtime=runtime,
        tool_definition_resolver=resolver,
    )[0]
    update_payload = project_session_event(
        update_event,
        event_view="tools",
        tool_render_runtime=runtime,
        tool_definition_resolver=resolver,
    )[0]
    end_payload = project_session_event(
        end_event,
        event_view="tools",
        tool_render_runtime=runtime,
        tool_definition_resolver=resolver,
        tool_render_expanded=True,
    )[0]

    assert "rendered_tool_call" not in default_payload
    assert start_payload["rendered_tool_call"] == {
        "type": "text",
        "text": "call README.md",
        "plain_text": "call README.md",
        "contract_version": 1,
        "status": "running",
    }
    assert update_payload["rendered_tool_result"] == {
        "type": "text",
        "text": "README.md partial partial=True expanded=False",
        "plain_text": "README.md partial partial=True expanded=False",
        "class_name": "tool-row",
        "is_partial": True,
        "expanded": False,
        "contract_version": 1,
        "status": "partial",
        "collapsed_text": "README.md partial partial=True expanded=False",
        "artifacts": [],
    }
    assert end_payload["rendered_tool_result"] == {
        "type": "text",
        "text": "README.md final partial=False expanded=True",
        "plain_text": "README.md final partial=False expanded=True",
        "class_name": "tool-row",
        "is_partial": False,
        "expanded": True,
        "contract_version": 1,
        "status": "ok",
        "collapsed_text": "README.md final partial=False expanded=False",
        "expanded_text": "README.md final partial=False expanded=True",
        "artifacts": [
            {"type": "file", "path": "/tmp/read-full.txt", "name": "read-full.txt"}
        ],
    }


def test_project_session_event_marks_rendered_tool_error_status() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.harness.presentation import ToolRenderRuntime
    from loushang.harness.session import project_session_event
    from loushang.harness.tools.workspace import ToolDefinition

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[TextPart(type="text", text="ok")], details={})

    def render_result(result, options, theme, context):
        del options, theme, context
        return {"text": result.content[0].text}

    definition = ToolDefinition(
        name="bash",
        label="Bash",
        description="Run commands",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        execution=direct_execution(execute),
        render_result=render_result,
    )

    payload = project_session_event(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tc1",
            "tool_name": "bash",
            "result": AgentToolResult(
                content=[TextPart(type="text", text="boom")], details={}
            ),
            "is_error": True,
        },
        event_view="tools",
        tool_render_runtime=ToolRenderRuntime(),
        tool_definition_resolver=lambda name: definition if name == "bash" else None,
    )[0]

    assert payload["rendered_tool_result"]["status"] == "error"


def test_project_session_event_structures_tool_ui_state_and_bash_artifacts() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.harness.presentation import ToolRenderRuntime
    from loushang.harness.session import project_session_event
    from loushang.harness.tools.workspace import ToolDefinition

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[TextPart(type="text", text="ok")], details={})

    def render_result(result, options, theme, context):
        del options, theme, context
        return {"text": result.content[0].text}

    definition = ToolDefinition(
        name="bash",
        label="Bash",
        description="Run commands",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        execution=direct_execution(execute),
        render_result=render_result,
    )

    def project(details):
        return project_session_event(
            {
                "type": "tool_execution_end",
                "tool_call_id": "tc1",
                "tool_name": "bash",
                "result": AgentToolResult(
                    content=[TextPart(type="text", text="out")], details=details
                ),
                "is_error": False,
                "duration_ms": 123,
            },
            event_view="tools",
            tool_render_runtime=ToolRenderRuntime(),
            tool_definition_resolver=lambda name: (
                definition if name == "bash" else None
            ),
        )[0]["rendered_tool_result"]

    timed_out = project(
        {
            "timed_out": True,
            "stdout_artifact_path": "/tmp/stdout.log",
            "stderr_artifact_path": "/tmp/stderr.log",
        }
    )
    cancelled = project({"cancelled": True, "duration_ms": 456})

    assert timed_out["status"] == "timed_out"
    assert timed_out["duration_ms"] == 123
    assert timed_out["artifacts"] == [
        {
            "type": "file",
            "path": "/tmp/stdout.log",
            "name": "stdout.log",
            "stream": "stdout",
        },
        {
            "type": "file",
            "path": "/tmp/stderr.log",
            "name": "stderr.log",
            "stream": "stderr",
        },
    ]
    assert cancelled["status"] == "cancelled"
    assert cancelled["duration_ms"] == 456


def test_project_session_event_uses_distinct_event_and_presentation_views() -> None:
    from loushang.agent import FunctionalToolOutputProjector
    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.harness.presentation import ToolRenderRuntime
    from loushang.harness.session import project_session_event
    from loushang.harness.tools.workspace import ToolDefinition

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        raise AssertionError("not executed")

    def render_result(result, options, theme, context):
        del options, theme, context
        return {"text": f"surface={result.details['surface']}"}

    definition = ToolDefinition(
        name="bash",
        label="Bash",
        description="Run commands",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        execution=direct_execution(execute),
        render_result=render_result,
    )
    result = AgentToolResult(
        content=[TextPart(type="text", text="out")],
        details=object(),
        projector=FunctionalToolOutputProjector(
            transcript=lambda details: {"surface": "transcript"},
            event=lambda details: {
                "surface": "event",
                "timed_out": True,
                "duration_ms": 456,
                "stdout_artifact_path": "/tmp/stdout.log",
            },
        ),
    )
    event_result = result.for_event()
    assert event_result.details == {
        "surface": "event",
        "timed_out": True,
        "duration_ms": 456,
        "stdout_artifact_path": "/tmp/stdout.log",
    }
    assert event_result.details is not result.details

    payload = project_session_event(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tc1",
            "tool_name": "bash",
            "result": event_result,
            "is_error": False,
            "duration_ms": 123,
        },
        event_view="tools",
        tool_render_runtime=ToolRenderRuntime(),
        tool_definition_resolver=lambda name: definition if name == "bash" else None,
    )[0]

    assert payload["result"]["details"]["surface"] == "event"
    assert payload["rendered_tool_result"]["text"] == "surface=transcript"
    assert payload["rendered_tool_result"]["status"] == "timed_out"
    assert payload["rendered_tool_result"]["duration_ms"] == 456
    assert payload["rendered_tool_result"]["artifacts"] == [
        {
            "type": "file",
            "path": "/tmp/stdout.log",
            "name": "stdout.log",
            "stream": "stdout",
        }
    ]


def test_project_session_event_omits_rendered_tool_payload_when_renderer_fails() -> (
    None
):
    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.harness.presentation import ToolRenderRuntime
    from loushang.harness.session import project_session_event
    from loushang.harness.tools.workspace import ToolDefinition

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[TextPart(type="text", text="ok")], details={})

    def render_call(args, theme, context):
        del args, theme, context
        raise RuntimeError("renderer failed")

    definition = ToolDefinition(
        name="read",
        label="Read",
        description="Read files",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        execution=direct_execution(execute),
        render_call=render_call,
    )

    def resolver(name):
        return definition if name == "read" else None

    payload = project_session_event(
        {
            "type": "tool_execution_start",
            "tool_call_id": "tc1",
            "tool_name": "read",
            "args": {"path": "README.md"},
        },
        event_view="tools",
        tool_render_runtime=ToolRenderRuntime(),
        tool_definition_resolver=resolver,
    )[0]

    assert payload["type"] == "tool_execution_start"
    assert "rendered_tool_call" not in payload
