from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from loushang.harnesstui.conversation.tool_transcript import (
    ToolCallSnapshot,
    ToolCallView,
    ToolResultView,
    ToolTranscriptBlock,
    ToolTranscriptProjectionBinding,
    ToolTranscriptProjector,
    build_mapping_tool_transcript_projection,
    tool_block_to_record,
)
from loushang.tui.transcript import ToolExecutionRecord


def test_projection_binding_composes_raw_view_ports_with_neutral_projector() -> None:
    calls: list[tuple[str, object]] = []

    def call_view(event: dict[str, object]) -> ToolCallView:
        calls.append(("call_view", event))
        return ToolCallView(
            tool_call_id=str(event["id"]),
            tool_name=str(event["name"]),
            args=event.get("args"),
        )

    def result_view(
        event: dict[str, object],
        snapshot: ToolCallSnapshot | None,
        tool_call_id: str | None,
    ) -> ToolResultView:
        del snapshot
        calls.append(("result_view", event))
        return ToolResultView(
            tool_call_id=tool_call_id or str(event["id"]),
            tool_name=str(event["name"]),
            status="ok",
        )

    binding = ToolTranscriptProjectionBinding[dict[str, object], object](
        neutral_projector=ToolTranscriptProjector(
            verb_resolver=lambda tool_name, args: "Ran"
        ),
        call_id=lambda event: str(event["id"]),
        message_id=lambda message: str(getattr(message, "id", "")),
        call_view=call_view,
        result_view=result_view,
        tool_result_message_view=lambda message: ToolResultView(
            tool_call_id="message-1",
            tool_name="read",
            status="ok",
        ),
    )
    raw_call = {"id": "call-1", "name": "bash", "args": {"command": "pytest"}}
    snapshot = binding.remember_call(raw_call)

    assert binding.call_id(raw_call) == "call-1"
    assert snapshot.tool_name == "bash"
    assert binding.project_result(
        {"id": "call-1", "name": "ignored"},
        snapshot,
    ) == ToolTranscriptBlock(
        tool_call_id="call-1",
        tool_name="bash",
        status="ok",
        verb="Ran",
        title="bash pytest",
    )
    assert binding.project_tool_result_message(object()).tool_call_id == "message-1"
    assert [name for name, _event in calls] == ["call_view", "result_view"]


def test_mapping_projection_reuses_workspace_policy_with_injected_results() -> None:
    binding = build_mapping_tool_transcript_projection(
        result_text=lambda result, _max_lines: str(result),
        result_details=lambda _result: {},
        result_terminated=lambda _result: False,
        error_summary=lambda _result: None,
        message_event=lambda _message: {
            "type": "tool_execution_end",
            "tool_call_id": "message-1",
            "tool_name": "read",
            "result": "done",
        },
    )
    event = {
        "type": "tool_execution_start",
        "tool_call_id": "call-1",
        "tool_name": "bash",
        "args": {"command": "pytest -q"},
    }
    snapshot = binding.remember_call(event)
    block = binding.project_result(
        {
            "type": "tool_execution_end",
            "tool_call_id": "call-1",
            "tool_name": "bash",
            "result": "passed",
        },
        snapshot,
    )

    assert block.verb == "Tested"
    assert block.command == "bash pytest -q"
    assert block.body == "passed"


def test_neutral_projector_combines_call_snapshot_and_result_view() -> None:
    projector = ToolTranscriptProjector(
        verb_resolver=lambda tool_name, args: "Tested",
        body_visibility=lambda tool_name, status: status == "ok",
        command_resolver=lambda tool_name, args, title: title,
        max_body_lines=3,
    )
    snapshot = projector.remember_call(
        ToolCallView(
            tool_call_id="tc1",
            tool_name="bash",
            args={"command": "pytest tests/tui -q"},
            rendered_text="$ pytest tests/tui -q",
        )
    )

    block = projector.project_result(
        ToolResultView(
            tool_call_id="tc1",
            tool_name="ignored-after-snapshot",
            status="ok",
            result_text="one\ntwo\nthree\nfour",
        ),
        snapshot,
    )

    assert block == ToolTranscriptBlock(
        tool_call_id="tc1",
        tool_name="bash",
        status="ok",
        verb="Tested",
        title="bash pytest tests/tui -q",
        body="... (1 earlier lines)\ntwo\nthree\nfour",
        command="bash pytest tests/tui -q",
    )


