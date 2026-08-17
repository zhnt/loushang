from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from loushang.harnesstui.conversation.screen_runner import ConversationScreenPort
from loushang.harnesstui.testing.input_playback import (
    ConversationInputPlaybackResult,
    ConversationInputScenario,
)
from loushang.harnesstui.testing.scenarios.factory import (
    ConversationScenarioFactory,
    ScenarioFrameContracts,
)
from loushang.tui import (
    CompletionItem,
    CompletionProvider,
    PlaybackEvent,
    RenderConstraints,
)
from loushang.tui.input import BRACKETED_PASTE_END, BRACKETED_PASTE_START
from loushang.tui.playback_suite import PlaybackScenarioSpec

AppT = TypeVar("AppT", bound=ConversationScreenPort)


def composer_scenarios(
    factory: ConversationScenarioFactory[AppT],
    contracts: ScenarioFrameContracts,
) -> tuple[PlaybackScenarioSpec, ...]:
    """Build product-neutral composer recipes against a concrete app binding."""

    recipes = _ComposerRecipes(factory=factory, contracts=contracts)
    return (
        PlaybackScenarioSpec(
            name="completion-tab",
            description="Apply tab completion without clearing or repainting the screen.",
            run=recipes.completion_tab,
        ),
        PlaybackScenarioSpec(
            name="completion-navigation-priority",
            description="Route completion navigation before history navigation.",
            run=recipes.completion_navigation_priority,
        ),
        PlaybackScenarioSpec(
            name="completion-escape-cancel",
            description="Cancel visible completions without clearing the composer draft.",
            run=recipes.completion_escape_cancel,
            tags=("completion", "editor", "composer"),
        ),
        PlaybackScenarioSpec(
            name="completion-prefix-refresh",
            description="Refresh visible completions when the composer prefix changes.",
            run=recipes.completion_prefix_refresh,
            tags=("completion", "editor", "composer"),
        ),
        PlaybackScenarioSpec(
            name="completion-enter-submits-command",
            description="Apply a selected slash command completion before local command submission.",
            run=recipes.completion_enter_submits_command,
            tags=("completion", "command", "composer"),
        ),
        PlaybackScenarioSpec(
            name="history-navigation",
            description="Browse prompt history from a non-empty draft and restore the draft.",
            run=recipes.history_navigation,
        ),
        PlaybackScenarioSpec(
            name="bracketed-paste-large-marker",
            description="Render a large bracketed paste as a stable composer marker.",
            run=recipes.bracketed_paste_large_marker,
        ),
        PlaybackScenarioSpec(
            name="resize-reflow-stable",
            description="Keep composer text and cursor stable across terminal resizes.",
            run=recipes.resize_reflow_stable,
        ),
        PlaybackScenarioSpec(
            name="wide-char-input-cursor",
            description="Keep CJK and emoji input cursor diagnostics aligned.",
            run=recipes.wide_char_input_cursor,
        ),
        PlaybackScenarioSpec(
            name="keyboard-shift-enter-newline",
            description="Route raw Shift+Enter to composer newline before submission.",
            run=recipes.keyboard_shift_enter_newline,
        ),
        PlaybackScenarioSpec(
            name="editor-key-editing",
            description="Route common editor keys for line movement, kill/yank, and undo.",
            run=recipes.editor_key_editing,
            tags=("editor", "composer"),
        ),
        PlaybackScenarioSpec(
            name="page-navigation",
            description="Route composer PageUp and PageDown using playback terminal dimensions.",
            run=recipes.page_navigation,
            tags=("editor", "composer"),
        ),
        PlaybackScenarioSpec(
            name="paste-marker-delete-undo",
            description="Delete a large paste marker atomically and restore it with undo.",
            run=recipes.paste_marker_delete_undo,
            tags=("editor", "paste", "composer"),
        ),
        PlaybackScenarioSpec(
            name="composer-selection-replace",
            description="Extend composer selection with Shift+Left and replace it through typed input.",
            run=recipes.composer_selection_replace,
            tags=("editor", "selection", "composer"),
        ),
        PlaybackScenarioSpec(
            name="composer-selection-stress",
            description="Stress composer selection across wide text, paste markers, kill/yank, undo, and completions.",
            run=recipes.composer_selection_stress,
            tags=("editor", "selection", "paste", "completion", "composer"),
        ),
    )


