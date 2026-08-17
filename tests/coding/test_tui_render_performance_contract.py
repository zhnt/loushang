from __future__ import annotations

import pytest

from loushang.tui import PlaybackFrameBudget
from tests.coding.tui_support.scenarios.budgets import (
    INTERACTION_FRAME_BUDGET,
    LONG_TRANSCRIPT_FRAME_BUDGET,
)
from tests.coding.tui_support.scenarios.product import (
    PRODUCT_COMPOSED_FRAME_BUDGET,
    PRODUCT_STREAMING_CONTROL_FRAME_BUDGET,
)

pytestmark = pytest.mark.tui_render_contract


@pytest.mark.parametrize(
    ("actual", "expected"),
    (
        (
            INTERACTION_FRAME_BUDGET,
            PlaybackFrameBudget(
                disallowed_operation_classes=(
                    "baseline_repaint",
                    "recovery_repaint",
                ),
                max_operations=32,
                max_serialized_output_bytes=768,
                max_changed_visible_lines=8,
                require_synchronized=True,
            ),
        ),
        (
            LONG_TRANSCRIPT_FRAME_BUDGET,
            PlaybackFrameBudget(
                disallowed_operation_classes=(
                    "baseline_repaint",
                    "recovery_repaint",
                ),
                max_operations=12,
                max_serialized_output_bytes=2_000,
                max_changed_visible_lines=3,
                require_synchronized=True,
            ),
        ),
        (
            PRODUCT_COMPOSED_FRAME_BUDGET,
            PlaybackFrameBudget(
                disallowed_operation_classes=(
                    "baseline_repaint",
                    "recovery_repaint",
                ),
                max_operations=64,
                max_serialized_output_bytes=3_000,
                max_changed_visible_lines=20,
                require_synchronized=True,
            ),
        ),
        (
            PRODUCT_STREAMING_CONTROL_FRAME_BUDGET,
            PlaybackFrameBudget(
                disallowed_operation_classes=(
                    "baseline_repaint",
                    "recovery_repaint",
                ),
                max_operations=1_500,
                max_serialized_output_bytes=90_000,
                max_changed_visible_lines=18,
                require_synchronized=True,
            ),
        ),
    ),
    ids=(
        "interaction",
        "long-transcript",
        "product-composed",
        "product-streaming-control",
    ),
)
def test_tui_playback_frame_budget_values_are_frozen(
    actual: PlaybackFrameBudget,
    expected: PlaybackFrameBudget,
) -> None:
    assert actual == expected
