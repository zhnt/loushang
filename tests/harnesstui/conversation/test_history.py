from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

from loushang.harness.conversation.types import ConversationRecord
from loushang.harnesstui.conversation.history import (
    ConversationHistoryProjector,
    project_agent_message_payload,
    project_command_execution_payload,
    project_context_branch_summary_payload,
    project_context_compaction_payload,
)
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    ToolExecutionRecord,
    UserPromptRecord,
)


def _record(kind: str, payload: object) -> ConversationRecord[object]:
    return ConversationRecord(
        record_id=f"record-{kind}",
        parent_id=None,
        kind=kind,
        payload_version=1,
        created_at="2026-01-01T00:00:00Z",
        payload=payload,
    )


def test_history_projector_filters_and_dispatches_records_in_source_order() -> None:
    seen: list[tuple[str, object]] = []

    def project_message(payload: object):
        seen.append(("message", payload))
        return AssistantMessageRecord(str(payload))

    def project_command(payload: object):
        seen.append(("command", payload))
        return UserPromptRecord(str(payload))

    def project_fallback(payload: object):
        seen.append(("fallback", payload))
        return UserPromptRecord(str(payload))

    projector = ConversationHistoryProjector(
        dispositions={
            "message": "render",
            "command": "render",
            "state": "state-only",
            "hidden": "hidden",
            "metadata": "metadata-only",
        },
        payload_projectors={
            "message": project_message,
            "command": project_command,
        },
        fallback_projector=project_fallback,
    )

    records = projector.project_items(
        (
            _record("message", "answer"),
            _record("state", "ignored state"),
            "legacy prompt",
            _record("command", "run tests"),
            _record("hidden", "ignored hidden"),
            _record("metadata", "ignored metadata"),
            _record("unknown", "ignored unknown"),
        )
    )

    assert records == (
        AssistantMessageRecord("answer"),
        UserPromptRecord("legacy prompt"),
        UserPromptRecord("run tests"),
    )
    assert seen == [
        ("message", "answer"),
        ("fallback", "legacy prompt"),
        ("command", "run tests"),
    ]


def test_history_projector_omits_render_kind_without_payload_projector() -> None:
    projector = ConversationHistoryProjector(
        dispositions={"unsupported": "render"},
        payload_projectors={},
        fallback_projector=lambda _item: None,
    )

    assert projector.project_item(_record("unsupported", object())) is None


def test_context_section_projectors_validate_neutral_payload_shapes() -> None:
    assert project_context_compaction_payload(
        SimpleNamespace(summary="condensed", tokens_before=1200)
    ) == ContextCompactionRecord(summary="condensed", tokens_before=1200)
    assert project_context_branch_summary_payload(
        SimpleNamespace(summary="branch context")
    ) == ContextCompactionRecord(summary="branch context")
    assert (
        project_context_compaction_payload(
            SimpleNamespace(summary="bad", tokens_before="many")
        )
        is None
    )
    assert project_context_branch_summary_payload(SimpleNamespace()) is None


def test_agent_message_projector_uses_structural_roles_without_agent_imports() -> None:
    tool_record = ToolExecutionRecord(
        name="tool",
        state="completed",
        elapsed_seconds=0.0,
    )

    def project_tool(_message: object) -> ToolExecutionRecord:
        return tool_record

    assert project_agent_message_payload(
        SimpleNamespace(role="user", content=[SimpleNamespace(text="hello")]),
        tool_result_projector=project_tool,
    ) == UserPromptRecord("hello")
    assert project_agent_message_payload(
        SimpleNamespace(role="assistant", content="answer"),
        tool_result_projector=project_tool,
    ) == AssistantMessageRecord("answer", stable=True)
    assert (
        project_agent_message_payload(
            SimpleNamespace(role="toolResult"),
            tool_result_projector=project_tool,
        )
        is tool_record
    )
    assert project_agent_message_payload(
        SimpleNamespace(role="application", content="status", display=True),
        tool_result_projector=project_tool,
    ) == AssistantMessageRecord("status", stable=True)
    assert (
        project_agent_message_payload(
            SimpleNamespace(role="application", content="hidden", display=False),
            tool_result_projector=project_tool,
        )
        is None
    )


def test_command_execution_projector_uses_standard_payload_shape() -> None:
    assert project_command_execution_payload(
        SimpleNamespace(
            command="pytest -q",
            output="passed",
            cancelled=False,
            exit_code=0,
        )
    ) == ToolExecutionRecord(
        name="bash pytest -q",
        state="completed",
        elapsed_seconds=0.0,
        output="passed",
        command="pytest -q",
        exit_code=0,
        stderr="",
    )
    assert (
        project_command_execution_payload(
            SimpleNamespace(command="pytest -q", output="passed")
        )
        is None
    )


def test_importing_history_dispatch_does_not_load_product_or_ai_layers() -> None:
    script = """
import importlib
import sys

importlib.import_module("loushang.harnesstui.conversation.history")

for prefix in ("loushang.agent", "loushang.ai", "loushang.coding"):
    assert not any(
        name == prefix or name.startswith(prefix + ".") for name in sys.modules
    ), prefix
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
