from __future__ import annotations

from pathlib import Path
from typing import cast

from loushang.harnesstui.conversation.screen_runner import ConversationScreenPort
from loushang.harnesstui.testing.scenarios.factory import (
    ConversationScenarioFactory,
    ScenarioFrameContracts,
)
from loushang.harnesstui.testing.scenarios.surface import surface_scenarios


def test_surface_scenarios_publish_only_product_neutral_selection_recipes() -> None:
    scenarios = surface_scenarios(
        cast(ConversationScenarioFactory[ConversationScreenPort], object()),
        cast(ScenarioFrameContracts, object()),
    )

    assert [scenario.name for scenario in scenarios] == [
        "active-surface",
        "mouse-select-active-surface",
    ]
    assert all(
        scenario.run.__self__.__class__.__module__
        == "loushang.harnesstui.testing.scenarios.surface"
        for scenario in scenarios
    )


def test_surface_recipe_source_does_not_own_product_surface_policy() -> None:
    source = Path("src/loushang/harnesstui/testing/scenarios/surface.py").read_text(
        encoding="utf-8"
    )

    assert all(
        product_term not in source
        for product_term in (
            "/settings",
            "approval",
            "command-palette",
            "model-select",
        )
    )
