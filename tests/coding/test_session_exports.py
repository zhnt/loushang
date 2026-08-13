from __future__ import annotations

import asyncio
from pathlib import Path

from loushang.agent import Agent
from loushang.agent.types import AgentToolResult
from loushang.ai.types import (
    AssistantMessage,
    TextPart,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from loushang.coding.session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.harness.tools.execution import direct_execution
from loushang.harness.tools.workspace import ToolDefinition
from loushang.harness.tools.workspace.registry import (
    WorkspaceToolRegistry as ToolRegistry,
)
from loushang.harness.transcript.jsonl_file import (
    load_agent_transcript_file as load_session_file,
)


def _build_export_session(
    tmp_path, *, tool_registry: ToolRegistry | None = None
) -> AgentSession:
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="hello export")],
                timestamp=0.0,
            )
        )
    )
    asyncio.run(
        manager.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[
                    TextPart(type="text", text="Calling read"),
                    ToolCall(
                        type="toolCall",
                        id="call-1",
                        name="read",
                        arguments={"path": "README.md"},
                    ),
                ],
                api="anthropic-messages",
                provider="faux",
                model="faux-model",
                response_id=None,
                usage=Usage(
                    input=10,
                    output=20,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=30,
                    cost={},
                ),
                stop_reason="toolUse",
                error_message=None,
                timestamp=1.0,
            )
        )
    )
    asyncio.run(
        manager.append_message(
            ToolResultMessage(
                role="toolResult",
                tool_call_id="call-1",
                tool_name="read",
                content=[TextPart(type="text", text="README content")],
                is_error=False,
                timestamp=2.0,
            )
        )
    )
    return AgentSession(
        agent=Agent(), session_manager=manager, tool_registry=tool_registry
    )


def test_export_session_to_jsonl_writes_branch_entries_and_header(tmp_path) -> None:
    from loushang.harness.session.export import export_session_to_jsonl

    session = _build_export_session(tmp_path)

    output = export_session_to_jsonl(session, output_path=str(tmp_path / "out.jsonl"))

    assert output.endswith(".jsonl")
    header, entries = load_session_file(tmp_path / "out.jsonl")
    assert header.conversation_id == session.session_id
    assert len(entries) == len(session.session_manager.get_branch())


def test_agent_session_exposes_standard_export_methods(tmp_path) -> None:
    session = _build_export_session(tmp_path)

    jsonl_output = session.export_to_jsonl(str(tmp_path / "session.jsonl"))
    html_output = session.export_to_html(str(tmp_path / "session.html"))

    assert jsonl_output.endswith(".jsonl")
    assert html_output.endswith(".html")
    assert (tmp_path / "session.jsonl").exists()
    assert (tmp_path / "session.html").exists()


def test_export_session_to_jsonl_defaults_to_generated_filename(tmp_path) -> None:
    from loushang.harness.session.export import export_session_to_jsonl

    cwd = tmp_path / "project"
    cwd.mkdir()
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(cwd), persist=False
        )
    )
    session = AgentSession(agent=Agent(), session_manager=manager)

    output = export_session_to_jsonl(session)

    path = Path(output)
    assert path.name.startswith("session-")
    assert path.suffix == ".jsonl"
    assert path.parent == cwd.resolve()


def test_export_session_to_jsonl_rechains_current_branch_parent_ids(tmp_path) -> None:
    import json

    from loushang.harness.session.export import export_session_to_jsonl

    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(tmp_path), persist=False
        )
    )
    first_id = asyncio.run(
        manager.append_message(
            UserMessage(
                role="user", content=[TextPart(type="text", text="root")], timestamp=0.0
            )
        )
    )
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="discarded")],
                timestamp=1.0,
            )
        )
    )
    manager.branch(first_id)
    asyncio.run(
        manager.append_message(
            UserMessage(
                role="user", content=[TextPart(type="text", text="kept")], timestamp=2.0
            )
        )
    )
    session = AgentSession(agent=Agent(), session_manager=manager)

    output = export_session_to_jsonl(
        session, output_path=str(tmp_path / "branch.jsonl")
    )
    lines = [
        json.loads(line)
        for line in Path(output).read_text(encoding="utf-8").splitlines()
    ]
    entries = lines[1:]

    assert [entry["payload"]["content"][0]["text"] for entry in entries] == [
        "root",
        "kept",
    ]
    assert [entry["parentId"] for entry in entries] == [
        None,
        entries[0]["recordId"],
    ]