def test_neutral_projector_defaults_do_not_assume_product_policy() -> None:
    projector = ToolTranscriptProjector()

    block = projector.project_result(
        ToolResultView(
            tool_call_id="tc1",
            tool_name="custom",
            status="ok",
            args={"path": "src/app.py"},
            result_text="not shown without a body policy",
        )
    )

    assert block.verb == "Used custom"
    assert block.title == "custom src/app.py"
    assert block.body is None


@pytest.mark.parametrize(
    ("status", "error_summary", "detail"),
    [
        ("running", None, None),
        ("error", "exit code 2", "failed: exit code 2"),
        ("cancelled", None, "cancelled"),
        ("timed_out", None, "timed out"),
        ("terminate", None, "terminated"),
    ],
)
def test_neutral_result_status_projects_generic_detail(
    status: str,
    error_summary: str | None,
    detail: str | None,
) -> None:
    projector = ToolTranscriptProjector()

    block = projector.project_result(
        ToolResultView(
            tool_call_id="tc1",
            tool_name="tool",
            status=status,  # type: ignore[arg-type]
            error_summary=error_summary,
        )
    )

    assert block.detail == detail


def test_neutral_result_details_project_edit_and_write_stats() -> None:
    projector = ToolTranscriptProjector()

    edit = projector.project_result(
        ToolResultView(
            tool_call_id="edit-1",
            tool_name="apply_patch",
            status="ok",
            details={"diff": "--- a/app.py\n+++ b/app.py\n@@\n-old\n+new"},
        )
    )
    write = projector.project_result(
        ToolResultView(
            tool_call_id="write-1",
            tool_name="write",
            status="ok",
            details={"operation": "overwrite", "bytesWritten": 2048},
        )
    )

    assert edit.detail == "+1 -1"
    assert write.detail == "overwrote, 2.0 KiB"


def test_tool_result_view_is_immutable() -> None:
    view = ToolResultView(tool_call_id="tc1", tool_name="tool", status="ok")

    with pytest.raises(FrozenInstanceError):
        view.status = "error"  # type: ignore[misc]


def test_tool_block_projects_to_generic_tool_execution_record() -> None:
    block = ToolTranscriptBlock(
        tool_call_id="tc1",
        tool_name="bash",
        status="ok",
        verb="Ran",
        title="uv run pytest tests/tui -q",
        detail=None,
        body="passed\n2 passed",
        command="uv run pytest tests/tui -q",
    )

    record = tool_block_to_record(block, elapsed_seconds=1.25)

    assert record == ToolExecutionRecord(
        name="uv run pytest tests/tui -q",
        state="completed",
        elapsed_seconds=1.25,
        output="passed\n2 passed",
        command="uv run pytest tests/tui -q",
    )


def test_tool_block_projects_failure_detail_to_stderr_and_exit_code() -> None:
    block = ToolTranscriptBlock(
        tool_call_id="tc1",
        tool_name="bash",
        status="error",
        verb="Ran",
        title="pytest",
        detail="failed: exit code 2",
        body="",
    )

    record = tool_block_to_record(block, elapsed_seconds=0.5)

    assert record.state == "failed"
    assert record.stderr == "failed: exit code 2"
    assert record.exit_code == 2


def test_neutral_record_projection_does_not_infer_command_from_product_verb() -> None:
    block = ToolTranscriptBlock(
        tool_call_id="tc1",
        tool_name="custom",
        status="ok",
        verb="Ran",
        title="product label",
    )

    assert tool_block_to_record(block).command == ""


def test_tool_block_infers_diff_output_kind() -> None:
    block = ToolTranscriptBlock(
        tool_call_id="tc1",
        tool_name="apply_patch",
        status="ok",
        verb="Edited",
        title="src/app.py",
        body="diff --git a/src/app.py b/src/app.py\n@@\n-old\n+new",
    )

    record = tool_block_to_record(block)

    assert record.output_kind == "diff"
    assert record.show_stats is True
