from __future__ import annotations

import asyncio

from loushang.coding.ui.completion import coding_inline_completion_provider
from loushang.harnesstui.testing.scenarios.composer import composer_scenarios
from loushang.tui.playback_suite import PlaybackScenarioSpec
from tests.coding.tui_support.fakes import (
    SessionCommandPlaybackSession as _SessionCommandSession,
)
from tests.coding.tui_support.playback import (
    ScreenTuiInputPlaybackResult,
    ScreenTuiInputScenario,
)
from tests.coding.tui_support.scenario_binding import (
    CODING_SCENARIO_FACTORY,
    CODING_SCENARIO_FRAME_CONTRACTS,
)
from tests.coding.tui_support.scenarios.budgets import (
    INTERACTION_FRAME_BUDGET,
)


def _run_completion_session_command() -> ScreenTuiInputPlaybackResult:
    session = _SessionCommandSession()
    scenario = ScreenTuiInputScenario(width=80, height=12)
    scenario.app.composer.set_completion_provider(
        asyncio.run(coding_inline_completion_provider(session, base_path=None))
    )

    result = scenario.render().type_text("/na").tab().run()

    result.assert_composer_text("/rename ")
    result.assert_visible_contains("› /rename")
    result.assert_no_clear_screen()
    result.assert_cursor_matches_diagnostics()
    assert session.commands == []
    assert session.prompts == []
    INTERACTION_FRAME_BUDGET.assert_result(result, skip_first=True)
    return result


_SHARED_COMPOSER_SCENARIOS = composer_scenarios(
    CODING_SCENARIO_FACTORY,
    CODING_SCENARIO_FRAME_CONTRACTS,
)

COMPOSER_SCENARIOS = (
    _SHARED_COMPOSER_SCENARIOS[0],
    PlaybackScenarioSpec(
        name="completion-session-command",
        description="Apply session command completion without executing the selected command.",
        run=_run_completion_session_command,
        tags=("completion", "command", "session"),
    ),
    *_SHARED_COMPOSER_SCENARIOS[1:],
)


__all__ = ["COMPOSER_SCENARIOS"]