def test_render_transcript_uses_stable_message_ids() -> None:
    from loushang.harness.transcript.export import render_transcript

    html = render_transcript(
        [
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="first")],
                timestamp=0.0,
            ),
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="second")],
                timestamp=1.0,
            ),
        ]
    )

    assert 'id="message-1"' in html
    assert 'id="message-2"' in html


def test_render_transcript_renders_markdown_code_fences_with_syntax_highlighting() -> (
    None
):
    from loushang.harness.transcript.export import render_transcript

    html = render_transcript(
        [
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[
                    TextPart(
                        type="text",
                        text="Use this:\n\n```python\ndef answer():\n    return 42\n```",
                    )
                ],
                api="anthropic-messages",
                provider="faux",
                model="faux-model",
                response_id=None,
                usage=Usage(
                    input=1,
                    output=1,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=2,
                    cost={},
                ),
                stop_reason="end_turn",
                error_message=None,
                timestamp=1.0,
            )
        ]
    )

    assert 'class="markdown-content"' in html
    assert 'class="highlight language-python"' in html
    assert 'class="k">def</span>' in html
    assert "```" not in html


def test_export_session_to_html_writes_template_based_document(tmp_path) -> None:
    from loushang.harness.session.export import export_session_to_html

    session = _build_export_session(tmp_path)

    output = export_session_to_html(session, output_path=str(tmp_path / "session.html"))
    html = (tmp_path / "session.html").read_text(encoding="utf-8")

    assert output.endswith(".html")
    assert "<html" in html
    assert session.session_id in html


def test_export_session_to_html_includes_tool_and_stats_sections(tmp_path) -> None:
    from loushang.harness.session.export import export_session_to_html

    session = _build_export_session(tmp_path)

    output = export_session_to_html(session)
    html = Path(output).read_text(encoding="utf-8")

    assert "Context Usage" in html
    assert "Tool Calls" in html or "tool call" in html.lower()


def test_export_session_to_html_script_loads_embedded_session_data(tmp_path) -> None:
    from loushang.harness.session.export import export_session_to_html

    session = _build_export_session(tmp_path)

    output = export_session_to_html(session, output_path=str(tmp_path / "session.html"))
    html = Path(output).read_text(encoding="utf-8")

    assert "window.loushangSessionData" in html
    assert "TextDecoder" in html
    assert 'document.getElementById("session-data")' in html
    assert 'id="transcript-search"' in html
    assert 'id="message-type-filter"' in html
    assert "data-message-type=" in html
    assert 'class="sidebar"' in html
    assert 'id="tool-calls"' in html
    assert 'data-tool-name="read"' in html
    assert 'data-tool-status="ok"' in html
    assert "transcript-count" in html


def test_export_session_to_html_tool_results_include_presentation_notices(
    tmp_path,
) -> None:
    from loushang.harness.transcript.export import render_tool_sections

    html = render_tool_sections(
        [
            ToolResultMessage(
                role="toolResult",
                tool_call_id="call-1",
                tool_name="bash",
                content=[TextPart(type="text", text="tail")],
                is_error=False,
                timestamp=1.0,
                details={
                    "truncation": {"truncated": True, "maxBytes": 50 * 1024},
                    "fullOutputPath": "/tmp/full.log",
                },
            )
        ]
    )

    assert "[Truncated: 50.0KB limit]" in html
    assert "[Full output: /tmp/full.log]" in html


def test_export_session_to_html_tool_results_convert_ansi_to_html() -> None:
    from loushang.harness.transcript.export import render_tool_sections

    html = render_tool_sections(
        [
            ToolResultMessage(
                role="toolResult",
                tool_call_id="call-1",
                tool_name="bash",
                content=[TextPart(type="text", text="\x1b[31mred\x1b[0m normal")],
                is_error=False,
                timestamp=1.0,
            )
        ]
    )

    assert "\x1b[" not in html
    assert '<span style="color:#800000">red</span>' in html
    assert "normal" in html


