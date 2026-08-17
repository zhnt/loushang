"""Coding binding for product-neutral conversation lifecycle scenarios."""

from __future__ import annotations

from loushang.harnesstui.testing.scenarios.lifecycle import lifecycle_scenarios
from tests.coding.tui_support.scenario_binding import (
    CODING_SCENARIO_FACTORY,
    CODING_SCENARIO_FRAME_CONTRACTS,
)

LIFECYCLE_SCENARIOS = lifecycle_scenarios(
    CODING_SCENARIO_FACTORY,
    CODING_SCENARIO_FRAME_CONTRACTS,
)

__all__ = ["LIFECYCLE_SCENARIOS"]
