from __future__ import annotations

import subprocess
import sys

import pytest

from loushang.harnesstui.conversation.transcript_display import (
    TranscriptDisplayProjectionProfile,
    compact_absolute_display_paths,
)
from loushang.tui.transcript import ToolExecutionRecord, UserPromptRecord


def test_compact_absolute_display_paths_prefers_cwd_then_home() -> None:
    assert (
        compact_absolute_display_paths(
            "read /home/dev/work/repo/README.md '/home/dev/.config/app.toml' /opt/data",
            cwd="/home/dev/work/repo/",
            home="/home/dev/",
        )
        == "read README.md '~/.config/app.toml' /opt/data"
    )


def test_compact_absolute_display_paths_handles_exact_roots_without_mutating_text() -> (
    None
):
    assert (
        compact_absolute_display_paths(
            "cwd=/workspace/repo home=/home/dev",
            cwd="/workspace/repo",
            home="/home/dev",
        )
        == "cwd=. home=~"
    )
    assert (
        compact_absolute_display_paths(
            "read /workspace/repo/file.py",
            cwd="/",
            home="/",
        )
        == "read /workspace/repo/file.py"
    )


def test_projection_profile_transforms_tool_record_with_injected_policy() -> None:
    calls: list[tuple[str, ...]] = []

    def project_name(name: str, *, context: str) -> str:
        calls.append(("name", name, context))
        return name.replace(context, ".")

    def project_output(
        record: ToolExecutionRecord,
        *,
        projected_name: str,
        context: str,
    ) -> str:
        calls.append(("output", record.output, projected_name, context))
        return record.output.upper()

    profile = TranscriptDisplayProjectionProfile[str](
        project_tool_name=project_name,
        project_tool_output=project_output,
        suppress_duplicate_tool_command=True,
        tool_record_width_inset=2,
    )
    record = ToolExecutionRecord(
        name="bash /repo/check.py",
        state="completed",
        elapsed_seconds=0.5,
        command="  bash   /repo/check.py  ",
        output="passed",
    )

    projected = profile.project_record(record, context="/repo")

    assert isinstance(projected, ToolExecutionRecord)
    assert projected is not record
    assert projected.name == "bash ./check.py"
    assert projected.command == ""
    assert projected.output == "PASSED"
    assert record.command == "  bash   /repo/check.py  "
    assert calls == [
        ("name", "bash /repo/check.py", "/repo"),
        ("output", "passed", "bash ./check.py", "/repo"),
    ]


def test_projection_profile_preserves_identity_when_policy_makes_no_change() -> None:
    profile = TranscriptDisplayProjectionProfile[str](
        project_tool_name=lambda name, *, context: name,
        project_tool_output=lambda record, *, projected_name, context: record.output,
        suppress_duplicate_tool_command=False,
        tool_record_width_inset=0,
    )
    tool = ToolExecutionRecord(
        name="bash",
        state="completed",
        elapsed_seconds=0.0,
        command="bash",
        output="done",
    )
    prompt = UserPromptRecord("hello")

    assert profile.project_record(tool, context="workspace") is tool
    assert profile.project_record(prompt, context="workspace") is prompt


def test_projection_profile_applies_tool_width_inset_only_to_tools() -> None:
    profile = TranscriptDisplayProjectionProfile[str](
        project_tool_name=lambda name, *, context: name,
        project_tool_output=lambda record, *, projected_name, context: record.output,
        suppress_duplicate_tool_command=False,
        tool_record_width_inset=2,
    )
    tool = ToolExecutionRecord(
        name="bash",
        state="completed",
        elapsed_seconds=0.0,
    )
    prompt = UserPromptRecord("hello")

    assert profile.record_render_width(tool, width=80) == 78
    assert profile.record_render_width(tool, width=1) == 1
    assert profile.record_render_width(prompt, width=80) == 80


def test_projection_profile_rejects_negative_tool_width_inset() -> None:
    with pytest.raises(ValueError, match="must be non-negative"):
        TranscriptDisplayProjectionProfile[str](
            project_tool_name=lambda name, *, context: name,
            project_tool_output=lambda record, *, projected_name, context: (
                record.output
            ),
            suppress_duplicate_tool_command=False,
            tool_record_width_inset=-1,
        )


def test_transcript_display_stays_product_neutral_on_fresh_import() -> None:
    script = """
import sys

import loushang.harnesstui.conversation.transcript_display

forbidden_prefixes = (
    "loushang.agent",
    "loushang.ai",
    "loushang.coding",
)
forbidden = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
)
assert forbidden == [], forbidden
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
