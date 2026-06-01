from __future__ import annotations

from pathlib import Path
from typing import Any

import loushang.tui.markdown.renderer as markdown_renderer_module
from loushang.tui import RenderConstraints, strip_control_sequences
from loushang.tui.transcript import (
    AssistantMessageRecord,
    DisplayRecord,
    ErrorRecord,
    ToolExecutionRecord,
    UserPromptRecord,
    WorkedDividerRecord,
)


def _lines(value: Any, *, width: int = 80, height: int = 24) -> list[str]:
    result = value.render(RenderConstraints(width=width, max_height=height, visible_height=height))
    return [strip_control_sequences(line.text) for line in result.lines]


def _raw_lines(value: Any, *, width: int = 80, height: int = 24) -> list[str]:
    result = value.render(RenderConstraints(width=width, max_height=height, visible_height=height))
    return [line.text for line in result.lines]


def test_native_coding_tui_state_commits_turn_without_stale_working() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 13.25,
    )

    app.start_prompt("你好", started_at=10.0)
    app.begin_assistant()
    app.append_assistant_chunk("你好！")
    app.end_assistant()
    app.complete_run(elapsed_seconds=3.25)

    assert app.state.active_started_at is None
    assert [type(record) for record in app.state.records] == [
        UserPromptRecord,
        AssistantMessageRecord,
        WorkedDividerRecord,
    ]

    rendered = "\n".join(_lines(app))
    assert "› 你好" in rendered
    assert "• 你好！" in rendered
    assert "Worked for 3.25s" in rendered
    assert "Working" not in rendered[rendered.rfind("Worked for 3.25s") :]


def test_native_coding_tui_styles_tool_heading_marker_verb_and_flags() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 1.0,
    )
    app.state.records.append(
        ToolExecutionRecord(
            name="git status --short --branch",
            state="completed",
            elapsed_seconds=0.0,
        )
    )

    raw = _raw_lines(app, width=120, height=20)
    line = next(line for line in raw if "git status" in strip_control_sequences(line))

    assert strip_control_sequences(line) == "• Ran git status --short --branch took 0.00s"
    assert "\x1b[1;96m•\x1b[22;39m" in line
    assert "\x1b[1mRan\x1b[22m" in line
    assert "\x1b[96m--short\x1b[39m" in line
    assert "\x1b[96m--branch\x1b[39m" in line
    assert "\x1b[2;90mtook 0.00s\x1b[22;39m" in line


def test_native_coding_tui_compacts_repo_paths_in_tool_heading_only() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    cwd = "/home/dev/workspace/loushang"
    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd=cwd,
        branch="main",
        session_label="abcd1234",
        now=lambda: 1.0,
    )
    record = ToolExecutionRecord(
        name=f"read {cwd}/README.md",
        state="completed",
        elapsed_seconds=0.0,
    )
    app.state.records.append(record)

    line = next(line for line in _lines(app, width=120, height=20) if "Ran read" in line)

    assert line == "• Ran read README.md took 0.00s"
    assert record.name == f"read {cwd}/README.md"


def test_native_coding_tui_compacts_home_paths_in_tool_heading_only() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    home = str(Path.home())
    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd=f"{home}/workspace/loushang",
        branch="main",
        session_label="abcd1234",
        now=lambda: 1.0,
    )
    record = ToolExecutionRecord(
        name=f"read {home}/.config/loushang/config.toml",
        state="completed",
        elapsed_seconds=0.0,
    )
    app.state.records.append(record)

    line = next(line for line in _lines(app, width=120, height=20) if "Ran read" in line)

    assert line == "• Ran read ~/.config/loushang/config.toml took 0.00s"
    assert record.name == f"read {home}/.config/loushang/config.toml"


def test_native_coding_tui_keeps_tool_command_and_output_paths_uncompacted() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    cwd = "/home/dev/workspace/loushang"
    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd=cwd,
        branch="main",
        session_label="abcd1234",
        now=lambda: 1.0,
    )
    app.state.records.append(
        ToolExecutionRecord(
            name=f"bash {cwd}/scripts/check.py",
            state="completed",
            elapsed_seconds=0.0,
            command=f"python {cwd}/scripts/check.py",
            output=f"{cwd}/README.md",
        )
    )

    plain = tuple(_lines(app, width=120, height=20))

    assert "• Ran bash scripts/check.py took 0.00s" in plain
    assert f"  │ $ python {cwd}/scripts/check.py" in plain
    assert f"  └ {cwd}/README.md" in plain


