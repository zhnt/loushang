from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

from loushang.coding.ui.product_binding import build_coding_ui_controller
from loushang.harnesstui.testing.performance import (
    build_synthetic_long_transcript_records,
)
from loushang.harnesstui.testing.scenarios.transcript import (
    TranscriptScenarioFixtures,
    transcript_scenarios,
)
from loushang.tui.playback_suite import PlaybackScenarioSpec
from loushang.tui.transcript import (
    AssistantMessageRecord,
    DisplayRecord,
    ToolExecutionRecord,
)
from tests.coding.tui_support.action_host import (
    coding_screen_prompt_handler,
)
from tests.coding.tui_support.playback import ScreenTuiLoopPlayback
from tests.coding.tui_support.scenario_binding import (
    CODING_SCENARIO_FACTORY,
    CODING_SCENARIO_FRAME_CONTRACTS,
)


def _coding_long_transcript_records() -> tuple[DisplayRecord, ...]:
    return build_synthetic_long_transcript_records(
        turns=40,
        tail_tool_output_lines=300,
    )


def _coding_tool_output_records() -> tuple[DisplayRecord, ...]:
    return (
        ToolExecutionRecord(
            name="bash pytest tests/coding -q",
            state="completed",
            elapsed_seconds=0.6,
            output="\n".join(f"line {index}" for index in range(1, 13)),
        ),
    )


_CODING_TRANSCRIPT_FIXTURES = TranscriptScenarioFixtures(
    long_transcript_records=_coding_long_transcript_records,
    tool_output_records=_coding_tool_output_records,
    long_transcript_anchor="›",
    tool_preview_visible=(
        "  └ line 1",
        "    line 3",
        "    ... (6 hidden lines)",
        "    line 12",
    ),
    tool_preview_hidden=("    line 4", "    line 9"),
)


def _run_transcript_reader_copy_command() -> object:
    playback = ScreenTuiLoopPlayback(width=72, height=9)
    playback.app.state.records.extend(
        (
            AssistantMessageRecord("reader-visible latest answer"),
            AssistantMessageRecord("reader-visible older answer"),
        )
    )
    session = _CopyCommandPlaybackSession(
        recent_texts=(
            "latest structured answer",
            "previous structured answer",
        )
    )
    controller = build_coding_ui_controller(session=session)

    result = playback.run(
        (0.00, "\x0f"),
        (0.01, "\x02"),
        (0.02, "\x0f"),
        (0.03, "/copy 2\r"),
        (0.05, ""),
        handle_prompt=coding_screen_prompt_handler(
            presenter=playback.app,
            controller=controller,
            stderr=StringIO(),
            verbose=False,
        ),
    )

    result.assert_exit_code(0)
    result.assert_text_contains("Transcript window")
    result.assert_text_contains("Ctrl+O/q/Esc close")
    result.assert_text_contains("Copied /copy 2 from structured source.")
    result.assert_no_clear_screen()
    assert session.commands == [("copy", "2")]
    assert session.prompts == []
    assert session.copied == ["previous structured answer"]
    return result


class _CopyCommandPlaybackSession:
    def __init__(self, *, recent_texts: tuple[str, ...]) -> None:
        self.recent_texts = recent_texts
        self.commands: list[tuple[str, str]] = []
        self.prompts: list[str] = []
        self.copied: list[str] = []

    def list_commands(self) -> list[object]:
        return [
            SimpleNamespace(
                name="copy",
                description="Copy an assistant message to clipboard",
                source="builtin",
                argument_hint="[N]",
            )
        ]

    async def execute_command_async(
        self,
        invocation_name: str,
        args: str,
    ) -> object:
        self.commands.append((invocation_name, args))
        copy_index = int(args.strip() or "1")
        text = self.recent_texts[copy_index - 1]
        self.copied.append(text)
        return SimpleNamespace(
            invocation_name=invocation_name,
            result={
                "source": "builtin",
                "command": invocation_name,
                "status": "ok",
                "message": f"Copied /copy {copy_index} from structured source.",
                "index": copy_index,
                "characters": len(text),
            },
        )

    async def prompt(self, text: str, **_kwargs: object) -> None:
        self.prompts.append(text)


_NEUTRAL_TRANSCRIPT_SCENARIOS = transcript_scenarios(
    CODING_SCENARIO_FACTORY,
    CODING_SCENARIO_FRAME_CONTRACTS,
    fixtures=_CODING_TRANSCRIPT_FIXTURES,
)

TRANSCRIPT_SCENARIOS = (
    *_NEUTRAL_TRANSCRIPT_SCENARIOS[:3],
    PlaybackScenarioSpec(
        name="transcript-reader-copy-command",
        description="Open and close the transcript reader, then copy the second assistant response from structured history.",
        run=_run_transcript_reader_copy_command,
        tags=("transcript", "command"),
    ),
    *_NEUTRAL_TRANSCRIPT_SCENARIOS[3:],
)


__all__ = ["TRANSCRIPT_SCENARIOS"]
