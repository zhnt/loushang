from __future__ import annotations

from loushang.agent import AgentToolResult
from loushang.ai import TextPart


def _result(text: str, *, details: object | None = None, terminate: bool = False) -> AgentToolResult:
    return AgentToolResult(content=[TextPart(type="text", text=text)], details=details or {}, terminate=terminate)


def _project(tool_name: str, args: dict[str, object], result: AgentToolResult, *, is_error: bool = False, max_body_lines: int = 4):
    from loushang.coding.tools import create_all_tool_definitions
    from loushang.coding.ui.tool_blocks import ToolTranscriptProjector

    definitions = create_all_tool_definitions()
    projector = ToolTranscriptProjector(tool_definition_resolver=definitions.get, max_body_lines=max_body_lines)
    snapshot = projector.remember_call(
        {
            "type": "tool_execution_start",
            "tool_call_id": "tc1",
            "tool_name": tool_name,
            "args": args,
        }
    )
    return projector.project_result(
        {
            "type": "tool_execution_end",
            "tool_call_id": "tc1",
            "tool_name": tool_name,
            "result": result,
            "is_error": is_error,
        },
        snapshot,
    )


def test_builtin_read_tool_transcript_block_uses_call_renderer_without_body() -> None:
    block = _project("read", {"path": "src/loushang/coding/ui/mode.py", "offset": 10, "limit": 3}, _result("line1\nline2"))

    assert block.verb == "Explored"
    assert block.title == "read src/loushang/coding/ui/mode.py:10-12"
    assert block.status == "ok"
    assert block.body is None


def test_builtin_bash_tool_transcript_block_shows_bounded_output_preview() -> None:
    block = _project(
        "bash",
        {"command": "pytest tests/coding -q"},
        _result("\n".join(f"line {index}" for index in range(1, 8))),
        max_body_lines=3,
    )

    assert block.verb == "Tested"
    assert block.title == "bash pytest tests/coding -q"
    assert block.status == "ok"
    assert block.body is not None
    assert len(block.body.splitlines()) <= 4
    assert "line 7" in block.body


def test_builtin_bash_tool_transcript_block_shows_head_and_tail_preview_by_default() -> None:
    block = _project(
        "bash",
        {"command": "pytest tests/coding -q"},
        _result("\n".join(f"line {index}" for index in range(1, 13))),
        max_body_lines=8,
    )

    assert block.body == (
        "line 1\n"
        "line 2\n"
        "line 3\n"
        "... (6 hidden lines)\n"
        "line 10\n"
        "line 11\n"
        "line 12"
    )


def test_builtin_edit_and_write_blocks_do_not_dump_tool_result_bodies() -> None:
    edit = _project(
        "edit",
        {"path": "src/example.py", "oldText": "old", "newText": "new"},
        _result(
            "Applied 1 edit to src/example.py",
            details={"diff": "--- a/src/example.py\n+++ b/src/example.py\n@@\n-old\n+new"},
        ),
    )
    write = _project(
        "write",
        {"path": "src/new.py", "content": "print('hello')"},
        _result("Successfully wrote 14 bytes to src/new.py", details={"operation": "create", "bytes_written": 14}),
    )

    assert edit.verb == "Edited"
    assert edit.title == "edit src/example.py (1 edit)"
    assert edit.detail == "+1 -1"
    assert edit.body is None
    assert write.verb == "Edited"
    assert write.title == "write src/new.py"
    assert write.detail == "created, 14 B"
    assert write.body is None


def test_builtin_search_blocks_show_bounded_result_preview() -> None:
    grep = _project("grep", {"pattern": "ToolTranscript", "path": "src"}, _result("a.py:1\nb.py:2\nc.py:3"), max_body_lines=2)
    ls = _project("ls", {"path": "src/loushang"}, _result("agent\nai\ncoding\ntui"), max_body_lines=2)

    assert grep.verb == "Explored"
    assert grep.title == "grep /ToolTranscript/ in src"
    assert grep.body == "a.py:1\nb.py:2\n... (1 more lines)"
    assert ls.verb == "Explored"
    assert ls.title == "ls src/loushang"
    assert ls.body == "agent\nai\n... (2 more lines)"


def test_builtin_failed_tool_transcript_block_uses_error_detail_not_body() -> None:
    block = _project("bash", {"command": "exit 1"}, _result("boom\nmore detail"), is_error=True)

    assert block.status == "error"
    assert block.detail == "failed: boom"
    assert block.body is None