def test_native_coding_tui_styles_error_records_red() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 1.0,
    )
    app.state.records.append(ErrorRecord("provider failed"))

    raw = _raw_lines(app, width=120, height=20)
    line = next(line for line in raw if "provider failed" in strip_control_sequences(line))

    assert strip_control_sequences(line) == "■ Error: provider failed"
    assert line.startswith("\x1b[31m■ Error: provider failed\x1b[39m")


def test_native_coding_tui_styles_tool_connectors_and_metadata() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 1.0,
    )
    app.state.records.append(
        ToolExecutionRecord(
            name="git add src/loushang",
            state="completed",
            elapsed_seconds=0.0,
            output="(no output)\n… +4 lines",
        )
    )

    raw = _raw_lines(app, width=120, height=20)
    connector_line = next(line for line in raw if "(no output)" in strip_control_sequences(line))
    collapsed_line = next(line for line in raw if "+4 lines" in strip_control_sequences(line))

    assert strip_control_sequences(connector_line) == "  └ (no output)"
    assert "\x1b[2;90m└\x1b[22;39m" in connector_line
    assert "\x1b[2;90m(no output)\x1b[22;39m" in connector_line
    assert strip_control_sequences(collapsed_line) == "    … +4 lines"
    assert "\x1b[2;90m… +4 lines\x1b[22;39m" in collapsed_line


def test_native_coding_tui_styles_tool_activity_actions() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 1.0,
    )
    app.state.records.append(
        ToolExecutionRecord(
            name="search workspace",
            state="completed",
            elapsed_seconds=0.0,
            output="Read theme.py\nSearch transcript in src/loushang/tui",
        )
    )

    raw = _raw_lines(app, width=120, height=20)
    read_line = next(line for line in raw if "Read theme.py" in strip_control_sequences(line))
    search_line = next(line for line in raw if "Search transcript" in strip_control_sequences(line))

    assert strip_control_sequences(read_line) == "  └ Read theme.py"
    assert "\x1b[96mRead\x1b[39m" in read_line
    assert strip_control_sequences(search_line) == "    Search transcript in src/loushang/tui"
    assert "\x1b[96mSearch\x1b[39m" in search_line


def test_native_coding_tui_structures_tool_command_and_output_body() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 1.0,
    )
    app.state.records.append(
        ToolExecutionRecord(
            name="bash git status",
            state="completed",
            elapsed_seconds=0.6,
            command="bash git status",
            output=(
                "... (6 earlier lines)\n"
                "\tdocs/product-definition-draft.md\n"
                "\tdocs/product-definition-presentation.md\n"
                "\n"
                'nothing added to commit but untracked files present (use "git add" to track)\n'
                "Took 0.6s"
            ),
        )
    )

    raw = _raw_lines(app, width=120, height=20)
    plain = tuple(strip_control_sequences(line) for line in raw)

    assert "  │ $ bash git status" not in plain
    assert "  └ ... (6 earlier lines)" in plain
    assert '    nothing added to commit but untracked files present (use "git add" to track)' in plain
    assert "    Took 0.6s" not in plain

    collapsed_line = next(line for line in raw if "earlier lines" in strip_control_sequences(line))
    nothing_line = next(line for line in raw if "nothing added" in strip_control_sequences(line))

    assert "\x1b[2;90m└\x1b[22;39m" in collapsed_line
    assert "\x1b[2;90m... (6 earlier lines)\x1b[22;39m" in collapsed_line
    assert "\x1b[2;90mnothing added to commit but untracked files present" in nothing_line