@dataclass(frozen=True, slots=True)
class _ComposerRecipes(Generic[AppT]):
    factory: ConversationScenarioFactory[AppT]
    contracts: ScenarioFrameContracts

    def completion_tab(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .with_completion_items("/model", "/models")
            .render()
            .type_text("/mod")
            .tab()
            .run()
        )
        result.assert_composer_text("/model ")
        result.assert_visible_contains("/model")
        self._assert_interaction(result)
        return result

    def completion_navigation_priority(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .with_history("history prompt")
            .with_completion_items("/model", "/models")
            .render()
            .type_text("/mod")
            .key("\x1b[B")
            .tab()
            .run()
        )
        result.assert_composer_text("/models ")
        result.assert_visible_contains("/models")
        self._assert_interaction(result)
        return result

    def completion_escape_cancel(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .with_completion_items("/help", "/history")
            .render()
            .type_text("/h")
            .escape()
            .run()
        )
        result.assert_composer_text("/h")
        result.assert_visible_contains("/h")
        result.assert_visible_not_contains("  /help")
        result.assert_visible_not_contains("  /history")
        self._assert_interaction(result)
        return result

    def completion_prefix_refresh(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .with_completion_items("/help", "/history", "/model")
            .render()
            .type_text("/")
            .type_text("m")
            .run()
        )
        result.assert_composer_text("/m")
        result.assert_visible_contains("/m")
        result.assert_visible_contains("  /model")
        result.assert_visible_not_contains("  /help")
        result.assert_visible_not_contains("  /history")
        self._assert_interaction(result)
        return result

    def completion_enter_submits_command(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(
                width=80,
                height=12,
                is_local_command=lambda text: text == "/model",
            )
            .with_completion_items("/model", "/models")
            .render()
            .type_text("/mod")
            .enter()
            .run()
        )
        result.assert_local_texts("/model")
        result.assert_composer_text("")
        result.assert_visible_not_contains("  /model")
        result.assert_visible_not_contains("  /models")
        self._assert_interaction(result)
        return result

    def history_navigation(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .with_history("first prompt", "second prompt")
            .render()
            .type_text("draft")
            .key("\x1b[A")
            .key("\x1b[A")
            .key("\x1b[B")
            .key("\x1b[B")
            .run()
        )
        assert [
            state["composer_text"] for state in result.step_state_snapshots[1:]
        ] == [
            "draft",
            "second prompt",
            "first prompt",
            "second prompt",
            "draft",
        ]
        result.assert_composer_text("draft")
        result.assert_visible_contains("draft")
        self._assert_interaction(result)
        return result

    def bracketed_paste_large_marker(self) -> ConversationInputPlaybackResult[AppT]:
        pasted = "\n".join(f"line {index}" for index in range(10))
        result = (
            self.factory.input(width=80, height=12)
            .render()
            .key(f"{BRACKETED_PASTE_START}{pasted}{BRACKETED_PASTE_END}")
            .run()
        )
        result.assert_composer_text(pasted)
        result.assert_visible_contains("[paste #1 +10 lines]")
        self._assert_interaction(result)
        return result

    def resize_reflow_stable(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .render()
            .type_text("resize keeps composer stable")
            .resize(width=42, height=8)
            .type_text(" after shrink")
            .resize(width=100, height=14)
            .type_text(" after grow")
            .run()
        )
        result.assert_composer_text(
            "resize keeps composer stable after shrink after grow"
        )
        result.assert_visible_contains("after grow")
        assert any(
            step.diagnostics.operation_class == "resize_repaint"
            for step in result.steps
        )
        result.assert_no_clear_scrollback()
        result.assert_cursor_matches_diagnostics()
        self.contracts.assert_interaction(result)
        return result

    def wide_char_input_cursor(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=32, height=10)
            .render()
            .type_chars("你好🙂 terminal")
            .run()
        )
        result.assert_composer_text("你好🙂 terminal")
        result.assert_visible_contains("你好🙂 terminal")
        self._assert_interaction(result)
        return result

    def keyboard_shift_enter_newline(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .render()
            .type_text("first line")
            .key("\x1b[13;2u")
            .type_text("second line")
            .enter()
            .run()
        )
        result.assert_prompt_texts("first line\nsecond line")
        result.assert_composer_text("")
        result.assert_visible_contains("first line")
        self._assert_interaction(result)
        return result

    def editor_key_editing(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .render()
            .type_text("alpha beta gamma")
            .key("\x01say ")
            .key("\x05\x17")
            .key("\x19")
            .key("\x1f")
            .run()
        )
        result.assert_composer_text("say alpha beta ")
        result.assert_visible_contains("say alpha beta")
        self._assert_interaction(result)
        return result

    def page_navigation(self) -> ConversationInputPlaybackResult[AppT]:
        scenario = self.factory.input(width=20, height=3).with_composer_text(
            "one\ntwo\nthree\nfour\nfive"
        )
        playback = scenario.playback

        playback.play((PlaybackEvent("render"), PlaybackEvent.input("\x1b[5~")))
        page_up = scenario.app.composer.render(
            RenderConstraints(width=20, max_height=5)
        )
        assert page_up.cursor is not None
        assert (page_up.cursor.row, page_up.cursor.column) == (2, 6)

        playback.play((PlaybackEvent.input("\x1b[6~"),))
        page_down = scenario.app.composer.render(
            RenderConstraints(width=20, max_height=5)
        )
        assert page_down.cursor is not None
        assert (page_down.cursor.row, page_down.cursor.column) == (4, 6)

        result = self._result_from_scenario(scenario)
        result.assert_composer_text("one\ntwo\nthree\nfour\nfive")
        self._assert_interaction(result)
        return result

    def paste_marker_delete_undo(self) -> ConversationInputPlaybackResult[AppT]:
        pasted = "\n".join(f"line {index}" for index in range(10))
        result = (
            self.factory.input(width=80, height=12)
            .render()
            .key(f"{BRACKETED_PASTE_START}{pasted}{BRACKETED_PASTE_END}")
            .key("\x7f")
            .key("\x1f")
            .run()
        )
        result.assert_composer_text(pasted)
        result.assert_visible_contains("[paste #1 +10 lines]")
        self._assert_interaction(result)
        return result

    def composer_selection_replace(self) -> ConversationInputPlaybackResult[AppT]:
        result = (
            self.factory.input(width=80, height=12)
            .render()
            .type_text("abc")
            .key("\x1b[1;2D")
            .type_text("x")
            .run()
        )
        selected_output = (
            result.steps[2].frame.serialized_output if result.steps[2].frame else ""
        )
        assert "\x1b[7mc\x1b[27m" in selected_output
        result.assert_composer_text("abx")
        result.assert_visible_contains("abx")
        self._assert_interaction(result)
        return result

    def composer_selection_stress(self) -> ConversationInputPlaybackResult[AppT]:
        scenario = self.factory.input(width=80, height=12)
        playback = scenario.playback

        playback.play(
            (
                PlaybackEvent("render"),
                PlaybackEvent.input("你🙂a"),
                PlaybackEvent.input("\x1b[1;2D"),
                PlaybackEvent.input("\x1b[1;2D"),
                PlaybackEvent.input("x"),
                PlaybackEvent.input("\x1b[1;2H"),
                PlaybackEvent.input("wide"),
                PlaybackEvent.input("\x1f"),
                PlaybackEvent.input("\x01"),
                PlaybackEvent.input("\x1b[1;2F"),
                PlaybackEvent.input("\x0b"),
                PlaybackEvent.input("\x19"),
                PlaybackEvent.input("\x1f"),
            )
        )
        assert scenario.app.composer.value == ""
        assert [
            state["composer_text"] for state in playback.step_state_snapshots[1:8]
        ] == [
            "你🙂a",
            "你🙂a",
            "你🙂a",
            "你x",
            "你x",
            "wide",
            "你x",
        ]

        pasted = "\n".join(f"selected paste line {index}" for index in range(10))
        playback.play(
            (
                PlaybackEvent.input(
                    f"{BRACKETED_PASTE_START}{pasted}{BRACKETED_PASTE_END}"
                ),
            )
        )
        assert scenario.app.composer.value == pasted
        assert scenario.app.composer.selected_range is None
        assert "[paste #1 +10 lines]" in "\n".join(playback.port.screen.visible_lines)

        playback.play((PlaybackEvent.input("\x1b[1;2D"),))
        assert scenario.app.composer.selected_range == (0, 1)
        playback.play((PlaybackEvent.input("\x7f"),))
        assert scenario.app.composer.value == ""
        playback.play((PlaybackEvent.input("\x1f"),))
        assert scenario.app.composer.value == pasted
        assert "[paste #1 +10 lines]" in "\n".join(playback.port.screen.visible_lines)

        scenario.app.composer.clear()
        scenario.app.composer.set_completion_provider(
            CompletionProvider(
                (
                    CompletionItem(value="ax-alpha"),
                    CompletionItem(value="ax-beta"),
                )
            )
        )
        playback.play(
            (
                PlaybackEvent.input("ab"),
                PlaybackEvent.input("\x1b[1;2D"),
                PlaybackEvent.input("x"),
            )
        )
        assert scenario.app.composer.value == "ax"
        assert scenario.app.composer.selected_range is None
        assert scenario.app.composer.has_completions
        assert "ax-alpha" in "\n".join(playback.port.screen.visible_lines)

        result = self._result_from_scenario(scenario)
        result.assert_any_frame_output_contains("\x1b[7m")
        self._assert_interaction(result)
        return result

    def _result_from_scenario(
        self,
        scenario: ConversationInputScenario[AppT],
    ) -> ConversationInputPlaybackResult[AppT]:
        return scenario.playback.result()

    def _assert_interaction(
        self,
        result: ConversationInputPlaybackResult[AppT],
    ) -> None:
        result.assert_no_clear_screen()
        result.assert_cursor_matches_diagnostics()
        self.contracts.assert_interaction(result)


__all__ = ["composer_scenarios"]
