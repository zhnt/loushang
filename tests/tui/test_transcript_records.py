from __future__ import annotations

import pytest

import loushang.tui.transcript as transcript_module
from loushang.tui import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    ErrorRecord,
    RenderConstraints,
    StatusRecord,
    TerminalCapabilities,
    ThemeResolver,
    ThinkingRecord,
    ThinkingVisibility,
    ToolExecutionRecord,
    TranscriptBuffer,
    TranscriptView,
    UserPromptRecord,
    WorkedDividerRecord,
    render_transcript_records,
    strip_control_sequences,
)

pytestmark = pytest.mark.tui_render_contract


def rendered_text(view: TranscriptView, *, width: int = 60, height: int = 20) -> tuple[str, ...]:
    result = view.render(RenderConstraints(width=width, max_height=height))
    return tuple(line.text for line in result.lines)


def test_assistant_streaming_chunks_update_one_draft_until_commit() -> None:
    transcript = TranscriptBuffer()
    transcript.append(UserPromptRecord(text="hello"))

    transcript.append_assistant_chunk("Hel")
    transcript.append_assistant_chunk("lo")

    assert transcript.records == (UserPromptRecord(text="hello"),)
    assert transcript.assistant_draft == AssistantMessageRecord(text="Hello", stable=False)
    assert rendered_text(TranscriptView(transcript.records, draft=transcript.assistant_draft)) == (
        "> hello",
        "* Hello",
    )

    transcript.commit_assistant()

    assert transcript.assistant_draft is None
    assert transcript.records == (
        UserPromptRecord(text="hello"),
        AssistantMessageRecord(text="Hello", stable=True),
    )


def test_transcript_buffer_streaming_draft_buffers_chunks_until_materialized() -> None:
    transcript = TranscriptBuffer()

    for index in range(5):
        transcript.append_assistant_chunk(f"chunk {index}\n")

    buffer = transcript._assistant_draft_buffer
    assert buffer is not None
    assert buffer.chunk_count == 5
    assert buffer.materialize_count == 0

    assert transcript.assistant_draft == AssistantMessageRecord(
        text="chunk 0\nchunk 1\nchunk 2\nchunk 3\nchunk 4\n",
        stable=False,
    )
    assert buffer.materialize_count == 1

    transcript.commit_assistant()

    assert transcript.assistant_draft is None
    assert transcript.records == (
        AssistantMessageRecord(
            text="chunk 0\nchunk 1\nchunk 2\nchunk 3\nchunk 4\n",
            stable=True,
        ),
    )


def test_worked_divider_commits_as_stable_transcript_record() -> None:
    view = TranscriptView([WorkedDividerRecord(elapsed_seconds=95.4)])

    assert rendered_text(view, width=30) == ("- Worked for 1m 35.40s ------",)


def test_context_compaction_record_renders_as_single_stable_transcript_line() -> None:
    view = TranscriptView(
        [
            ContextCompactionRecord(
                summary="older context\nsummarized",
                tokens_before=500_000,
            )
        ]
    )

    lines = rendered_text(view, width=80)

    assert lines == ("* Context compacted (500000 tokens before)",)
    assert all("\n" not in line and "\r" not in line for line in lines)


def test_status_record_renders_message_without_thinking_prefix() -> None:
    view = TranscriptView([StatusRecord("Active tools: read, ls, find, grep, bash, edit, write")])

    assert rendered_text(view, width=80) == ("Active tools: read, ls, find, grep, bash, edit, write",)


def test_tool_execution_records_have_running_elapsed_and_completed_took_markers() -> None:
    view = TranscriptView(
        [
            ToolExecutionRecord(name="git status", state="running", elapsed_seconds=1.234),
            ToolExecutionRecord(name="pytest", state="completed", elapsed_seconds=2.0, output="3 passed"),
        ]
    )

    assert rendered_text(view, width=40) == (
        "- Ran git status 1.23s",
        "- Ran pytest took 2.00s",
        "  3 passed",
    )


def test_thinking_visibility_policy_never_invents_hidden_reasoning() -> None:
    visible = TranscriptView([ThinkingRecord(text="checking files", visibility=ThinkingVisibility.VISIBLE)])
    collapsed = TranscriptView([ThinkingRecord(text="checking files", visibility=ThinkingVisibility.COLLAPSED)])
    hidden = TranscriptView([ThinkingRecord(text="checking files", visibility=ThinkingVisibility.HIDDEN)])
    unavailable = TranscriptView([ThinkingRecord(text="", visibility=ThinkingVisibility.UNAVAILABLE)])

    assert rendered_text(visible) == ("? thinking: checking files",)
    assert rendered_text(collapsed) == ("? thinking collapsed",)
    assert rendered_text(hidden) == ()
    assert rendered_text(unavailable) == ("? thinking unavailable",)


def test_error_record_hides_diagnostics_unless_verbose_enabled() -> None:
    record = ErrorRecord(summary="Request failed", diagnostics="Traceback: details")

    assert rendered_text(TranscriptView([record], verbose_errors=False)) == ("! Error: Request failed",)
    assert rendered_text(TranscriptView([record], verbose_errors=True)) == (
        "! Error: Request failed",
        "  Traceback: details",
    )


