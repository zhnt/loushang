"""Coding binding for product-neutral terminal playback scenarios."""

from __future__ import annotations

from loushang.harnesstui.testing.scenarios.terminal import terminal_scenarios
from tests.coding.tui_support.scenario_binding import CODING_SCENARIO_FACTORY

TERMINAL_SCENARIOS = terminal_scenarios(CODING_SCENARIO_FACTORY)

__all__ = ["TERMINAL_SCENARIOS"]