def test_native_coding_tui_summarizes_long_tool_output_with_head_and_tail() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 1.0,
    )
    app.state.records.append(
        ToolExecutionRecord(
            name="bash pytest tests/coding -q",
            state="completed",
            elapsed_seconds=0.6,
            output="\n".join(f"line {index}" for index in range(1, 13)),
        )
    )

    raw = _raw_lines(app, width=120, height=20)
    plain = tuple(strip_control_sequences(line) for line in raw)

    assert "  └ line 1" in plain
    assert "    line 2" in plain
    assert "    line 3" in plain
    assert "    ... (6 hidden lines)" in plain
    assert "    line 10" in plain
    assert "    line 11" in plain
    assert "    line 12" in plain
    assert "    line 4" not in plain
    assert "    line 9" not in plain

    collapsed_line = next(line for line in raw if "hidden lines" in strip_control_sequences(line))
    assert "\x1b[2;90m... (6 hidden lines)\x1b[22;39m" in collapsed_line


def test_native_coding_tui_keeps_restyled_tool_output_within_screen_width() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 1.0,
    )
    full_width_content = "z" * 98
    app.state.records.append(
        ToolExecutionRecord(
            name="bash cat long-output.txt",
            state="completed",
            elapsed_seconds=0.1,
            output=f"{full_width_content}\n{full_width_content}",
        )
    )
    constraints = RenderConstraints(width=100, max_height=20, visible_height=20)

    result = app.render(constraints)
    result.validate(constraints)
    plain = tuple(strip_control_sequences(line.text) for line in result.lines)

    assert sum(line.count("z") for line in plain) == 196


def test_native_coding_tui_does_not_shred_long_tool_output_paths() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 1.0,
    )
    app.state.records.append(
        ToolExecutionRecord(
            name="bash find docs",
            state="completed",
            elapsed_seconds=0.1,
            output=(
                "docs/superpowers/specs/"
                "2026-05-19-loushang-coding-tools-substrate-hardening-and-pi-aligned-file-tool-semantics-design.md"
            ),
        )
    )

    plain = tuple(strip_control_sequences(line.text) for line in app.render(RenderConstraints(width=100, max_height=20)).lines)

    assert "    t" not in plain
    assert "    -tool-semantics-design.md" in plain


def test_native_coding_tui_keeps_non_duplicate_tool_command_detail() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 1.0,
    )
    app.state.records.append(
        ToolExecutionRecord(
            name="bash",
            state="completed",
            elapsed_seconds=0.6,
            command="git status",
            output="clean",
        )
    )

    raw = _raw_lines(app, width=120, height=20)
    command_line = next(line for line in raw if "$ git status" in strip_control_sequences(line))

    assert strip_control_sequences(command_line) == "  │ $ git status"
    assert "\x1b[2;90m│\x1b[22;39m" in command_line


def test_native_coding_tui_styles_worked_divider_as_dim_neutral() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 1.0,
    )
    app.state.records.append(WorkedDividerRecord(elapsed_seconds=1.0))

    raw = _raw_lines(app, width=80, height=20)
    line = next(line for line in raw if "Worked for" in strip_control_sequences(line))

    assert strip_control_sequences(line).startswith("─ Worked for 1.00s ")
    assert line.startswith("\x1b[2;90m─ Worked for 1.00s ")
    assert line.endswith("\x1b[22;39m")


def test_native_coding_tui_app_requests_stream_render_for_assistant_chunks() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    requested: list[str] = []
    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        render_requester=requested.append,
    )

    app.begin_assistant()
    app.append_assistant_chunk("hello")

    assert requested[-1] == "stream"


def test_native_coding_tui_keeps_unsubmitted_draft_in_composer_only() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 2.0,
    )
    app.start_prompt("你好", started_at=0.0)
    app.begin_assistant()
    app.append_assistant_chunk("收到")
    app.end_assistant("收到")
    app.complete_run(elapsed_seconds=2.0)

    app.composer.set_text("你")
    rendered = _lines(app)

    assert sum(1 for line in rendered if line == "› 你") == 1
    assert [record.text for record in app.state.records if isinstance(record, UserPromptRecord)] == ["你好"]


