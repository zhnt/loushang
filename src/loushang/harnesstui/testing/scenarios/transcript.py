from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar

from loushang.harnesstui.conversation.screen_runner import ConversationScreenPort
from loushang.harnesstui.testing.input_playback import (
    ConversationInputPlaybackResult,
)
from loushang.harnesstui.testing.scenarios.factory import (
    ConversationScenarioFactory,
    ScenarioFrameContracts,
)
from loushang.tui import strip_control_sequences
from loushang.tui.playback_suite import PlaybackScenarioSpec
from loushang.tui.transcript import (
    AssistantMessageRecord,
    DisplayRecord,
    ErrorRecord,
    ToolExecutionRecord,
    UserPromptRecord,
    WorkedDividerRecord,
)

AppT = TypeVar("AppT", bound=ConversationScreenPort)


@dataclass(frozen=True, slots=True)
class TranscriptScenarioFixtures:
    """Product-supplied transcript data and presentation expectations.

    The recipes own interaction flow. A product remains responsible for the
    volume used by its performance contract and for any exact tool-preview
    presentation it wants to freeze.
    """

    long_transcript_records: Callable[[], Iterable[DisplayRecord]]
    tool_output_records: Callable[[], Iterable[DisplayRecord]]
    long_transcript_anchor: str | None = None
    tool_preview_visible: tuple[str, ...] = ()
    tool_preview_hidden: tuple[str, ...] = ()


def transcript_scenarios(
    factory: ConversationScenarioFactory[AppT],
    contracts: ScenarioFrameContracts,
    *,
    fixtures: TranscriptScenarioFixtures | None = None,
) -> tuple[PlaybackScenarioSpec, ...]:
    """Build product-neutral transcript interaction recipes."""

    recipes = _TranscriptRecipes(
        factory=factory,
        contracts=contracts,
        fixtures=fixtures or _DEFAULT_FIXTURES,
    )
    return (
        PlaybackScenarioSpec(
            name="long-transcript-input",
            description="Echo input after a long transcript using bounded frame updates.",
            run=recipes.long_transcript_input,
        ),
        PlaybackScenarioSpec(
            name="tool-output-preview",
            description="Render long tool output as a bounded preview without flicker.",
            run=recipes.tool_output_preview,
        ),
        PlaybackScenarioSpec(
            name="transcript-reader-modal",
            description="Open the transcript reader, keep input modal, close it, and resume composing.",
            run=recipes.transcript_reader_modal,
        ),
        PlaybackScenarioSpec(
            name="transcript-reader-live-draft",
            description="Open the transcript reader during assistant streaming and keep the live draft visible.",
            run=recipes.transcript_reader_live_draft,
            tags=("transcript",),
        ),
        PlaybackScenarioSpec(
            name="transcript-reader-render-modes",
            description="Toggle transcript reader detail and raw modes without changing the composer.",
            run=recipes.transcript_reader_render_modes,
            tags=("transcript",),
        ),
        PlaybackScenarioSpec(
            name="transcript-reader-search",
            description="Search within the transcript reader, navigate matches, and return to composing.",
            run=recipes.transcript_reader_search,
            tags=("transcript",),
        ),
    )