def test_transcript_view_reuses_rendered_record_lines_for_same_width(monkeypatch) -> None:
    calls: list[object] = []

    def render_record(record: object, *, width: int, verbose_errors: bool, **_kwargs: object) -> list[str]:
        calls.append((record, width, verbose_errors))
        return [f"rendered:{len(calls)}"]

    monkeypatch.setattr(transcript_module, "_render_record", render_record)
    view = TranscriptView([UserPromptRecord("hello"), AssistantMessageRecord("world")])

    assert rendered_text(view, width=40) == ("rendered:1", "rendered:2")
    assert rendered_text(view, width=40) == ("rendered:1", "rendered:2")
    assert len(calls) == 2

    assert rendered_text(view, width=20) == ("rendered:3", "rendered:4")
    assert len(calls) == 4


def test_transcript_view_reuses_stable_record_lines_while_draft_changes(monkeypatch) -> None:
    calls: list[object] = []

    def render_record(record: object, *, width: int, verbose_errors: bool, **_kwargs: object) -> list[str]:
        calls.append((record, width, verbose_errors))
        return [f"rendered:{len(calls)}"]

    monkeypatch.setattr(transcript_module, "_render_record", render_record)
    stable = UserPromptRecord("hello")
    view = TranscriptView([stable], draft=AssistantMessageRecord("chunk 1", stable=False))

    assert rendered_text(view, width=40) == ("rendered:1", "rendered:2")
    view.draft = AssistantMessageRecord("chunk 1 chunk 2", stable=False)

    assert rendered_text(view, width=40) == ("rendered:1", "rendered:3")
    assert calls == [
        (stable, 40, False),
        (AssistantMessageRecord("chunk 1", stable=False), 40, False),
        (AssistantMessageRecord("chunk 1 chunk 2", stable=False), 40, False),
    ]


def test_render_transcript_records_matches_transcript_view_output() -> None:
    records = (
        UserPromptRecord("hello"),
        AssistantMessageRecord("world"),
    )

    lines = render_transcript_records(records, width=40, max_height=20)

    assert tuple(line.text for line in lines) == rendered_text(TranscriptView(records), width=40, height=20)


def test_transcript_view_can_render_assistant_markdown_with_content_theme() -> None:
    theme = ThemeResolver(
        defaults={
            "markdown.heading.level2": {"color": "cyan"},
            "markdown.inline_code": {"color": "yellow"},
        }
    )
    view = TranscriptView(
        [AssistantMessageRecord("## Result\nUse `pytest` now.")],
        theme=theme,
        capabilities=TerminalCapabilities(hyperlinks=True),
    )

    lines = rendered_text(view, width=50, height=10)

    assert tuple(strip_control_sequences(line) for line in lines) == (
        "* Result",
        "",
        "  Use pytest now.",
    )
    assert lines[0].startswith("* \x1b[1;36mResult")
    assert "\x1b[33mpytest\x1b[39m" in lines[2]


def test_transcript_tool_output_can_use_diff_and_code_content_renderers() -> None:
    theme = ThemeResolver(
        defaults={
            "diff.addition": {"color": "green"},
            "diff.deletion": {"color": "red"},
            "markdown.code.block.border": {"color": "bright_black"},
            "markdown.code.block": {"color": 252},
        }
    )
    view = TranscriptView(
        [
            ToolExecutionRecord("apply_patch", "completed", 1.2, "-old\n+new", output_kind="diff"),
            ToolExecutionRecord("python", "completed", 0.5, "print('ok')", output_kind="code", language="python"),
        ],
        theme=theme,
    )

    lines = rendered_text(view, width=60, height=20)

    assert tuple(strip_control_sequences(line) for line in lines) == (
        "- Ran apply_patch took 1.20s",
        "  -old",
        "  +new",
        "- Ran python took 0.50s",
        "  ```python",
        "    print('ok')",
        "  ```",
    )
    assert lines[1].startswith("  \x1b[31m-old")
    assert lines[2].startswith("  \x1b[32m+new")
    assert lines[4].startswith("  \x1b[90m```python")


def test_transcript_tool_record_renders_command_stderr_exit_and_diff_stats() -> None:
    theme = ThemeResolver(
        defaults={
            "diff.summary": {"bold": True, "color": "magenta"},
            "diff.addition": {"color": "green"},
            "diff.deletion": {"color": "red"},
        }
    )
    view = TranscriptView(
        [
            ToolExecutionRecord(
                "apply_patch",
                "failed",
                2.5,
                "-old\n+new",
                output_kind="diff",
                command="apply_patch < patch.diff",
                stderr="patch failed",
                exit_code=1,
                show_stats=True,
            ),
            ToolExecutionRecord("pytest", "cancelled", 1.25),
        ],
        theme=theme,
    )

    lines = rendered_text(view, width=60, height=20)

    assert tuple(strip_control_sequences(line) for line in lines) == (
        "! Ran apply_patch failed after 2.50s",
        "  $ apply_patch < patch.diff",
        "  Diff +1 -1",
        "  -old",
        "  +new",
        "  stderr: patch failed",
        "  exit code: 1",
        "! Ran pytest cancelled after 1.25s",
    )
    assert lines[2].startswith("  \x1b[1;35mDiff +1 -1")
    assert lines[4].startswith("  \x1b[32m+new")