def test_native_coding_tui_pending_sections_follow_working_line() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 11.5,
    )
    app.start_prompt("当前代码有啥？", started_at=10.0)
    app.queue_steer("你好")
    app.queue_followup("你是谁")

    rendered = _lines(app, width=140, height=18)
    working_index = next(index for index, line in enumerate(rendered) if "Working 1.50s" in line)
    steer_index = rendered.index("• Messages to be submitted after next tool call (press esc to interrupt and send immediately)")
    followup_index = rendered.index("• Queued follow-up inputs")
    composer_index = rendered.index("› ")

    assert working_index < steer_index < followup_index < composer_index
    assert "  ↳ 你好" in rendered
    assert "  ↳ 你是谁" in rendered
    assert "    alt + ↑ edit last queued message" in rendered


def test_native_coding_tui_requests_animation_frames_while_running() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp
    from loushang.tui import FakeTerminalPort, RenderLoop, TerminalSize, TuiRuntime

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    runtime = TuiRuntime(
        render_loop=RenderLoop(app),
        terminal=FakeTerminalPort(size=TerminalSize(columns=80, rows=24)),
        now_ms=lambda: 1_000,
    )

    runtime.render_now()
    assert runtime.request_next_animation_frame().delay_ms == 0

    app.start_prompt("你好", started_at=10.0)
    runtime.render_now()
    decision = runtime.request_next_animation_frame()

    assert decision.coalesced is True
    assert decision.delay_ms > 0


def test_native_coding_tui_reuses_stable_transcript_render_cache() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.start_prompt("first", started_at=0.0)
    app.begin_assistant()
    app.append_assistant_chunk("stable **markdown** response")
    app.end_assistant()
    app.complete_run(elapsed_seconds=1.0)
    app.start_prompt("second", started_at=9.0)

    _lines(app)
    cached = dict(app._transcript_region._stable_line_cache)
    _lines(app)

    assert cached
    assert app._transcript_region._stable_line_cache == cached


def test_native_coding_tui_reuses_unchanged_streaming_draft_cache() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.start_prompt("stream", started_at=9.0)
    app.begin_assistant()
    app.append_assistant_chunk("draft **markdown** response")

    _lines(app)
    first_cached = app._transcript_region._transient_line_cache_lines
    _lines(app)

    assert first_cached is not None
    assert app._transcript_region._transient_line_cache_lines is first_cached


def test_native_coding_tui_reuses_stable_streaming_markdown_blocks(monkeypatch) -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    rendered_code_blocks: list[tuple[str, ...]] = []
    original = markdown_renderer_module._render_markdown_block

    def render_markdown_block(
        block: markdown_renderer_module._MarkdownBlock,
        **kwargs: Any,
    ) -> tuple[str, ...]:
        if block.kind == "code":
            rendered_code_blocks.append(block.lines)
        return original(block, **kwargs)

    monkeypatch.setattr(markdown_renderer_module, "_render_markdown_block", render_markdown_block)

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.start_prompt("stream", started_at=9.0)
    app.begin_assistant()
    app.append_assistant_chunk("Intro\n\n```python\nprint('stable')\n```\n\nTail")

    _lines(app, width=80, height=100)
    app.append_assistant_chunk(" grows")
    _lines(app, width=80, height=100)

    assert rendered_code_blocks == [
        ("print('stable')",),
    ]


def test_native_coding_tui_rerenders_current_streaming_table_block(monkeypatch) -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    rendered_tables = 0
    original = markdown_renderer_module._render_markdown_block

    def render_markdown_block(
        block: markdown_renderer_module._MarkdownBlock,
        **kwargs: Any,
    ) -> tuple[str, ...]:
        nonlocal rendered_tables
        if block.kind == "table":
            rendered_tables += 1
        return original(block, **kwargs)

    monkeypatch.setattr(markdown_renderer_module, "_render_markdown_block", render_markdown_block)

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.start_prompt("stream table", started_at=9.0)
    app.begin_assistant()
    app.append_assistant_chunk("| A | B |\n|---|---|\n| 1 | 2 |\n")

    _lines(app, width=80, height=100)
    app.append_assistant_chunk("| 3 | 4 |\n")
    _lines(app, width=80, height=100)
    app.append_assistant_chunk("\nDone")
    _lines(app, width=80, height=100)
    app.append_assistant_chunk(" now")
    _lines(app, width=80, height=100)

    assert rendered_tables == 3


