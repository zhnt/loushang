from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import cast

from loushang.harnesstui.conversation.screen_runner import ConversationScreenPort
from loushang.harnesstui.testing.scenarios.factory import (
    ConversationScenarioFactory,
    ScenarioFrameContracts,
)
from loushang.harnesstui.testing.scenarios.transcript import (
    TranscriptScenarioFixtures,
    transcript_scenarios,
)
from loushang.tui.transcript import AssistantMessageRecord


def test_transcript_scenarios_publish_six_neutral_recipes() -> None:
    scenarios = transcript_scenarios(
        cast(ConversationScenarioFactory[ConversationScreenPort], object()),
        cast(ScenarioFrameContracts, object()),
    )

    assert [scenario.name for scenario in scenarios] == [
        "long-transcript-input",
        "tool-output-preview",
        "transcript-reader-modal",
        "transcript-reader-live-draft",
        "transcript-reader-render-modes",
        "transcript-reader-search",
    ]
    assert all(
        scenario.run.__self__.__class__.__module__
        == "loushang.harnesstui.testing.scenarios.transcript"
        for scenario in scenarios
    )


def test_transcript_scenarios_keep_product_fixture_data_injected() -> None:
    fixtures = TranscriptScenarioFixtures(
        long_transcript_records=lambda: (AssistantMessageRecord("long"),),
        tool_output_records=lambda: (AssistantMessageRecord("tool"),),
        tool_preview_visible=("product-visible",),
        tool_preview_hidden=("product-hidden",),
    )

    scenarios = transcript_scenarios(
        cast(ConversationScenarioFactory[ConversationScreenPort], object()),
        cast(ScenarioFrameContracts, object()),
        fixtures=fixtures,
    )

    recipes = scenarios[0].run.__self__
    assert recipes.fixtures is fixtures


def test_transcript_and_surface_recipe_imports_stay_product_neutral() -> None:
    script = """
import importlib
import sys

for module_name in (
    "loushang.harnesstui.testing.scenarios.transcript",
    "loushang.harnesstui.testing.scenarios.surface",
):
    importlib.import_module(module_name)

forbidden_prefixes = (
    "loushang.agent",
    "loushang.ai",
    "loushang.coding",
    "loushang.harness",
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


def test_transcript_recipe_source_does_not_own_coding_presentation_copy() -> None:
    source = Path("src/loushang/harnesstui/testing/scenarios/transcript.py").read_text(
        encoding="utf-8"
    )

    assert all(
        product_copy not in source
        for product_copy in (
            "›",
            "Messages to be submitted after next tool call",
            "Conversation interrupted",
            "Operation aborted",
        )
    )
