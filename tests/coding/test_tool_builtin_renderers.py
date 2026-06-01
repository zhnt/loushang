from __future__ import annotations

from loushang.agent.types import AgentToolResult
from loushang.ai.types import TextPart


def test_builtin_tool_definitions_expose_renderers_for_streaming_views() -> None:
    from loushang.coding.tools import create_all_tool_definitions

    definitions = create_all_tool_definitions()

    assert set(definitions) == {"read", "bash", "edit", "write", "grep", "find", "ls"}
    for definition in definitions.values():
        assert definition.render_call is not None
        assert definition.render_result is not None


def test_builtin_tool_renderers_format_call_headers() -> None:
    from loushang.coding.tools import ToolRenderRuntime, create_all_tool_definitions

    definitions = create_all_tool_definitions()
    runtime = ToolRenderRuntime(cwd="/repo")

    cases = [
        ("bash", {"command": "echo hi", "timeout": 2}, "$ echo hi (timeout 2s)"),
        ("read", {"path": "README.md"}, "read README.md"),
        ("read", {"path": "README.md", "offset": 3, "limit": 2}, "read README.md:3-4"),
        ("grep", {"pattern": "needle", "path": "src", "glob": "*.py", "limit": 5}, "grep /needle/ in src (*.py) limit 5"),
        ("find", {"pattern": "*.py", "path": "src", "limit": 5}, "find *.py in src (limit 5)"),
        ("ls", {"path": "src", "limit": 5}, "ls src (limit 5)"),
        ("write", {"path": "notes/out.txt"}, "write notes/out.txt"),
        ("edit", {"path": "notes/out.txt", "edits": [{"oldText": "a", "newText": "b"}]}, "edit notes/out.txt (1 edit)"),
    ]

    for tool_name, args, expected in cases:
        rendered = runtime.render_call(definitions[tool_name], f"call-{tool_name}", args)
        assert rendered == expected


def test_builtin_tool_result_renderer_collapses_and_expands_text_output() -> None:
    from loushang.coding.tools import ToolRenderRuntime, create_all_tool_definitions

    definitions = create_all_tool_definitions()
    runtime = ToolRenderRuntime(cwd="/repo")
    result = AgentToolResult(
        content=[TextPart(type="text", text="\n".join(f"line {index}" for index in range(1, 18)))],
        details={
            "truncation": {"truncated": True, "maxBytes": 50 * 1024},
            "fullOutputPath": "/tmp/full.log",
        },
    )

    collapsed = runtime.render_result(definitions["read"], "call-read", result)
    expanded = runtime.render_result(definitions["read"], "call-read", result, expanded=True)

    assert collapsed == (
        "line 1\n"
        "line 2\n"
        "line 3\n"
        "line 4\n"
        "line 5\n"
        "line 6\n"
        "line 7\n"
        "line 8\n"
        "line 9\n"
        "line 10\n"
        "... (7 more lines)\n"
        "[Truncated: 50.0KB limit]\n"
        "[Full output: /tmp/full.log]"
    )
    assert expanded.endswith("[Truncated: 50.0KB limit]\n[Full output: /tmp/full.log]")


def test_search_and_listing_result_renderers_use_pi_collapsed_limits() -> None:
    from loushang.coding.tools import ToolRenderRuntime, create_all_tool_definitions

    definitions = create_all_tool_definitions()
    runtime = ToolRenderRuntime(cwd="/repo")

    grep_result = AgentToolResult(
        content=[TextPart(type="text", text="\n".join(f"match {index}" for index in range(1, 18)))],
        details={"matchLimitReached": 100, "linesTruncated": True},
    )
    find_result = AgentToolResult(
        content=[TextPart(type="text", text="\n".join(f"file-{index}.py" for index in range(1, 24)))],
        details={"resultLimitReached": 1000},
    )
    ls_result = AgentToolResult(
        content=[TextPart(type="text", text="\n".join(f"entry-{index}" for index in range(1, 24)))],
        details={"entryLimitReached": 500},
    )

    assert runtime.render_result(definitions["grep"], "call-grep", grep_result) == (
        "match 1\n"
        "match 2\n"
        "match 3\n"
        "match 4\n"
        "match 5\n"
        "match 6\n"
        "match 7\n"
        "match 8\n"
        "match 9\n"
        "match 10\n"
        "match 11\n"
        "match 12\n"
        "match 13\n"
        "match 14\n"
        "match 15\n"
        "... (2 more lines)\n"
        "[Truncated: 100 matches limit, some lines truncated]"
    )
    assert runtime.render_result(definitions["find"], "call-find", find_result).endswith(
        "file-20.py\n... (3 more lines)\n[Truncated: 1000 results limit]"
    )
    assert runtime.render_result(definitions["ls"], "call-ls", ls_result).endswith(
        "entry-20\n... (3 more lines)\n[Truncated: 500 entries limit]"
    )


def test_bash_renderer_uses_tail_preview_and_duration_labels() -> None:
    from loushang.coding.tools import ToolRenderRuntime, create_all_tool_definitions

    definitions = create_all_tool_definitions()
    runtime = ToolRenderRuntime(cwd="/repo")
    runtime.render_call(definitions["bash"], "call-bash", {"command": "printf lines"})
    result = AgentToolResult(
        content=[TextPart(type="text", text="\n".join(f"line {index}" for index in range(1, 11)))],
        details={"fullOutputPath": "/tmp/bash.log"},
    )

    partial = runtime.render_result(definitions["bash"], "call-bash", result, is_partial=True)
    final = runtime.render_result(definitions["bash"], "call-bash", result)

    assert partial.startswith("... (5 earlier lines)\nline 6\nline 7\nline 8\nline 9\nline 10")
    assert final.startswith("line 1\nline 2\nline 3\n... (4 hidden lines)\nline 8\nline 9\nline 10")
    assert "[Full output: /tmp/bash.log]" in partial
    assert "Elapsed " in partial
    assert "Took " in final


def test_write_call_renderer_previews_content_like_pi() -> None:
    from loushang.coding.tools import ToolRenderRuntime, create_all_tool_definitions

    definitions = create_all_tool_definitions()
    runtime = ToolRenderRuntime(cwd="/repo")

    rendered = runtime.render_call(
        definitions["write"],
        "call-write",
        {"path": "notes/out.txt", "content": "\n".join(f"line {index}" for index in range(1, 13))},
    )

    assert rendered == (
        "write notes/out.txt\n\n"
        "line 1\n"
        "line 2\n"
        "line 3\n"
        "line 4\n"
        "line 5\n"
        "line 6\n"
        "line 7\n"
        "line 8\n"
        "line 9\n"
        "line 10\n"
        "... (2 more lines, 12 total)"
    )


def test_edit_tool_result_renderer_prefers_diff_payload() -> None:
    from loushang.coding.tools import ToolRenderRuntime, create_all_tool_definitions

    definitions = create_all_tool_definitions()
    runtime = ToolRenderRuntime(cwd="/repo")
    result = AgentToolResult(
        content=[TextPart(type="text", text="Applied 1 edits to notes/out.txt")],
        details={"diff": "--- a/notes/out.txt\n+++ b/notes/out.txt\n@@\n-a\n+b"},
    )

    rendered = runtime.render_result(definitions["edit"], "call-edit", result)

    assert rendered == "--- a/notes/out.txt\n+++ b/notes/out.txt\n@@\n-a\n+b"