def test_native_coding_tui_clears_transient_draft_cache_after_assistant_commit() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.start_prompt("stream", started_at=9.0)
    app.begin_assistant()
    app.append_assistant_chunk("draft **markdown** response")

    _lines(app)
    assert app._transcript_region._transient_line_cache_lines is not None

    app.end_assistant()

    assert app._transcript_region._transient_line_cache_key is None
    assert app._transcript_region._transient_line_cache_lines is None


def test_native_coding_tui_promotes_streaming_draft_cache_after_assistant_commit() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.start_prompt("stream", started_at=9.0)
    app.begin_assistant()
    app.append_assistant_chunk("\n".join(f"- **Line {line}**: `code-{line}`" for line in range(100)))

    _lines(app, width=100, height=1_000)
    transient_lines = app._transcript_region._transient_line_cache_lines
    assert transient_lines is not None

    app.end_assistant()

    assert transient_lines in app._transcript_region._stable_line_cache.values()
    assert app._transcript_region._transient_line_cache_lines is None


def test_native_coding_tui_complete_run_does_not_trim_active_transcript_line_window() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
        active_transcript_line_budget=55,
    )
    for turn in range(4):
        app.start_prompt(f"turn {turn}", started_at=float(turn))
        app.begin_assistant()
        app.append_assistant_chunk("\n".join(f"turn {turn} line {line}" for line in range(40)))
        app.end_assistant()
        app.complete_run(elapsed_seconds=1.0)

    rendered_lines = _lines(app, width=100, height=1_000)
    rendered = "\n".join(rendered_lines)

    assert app.state.evicted_prefix_record_count == 0
    assert app.consume_render_baseline_reset_reason() is None
    assert "turn 3 line 39" in rendered
    assert "turn 0 line 0" in rendered


def test_native_coding_tui_explicit_active_window_trim_keeps_recent_tail() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
        active_transcript_line_budget=55,
    )
    for turn in range(4):
        app.start_prompt(f"turn {turn}", started_at=float(turn))
        app.begin_assistant()
        app.append_assistant_chunk("\n".join(f"turn {turn} line {line}" for line in range(40)))
        app.end_assistant()
        app.complete_run(elapsed_seconds=1.0)

    app.trim_active_transcript_window()
    rendered_lines = _lines(app, width=100, height=1_000)
    rendered = "\n".join(rendered_lines)

    assert app.state.evicted_prefix_record_count > 0
    assert len(rendered_lines) <= 90
    assert "turn 3 line 39" in rendered
    assert "turn 0 line 0" not in rendered


def test_native_coding_tui_streaming_draft_render_keeps_full_append_stable_lines() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.start_prompt("stream", started_at=9.0)
    app.begin_assistant()
    app.append_assistant_chunk("\n".join(f"draft line {line}" for line in range(200)))

    rendered_lines = _lines(app, width=100, height=1_000)
    rendered = "\n".join(rendered_lines)

    assert len(app._transcript_region._transient_line_cache_lines or ()) >= 200
    assert "draft line 199" in rendered
    assert "draft line 0" in rendered


def test_native_coding_tui_streaming_draft_uses_markdown_visuals_for_append_chunks() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.start_prompt("stream", started_at=9.0)
    app.begin_assistant()
    app.append_assistant_chunk("- **Line 1**: markdown `code-1` with [link 1](https://example.com/1).\n")
    app.append_assistant_chunk("- **Line 2**: markdown `code-2` with [link 2](https://example.com/2).\n")

    rendered = "\n".join(_lines(app, width=100, height=1_000))

    assert "Line 1: markdown code-1 with link 1 (https://example.com/1)." in rendered
    assert "Line 2: markdown code-2 with link 2 (https://example.com/2)." in rendered
    assert "**Line" not in rendered
    assert "`code-" not in rendered
    assert "[link " not in rendered