def test_export_session_to_html_uses_tool_renderers(tmp_path) -> None:
    from loushang.harness.session.export import export_session_to_html

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[TextPart(type="text", text="ok")], details={})

    def render_call(args, theme, context):
        return {
            "html": (
                f'<span class="custom-call">{args["path"]} '
                f"{theme['accent']} {context.tool_call_id} {context.cwd}</span>"
            )
        }

    def render_result(result, options, theme, context):
        del theme
        return {
            "text": (
                f"rendered {context.args['path']} "
                f"expanded={options.expanded} error={context.is_error} "
                f"text={result.content[0].text}"
            )
        }

    registry = ToolRegistry()
    registry.register_tool(
        ToolDefinition(
            name="read",
            label="Read",
            description="Read files",
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            execution=direct_execution(execute),
            render_call=render_call,
            render_result=render_result,
        )
    )
    session = _build_export_session(tmp_path, tool_registry=registry)
    session.export_theme = {"accent": "blue"}

    output = export_session_to_html(session, output_path=str(tmp_path / "session.html"))
    html = Path(output).read_text(encoding="utf-8")

    assert '<span class="custom-call">README.md blue call-1 /tmp/project</span>' in html
    assert "rendered README.md expanded=False error=False text=README content" in html


def test_render_tool_sections_falls_back_when_tool_renderer_fails() -> None:
    from loushang.harness.transcript.export import render_tool_sections

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[TextPart(type="text", text="ok")], details={})

    def render_result(result, options, theme, context):
        del result, options, theme, context
        raise RuntimeError("renderer failed")

    definition = ToolDefinition(
        name="bash",
        label="Bash",
        description="Run commands",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        execution=direct_execution(execute),
        render_result=render_result,
    )

    html = render_tool_sections(
        [
            ToolResultMessage(
                role="toolResult",
                tool_call_id="call-1",
                tool_name="bash",
                content=[TextPart(type="text", text="fallback text")],
                is_error=False,
                timestamp=1.0,
            )
        ],
        tool_definition_resolver=lambda name: definition if name == "bash" else None,
    )

    assert "fallback text" in html
    assert "renderer failed" not in html


def test_render_tool_sections_uses_shared_renderer_runtime_state() -> None:
    from loushang.harness.transcript.export import render_tool_sections

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[TextPart(type="text", text="ok")], details={})

    def render_call(args, theme, context):
        del theme
        context.state["path"] = args["path"]
        return {"text": f"call {context.tool_call_id}"}

    def render_result(result, options, theme, context):
        del result, theme
        return {
            "text": (
                f"{context.state['path']} expanded={options.expanded} "
                f"last={context.last_rendered is not None}"
            )
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

    html = render_tool_sections(
        [
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[
                    ToolCall(
                        type="toolCall",
                        id="call-1",
                        name="read",
                        arguments={"path": "README.md"},
                    ),
                ],
                api="anthropic-messages",
                provider="faux",
                model="faux-model",
                response_id=None,
                usage=Usage(
                    input=1,
                    output=1,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=2,
                    cost={},
                ),
                stop_reason="toolUse",
                error_message=None,
                timestamp=1.0,
            ),
            ToolResultMessage(
                role="toolResult",
                tool_call_id="call-1",
                tool_name="read",
                content=[TextPart(type="text", text="done")],
                is_error=False,
                timestamp=2.0,
            ),
        ],
        tool_definition_resolver=lambda name: definition if name == "read" else None,
    )

    assert "README.md expanded=False last=False" in html
    assert "README.md expanded=True last=True" in html
    assert 'data-render-contract-version="1"' in html
    assert 'data-render-status="ok"' in html


