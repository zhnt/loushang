from __future__ import annotations

from typing import cast

from loushang.harnesstui.conversation.screen_runner import ConversationScreenPort
from loushang.harnesstui.testing.scenarios.composer import composer_scenarios
from loushang.harnesstui.testing.scenarios.factory import (
    ConversationScenarioFactory,
    ScenarioFrameContracts,
)
from loushang.harnesstui.testing.scenarios.lifecycle import lifecycle_scenarios
from loushang.harnesstui.testing.scenarios.terminal import terminal_scenarios
from loushang.tui.playback import PlaybackFrameBudget


def test_shared_recipe_builders_publish_only_neutral_scenario_catalogs() -> None:
    factory = cast(
        ConversationScenarioFactory[ConversationScreenPort],
        object(),
    )
    contracts = ScenarioFrameContracts(
        interaction=PlaybackFrameBudget(),
        long_transcript=PlaybackFrameBudget(),
    )

    assert [scenario.name for scenario in composer_scenarios(factory, contracts)] == [
        "completion-tab",
        "completion-navigation-priority",
        "completion-escape-cancel",
        "completion-prefix-refresh",
        "completion-enter-submits-command",
        "history-navigation",
        "bracketed-paste-large-marker",
        "resize-reflow-stable",
        "wide-char-input-cursor",
        "keyboard-shift-enter-newline",
        "editor-key-editing",
        "page-navigation",
        "paste-marker-delete-undo",
        "composer-selection-replace",
        "composer-selection-stress",
    ]
    assert [scenario.name for scenario in lifecycle_scenarios(factory, contracts)] == [
        "idle-escape-clears-draft",
        "running-steer-queued",
        "running-escape-keeps-queued-steer",
        "idle-escape-pops-pending-steer",
        "escape-pending-steer",
        "escape-pending-steer-fifo",
        "escape-pending-steer-preserves-draft",
        "screen-loop-ctrl-c-abort-running",
        "running-follow-up-queued",
        "keyboard-alt-enter-follow-up",
    ]
    assert [scenario.name for scenario in terminal_scenarios(factory)] == [
        "screen-loop-split-bracketed-paste",
        "terminal-control-response-hidden",
        "screen-loop-terminal-session-cleanup",
        "apple-shift-enter-normalized",
    ]