def test_native_coding_tui_assistant_markdown_tables_use_block_renderer() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.start_prompt("show table", started_at=9.0)
    app.begin_assistant()
    app.append_assistant_chunk(
        "| 模块 | 功能 |\n"
        "|---|---|\n"
        "| ai/provider/ | Provider 抽象协议 |\n"
        "| ai/tool/ | 工具 Schema 转换 |\n"
    )
    app.end_assistant()
    app.complete_run(elapsed_seconds=1.0)

    rendered = "\n".join(_lines(app, width=100, height=1_000))

    assert "ai/provider/" in rendered
    assert "Provider 抽象协议" in rendered
    assert "┌" in rendered
    assert "├" in rendered
    assert "└" in rendered
    assert "|---|---|" not in rendered


def test_native_coding_tui_code_diagrams_do_not_wrap_right_border_with_default_width() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.begin_assistant()
    app.append_assistant_chunk(
        "```\n"
        "  ┌─────────────────────────────────────────────────────────┐\n"
        "  │  loushang-coding  (产品装配层 - CLI/TUI/Workflow)        │\n"
        "  └─────────────────────────────────────────────────────────┘\n"
        "```"
    )

    lines = _lines(app, width=66, height=1_000)
    coding_line = next(line for line in lines if "loushang-coding" in line)

    assert coding_line.endswith("│")
    assert all(line.strip() != "│" for line in lines)


def test_native_coding_tui_streaming_draft_buffers_chunks_until_materialized() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.start_prompt("stream", started_at=9.0)
    app.begin_assistant()

    for index in range(10):
        app.append_assistant_chunk(f"- Line {index}: chunk\n")

    buffer = app.state._assistant_draft_buffer
    assert buffer is not None
    assert buffer.chunk_count == 10
    assert buffer.materialize_count == 0

    draft = app.state.assistant_draft

    assert draft is not None
    assert "- Line 9: chunk" in draft.text
    assert buffer.materialize_count == 1

    app.end_assistant()

    assert app.state._assistant_draft_buffer is None
    assert isinstance(app.state.records[-1], AssistantMessageRecord)
    assert "- Line 9: chunk" in app.state.records[-1].text


def test_native_coding_tui_render_streaming_draft_without_materializing_full_text() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.start_prompt("stream", started_at=9.0)
    app.begin_assistant()
    for index in range(25):
        app.append_assistant_chunk(f"- Line {index}: chunk\n")

    buffer = app.state._assistant_draft_buffer
    assert buffer is not None
    assert buffer.materialize_count == 0

    rendered = "\n".join(_lines(app, width=100, height=1_000))

    assert "Line 24: chunk" in rendered
    assert buffer.materialize_count == 0


def test_native_coding_tui_stable_render_cache_has_entry_limit() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
        stable_render_cache_entry_limit=2,
    )
    app.state.records.extend(AssistantMessageRecord(f"stable record {index}") for index in range(5))

    _lines(app, width=100, height=1_000)

    assert len(app._transcript_region._stable_line_cache) <= 2


def test_native_coding_tui_long_stream_keeps_latest_tail_visible() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.start_prompt("stream", started_at=9.0)
    app.begin_assistant()
    app.append_assistant_chunk("\n".join(f"line {index}" for index in range(1_100)))

    rendered = _lines(app, width=80, height=24)

    assert any("line 1099" in line for line in rendered)
    assert not any("line 0" in line for line in rendered)


def test_native_coding_tui_many_records_render_recent_tail_not_prefix() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.state.records.extend(UserPromptRecord(f"old prompt {index}") for index in range(200))
    app.state.records.append(UserPromptRecord("recent prompt"))
    app.state.records.append(AssistantMessageRecord("recent answer"))

    rendered = "\n".join(_lines(app, width=100, height=18))

    assert "old prompt 0" not in rendered
    assert "› recent prompt" in rendered
    assert "• recent answer" in rendered


def test_native_coding_tui_default_terminal_theme_styles_headings_like_pi() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.start_prompt("headings", started_at=9.0)
    app.begin_assistant()
    app.append_assistant_chunk("### 5. 生命周期阶段\n\n#### Dual Mode")

    raw = _raw_lines(app, width=100, height=32)
    heading = next(line for line in raw if "生命周期阶段" in strip_control_sequences(line))
    subheading = next(line for line in raw if "Dual Mode" in strip_control_sequences(line))

    assert strip_control_sequences(heading) == "• ### 5. 生命周期阶段"
    assert strip_control_sequences(subheading) == "  #### Dual Mode"
    assert heading.startswith("• \x1b[")
    assert "\x1b[1;" in heading
    assert "\x1b[1;33m" in heading
    assert "\x1b[1;" in subheading