@dataclass(frozen=True, slots=True)
class _TranscriptRecipes(Generic[AppT]):
    factory: ConversationScenarioFactory[AppT]
    contracts: ScenarioFrameContracts
    fixtures: TranscriptScenarioFixtures

    def long_transcript_input(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=100, height=18)
            .with_records(self.fixtures.long_transcript_records())
            .render()
            .type_chars("fresh input")
            .run()
        )
        result.assert_composer_text("fresh input")
        result.assert_visible_contains("fresh input")
        result.assert_no_clear_screen()
        self.contracts.assert_long_transcript(result)
        if self.fixtures.long_transcript_anchor is not None:
            result.assert_screen_anchor_stable(
                self.fixtures.long_transcript_anchor,
                occurrence="last",
            )
        return result

    def tool_output_preview(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=100, height=16)
            .with_records(self.fixtures.tool_output_records())
            .render()
            .type_text("next")
            .run()
        )
        for expected in self.fixtures.tool_preview_visible:
            result.assert_visible_contains(expected)
        for unexpected in self.fixtures.tool_preview_hidden:
            result.assert_visible_not_contains(unexpected)
        result.assert_composer_text("next")
        result.assert_visible_contains("next")
        self._assert_interaction(result)
        return result

    def transcript_reader_modal(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=72, height=8)
            .with_records(
                (
                    AssistantMessageRecord(
                        "\n".join(f"answer line {index}" for index in range(12))
                    ),
                )
            )
            .with_composer_text("draft")
            .with_completion_items("drafted")
            .render()
            .key("\x0f")
            .tab()
            .key("\x02")
            .key("\x06")
            .ctrl_c()
            .type_text("!")
            .run()
        )
        result.assert_composer_text("draft!")
        result.assert_prompt_texts()
        result.assert_local_texts()
        result.assert_no_abort_requested()
        result.assert_visible_contains("draft!")
        result.assert_visible_not_contains("Ctrl+O/q/Esc close")
        result.assert_no_clear_screen()

        opened_screen = _step_screen(result, 1)
        tab_screen = _step_screen(result, 2)
        ctrl_b_screen = _step_screen(result, 3)
        ctrl_f_screen = _step_screen(result, 4)
        assert "Ctrl+O/q/Esc close" in opened_screen
        assert "PgUp/Ctrl+B · PgDn/Ctrl+F page" in opened_screen
        assert "answer line 11" in opened_screen
        assert "Ctrl+O/q/Esc close" in tab_screen
        assert result.step_state_snapshots[2]["composer_text"] == "draft"
        assert "answer line 4" in ctrl_b_screen
        assert "answer line 11" in ctrl_f_screen
        return result

    def transcript_reader_live_draft(
        self,
    ) -> ConversationInputPlaybackResult[AppT]:
        scenario = (
            self.factory.input(width=78, height=10)
            .with_records(
                (
                    UserPromptRecord("previous question"),
                    AssistantMessageRecord("previous answer", stable=True),
                )
            )
            .with_composer_text("draft")
        )
        scenario.app.state.begin_run(started_at=0.0)
        scenario.app.state.begin_assistant()
        scenario.app.state.append_assistant_chunk("streaming live draft")

        result = scenario.render().key("\x0f").key("\x0f").type_text("!").run()
        result.assert_composer_text("draft!")
        result.assert_no_clear_screen()
        result.assert_visible_contains("draft!")
        result.assert_visible_not_contains("Ctrl+O/q/Esc close")

        opened_screen = _step_screen(result, 1)
        closed_screen = _step_screen(result, 2)
        assert "Transcript window" in opened_screen
        assert "streaming live draft" in opened_screen
        assert "Ctrl+O/q/Esc close" in opened_screen
        assert "Ctrl+O/q/Esc close" not in closed_screen
        assert "draft" in closed_screen
        return result

    def transcript_reader_render_modes(
        self,
    ) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=88, height=12)
            .with_records(
                (
                    AssistantMessageRecord("Use **markdown** literally.", stable=True),
                    ErrorRecord(
                        summary="Request failed",
                        diagnostics="Traceback detail",
                    ),
                )
            )
            .with_composer_text("draft")
            .render()
            .key("\x0f")
            .type_text("d")
            .type_text("r")
            .key("\x0f")
            .type_text("!")
            .run()
        )
        result.assert_composer_text("draft!")
        result.assert_no_clear_screen()
        result.assert_visible_contains("draft!")
        result.assert_visible_not_contains("Ctrl+O/q/Esc close")

        opened_screen = _step_screen(result, 1)
        detail_screen = _step_screen(result, 2)
        raw_detail_screen = _step_screen(result, 3)
        closed_screen = _step_screen(result, 4)
        assert "Transcript window" in opened_screen
        assert "Traceback detail" not in opened_screen
        assert "Transcript window · detail" in detail_screen
        assert "Traceback detail" in detail_screen
        assert "Transcript window · raw+detail" in raw_detail_screen
        assert "Assistant" in raw_detail_screen
        assert "Use **markdown** literally." in raw_detail_screen
        assert "Error" in raw_detail_screen
        assert "Traceback detail" in raw_detail_screen
        assert "Ctrl+O/q/Esc close" not in closed_screen
        assert "draft" in closed_screen
        return result

    def transcript_reader_search(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=82, height=10)
            .with_records(
                (
                    AssistantMessageRecord(
                        "\n".join(
                            (
                                "alpha one",
                                "beta first match",
                                "middle line",
                                "beta second match",
                            )
                        ),
                        stable=True,
                    ),
                )
            )
            .with_composer_text("draft")
            .render()
            .key("\x0f")
            .type_chars("/beta")
            .enter()
            .type_chars("n")
            .type_chars("N")
            .escape()
            .key("\x0f")
            .type_text("!")
            .run()
        )
        result.assert_composer_text("draft!")
        result.assert_no_clear_screen()
        result.assert_visible_contains("draft!")
        result.assert_visible_not_contains("Ctrl+O/q/Esc close")

        search_input_screen = _step_screen(result, 6)
        first_match_screen = _step_screen(result, 7)
        next_match_screen = _step_screen(result, 8)
        previous_match_screen = _step_screen(result, 9)
        cleared_search_screen = _step_screen(result, 10)
        closed_screen = _step_screen(result, 11)
        assert "Search: beta" in search_input_screen
        assert "Transcript window · search beta 1/2" in first_match_screen
        assert "beta first match" in first_match_screen
        assert "Transcript window · search beta 2/2" in next_match_screen
        assert "beta second match" in next_match_screen
        assert "Transcript window · search beta 1/2" in previous_match_screen
        assert "Transcript window · search" not in cleared_search_screen
        assert "Ctrl+O/q/Esc close" in cleared_search_screen
        assert "Ctrl+O/q/Esc close" not in closed_screen
        assert "draft" in closed_screen
        return result

    def _assert_interaction(
        self,
        result: ConversationInputPlaybackResult[AppT],
    ) -> None:
        result.assert_no_clear_screen()
        result.assert_cursor_matches_diagnostics()
        self.contracts.assert_interaction(result)