def test_export_session_to_html_embeds_entry_tree_and_summary_entries(tmp_path) -> None:
    import base64
    import json
    import re

    from loushang.harness.session.export import export_session_to_html

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    first_id = asyncio.run(
        manager.append_message(
            UserMessage(
                role="user", content=[TextPart(type="text", text="root")], timestamp=0.0
            )
        )
    )
    asyncio.run(
        manager.append_message(
            AssistantMessage(
                endpoint="test-endpoint",
                role="assistant",
                content=[TextPart(type="text", text="main branch")],
                api="anthropic-messages",
                provider="faux",
                model="faux-model",
                response_id=None,
                usage=Usage(
                    input=1,
                    output=1,
                    cache_read=0,
                    cache_write=0,
                    total_tokens=2,
                    cost={},
                ),
                stop_reason="end_turn",
                error_message=None,
                timestamp=1.0,
            )
        )
    )
    manager.branch(first_id)
    summary_id = asyncio.run(
        manager.branch_with_summary(first_id, "branch summary text")
    )
    asyncio.run(
        manager.append_compaction(
            summary="compact summary text",
            first_kept_entry_id=first_id,
            tokens_before=1234,
        )
    )
    asyncio.run(manager.append_label(summary_id, "summary label"))
    session = AgentSession(agent=Agent(), session_manager=manager)

    output = export_session_to_html(session, output_path=str(tmp_path / "session.html"))
    html = Path(output).read_text(encoding="utf-8")

    encoded = re.search(
        r'<script id="session-data" type="application/json">([^<]+)</script>', html
    )
    assert encoded is not None
    data = json.loads(base64.b64decode(encoded.group(1)).decode("utf-8"))
    assert data["leafId"] == manager.get_leaf_id()
    assert [entry["type"] for entry in data["entries"]] == ["record"] * 5
    assert [entry["kind"] for entry in data["entries"]] == [
        "agent.message",
        "agent.message",
        "context.branch_summary",
        "context.compaction_checkpoint",
        "record.annotation_patch",
    ]
    assert data["tree"]["entryCount"] == 5
    assert data["tree"]["leafId"] == manager.get_leaf_id()
    assert "Session Tree" in html
    assert "branch summary text" in html
    assert "compact summary text" in html
    assert "summary label" in html
    assert "main branch" not in html


def test_product_transcript_dispositions_cover_every_standard_kind() -> None:
    from loushang.harness.transcript import STANDARD_AGENT_TRANSCRIPT_KINDS
    from loushang.harness.transcript.export import (
        HTML_TRANSCRIPT_DISPOSITIONS,
    )
    from loushang.harnesstui.conversation.agent_binding import (
        STANDARD_AGENT_HISTORY_DISPOSITIONS,
    )

    expected = set(STANDARD_AGENT_TRANSCRIPT_KINDS)
    assert set(HTML_TRANSCRIPT_DISPOSITIONS) == expected
    assert set(STANDARD_AGENT_HISTORY_DISPOSITIONS) == expected


def test_export_session_to_html_embeds_system_prompt_and_tool_definitions(
    tmp_path,
) -> None:
    import base64
    import json
    import re

    from loushang.harness.session.export import export_session_to_html

    async def execute_probe(tool_call_id, params, signal, on_update):
        return AgentToolResult(content=[TextPart(type="text", text="ok")])

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    registry = ToolRegistry()
    registry.register_tool(
        ToolDefinition(
            name="probe",
            label="Probe",
            description="Inspect probe data",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            execution=direct_execution(execute_probe),
        )
    )
    agent = Agent(initial_state={"system_prompt": "export prompt", "tools": []})
    session = AgentSession(
        agent=agent,
        session_manager=manager,
        tool_registry=registry,
        active_tool_names=["probe"],
    )

    output = export_session_to_html(session, output_path=str(tmp_path / "session.html"))
    html = Path(output).read_text(encoding="utf-8")

    encoded = re.search(
        r'<script id="session-data" type="application/json">([^<]+)</script>', html
    )
    assert encoded is not None
    data = json.loads(base64.b64decode(encoded.group(1)).decode("utf-8"))
    assert data["systemPrompt"] == session.agent.system_prompt
    assert "export prompt" in data["systemPrompt"]
    assert data["tools"] == [
        {
            "name": "probe",
            "description": "Inspect probe data",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        }
    ]


def test_export_session_to_html_uses_custom_renderer_and_theme(tmp_path) -> None:
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.session.export import export_session_to_html

    def _renderer(message, options, theme):
        assert options == {"format": "html_export"}
        return {
            "html": (
                '<div class="rendered-card" style="color: var(--accent-color)">'
                + message.custom_type
                + "-"
                + theme["accent-color"]
                + "</div>"
            ),
            "className": "custom rendered-card-shell",
        }

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    asyncio.run(
        manager.append_custom_message_entry("demo.card", "custom payload", True)
    )
    session = AgentSession(
        agent=Agent(),
        session_manager=manager,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="cards",
                    source_path=tmp_path / "cards.py",
                    message_renderers={"demo.card": _renderer},
                )
            ]
        ),
    )
    session.export_theme = {"accent-color": "#123456"}

    output = export_session_to_html(session, output_path=str(tmp_path / "session.html"))
    html = Path(output).read_text(encoding="utf-8")

    assert "--accent-color: #123456;" in html
    assert "rendered-card" in html
    assert "demo.card-#123456" in html
    assert "syntax-key" in html