def test_native_coding_tui_default_welcome_panel_is_colored() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )

    raw = tuple(line.text for line in app.startup_welcome_panel().render(RenderConstraints(width=96, max_height=28)).lines)
    rendered = "\n".join(raw)

    assert "\x1b[90m╭──\x1b[39m" in raw[0]
    assert "\x1b[1;36m Loushang \x1b[22;39m" in raw[0]
    assert "\x1b[1;30m欲穷千里目，更上一层楼\x1b[22;39m" in rendered
    assert "\x1b[94mFrom Loushang's height, farther horizons unfold.\x1b[39m" in rendered
    assert "\x1b[1;30mWelcome to Loushang CLI\x1b[22;39m" in rendered
    assert "\x1b[1;30m   o\x1b[22;39m" in rendered
    assert "\x1b[36m   ▀██▀" in rendered


def test_native_coding_tui_preserves_markdown_ansi_when_replacing_assistant_prefix() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp
    from loushang.tui.theme import ThemeResolver

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
        transcript_theme=ThemeResolver(defaults={"markdown.heading.level3": {"bold": True, "color": "cyan"}}),
    )
    app.start_prompt("headings", started_at=9.0)
    app.begin_assistant()
    app.append_assistant_chunk("### Heading")

    raw = _raw_lines(app, width=80, height=32)
    heading = next(line for line in raw if "Heading" in strip_control_sequences(line))

    assert strip_control_sequences(heading) == "• ### Heading"
    assert heading.startswith("• \x1b[")
    assert "\x1b[1;36m### Heading" in heading


def test_native_coding_tui_installs_active_transcript_window_without_rendering_evicted_prefix() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    evicted_prefix = [UserPromptRecord(f"old prompt {index}") for index in range(200)]
    active_window: list[DisplayRecord] = [
        AssistantMessageRecord("Compacted summary: older turns are outside the active UI window."),
        UserPromptRecord("recent prompt"),
        AssistantMessageRecord("recent answer"),
    ]

    app.replace_transcript_window(
        active_window,
        evicted_prefix_record_count=len(evicted_prefix),
        reason="compaction",
    )
    rendered = "\n".join(_lines(app, width=100, height=24))

    assert app.state.evicted_prefix_record_count == 200
    assert app.state.records == active_window
    assert "Compacted summary" in rendered
    assert "› recent prompt" in rendered
    assert "• recent answer" in rendered
    assert "old prompt" not in rendered


def test_native_coding_tui_runtime_consumes_transcript_window_reset_as_baseline_repaint() -> None:
    from loushang.coding.ui.native_app import NativeCodingTuiApp
    from loushang.tui import FakeTerminalPort, RenderLoop, TerminalSize, TuiRuntime

    app = NativeCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="abcd1234",
        now=lambda: 10.0,
    )
    app.start_prompt("old prompt", started_at=1.0)
    app.begin_assistant()
    app.append_assistant_chunk("old answer")
    app.end_assistant()
    app.complete_run(elapsed_seconds=1.0)
    runtime = TuiRuntime(
        render_loop=RenderLoop(app, clear_scrollback_policy="disabled"),
        terminal=FakeTerminalPort(size=TerminalSize(columns=80, rows=24)),
    )
    runtime.render_now()

    app.replace_transcript_window(
        [
            AssistantMessageRecord("summary only"),
            UserPromptRecord("recent prompt"),
        ],
        evicted_prefix_record_count=2,
        reason="compaction",
    )
    step = runtime.render_now()

    step.assert_operation_class("baseline_repaint")
    step.assert_no_clear_scrollback()
    assert step.diagnostics.repaint_reason == "transcript_window_replaced:compaction"
    rendered = "\n".join(step.diagnostics.current_logical_lines)
    assert "old prompt" not in rendered
    assert "summary only" in rendered