def _step_screen(
    result: ConversationInputPlaybackResult[AppT],
    step_index: int,
) -> str:
    step = result.steps[step_index]
    assert step.frame is not None
    return strip_control_sequences("\n".join(step.frame.screen_after.visible_lines))


def _default_long_transcript_records() -> tuple[DisplayRecord, ...]:
    records: list[DisplayRecord] = []
    for index in range(1, 9):
        records.extend(
            (
                UserPromptRecord(f"Question {index}"),
                AssistantMessageRecord(f"Answer {index}"),
                ToolExecutionRecord(
                    name=f"inspect item {index}",
                    state="completed",
                    elapsed_seconds=0.01,
                    output="\n".join(
                        f"item {index} output line {line}" for line in range(1, 13)
                    ),
                ),
                WorkedDividerRecord(0.25),
            )
        )
    return tuple(records)


def _default_tool_output_records() -> tuple[DisplayRecord, ...]:
    return (
        ToolExecutionRecord(
            name="inspect output",
            state="completed",
            elapsed_seconds=0.6,
            output="\n".join(f"line {index}" for index in range(1, 13)),
        ),
    )


_DEFAULT_FIXTURES = TranscriptScenarioFixtures(
    long_transcript_records=_default_long_transcript_records,
    tool_output_records=_default_tool_output_records,
    tool_preview_visible=("line 1", "line 12"),
)


__all__ = ["TranscriptScenarioFixtures", "transcript_scenarios"]
