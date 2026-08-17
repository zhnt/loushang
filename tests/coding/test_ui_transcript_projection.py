from __future__ import annotations


def test_coding_tool_record_projection_preserves_command_label_policy() -> None:
    from loushang.harnesstui.conversation.agent_binding import (
        agent_tool_block_to_record,
    )
    from loushang.harnesstui.conversation.tool_transcript import (
        ToolTranscriptBlock,
    )

    block = ToolTranscriptBlock(
        tool_call_id="tc1",
        tool_name="bash",
        status="ok",
        verb="Ran",
        title="pytest -q",
    )

    assert agent_tool_block_to_record(block).command == "pytest -q"
