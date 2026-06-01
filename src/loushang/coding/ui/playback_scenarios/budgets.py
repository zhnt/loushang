from __future__ import annotations

from loushang.tui import PlaybackFrameBudget

INTERACTION_FRAME_BUDGET = PlaybackFrameBudget(
    disallowed_operation_classes=("baseline_repaint", "recovery_repaint"),
    max_operations=32,
    max_serialized_output_bytes=768,
    max_changed_visible_lines=8,
    require_synchronized=True,
)

LONG_TRANSCRIPT_FRAME_BUDGET = PlaybackFrameBudget(
    disallowed_operation_classes=("baseline_repaint", "recovery_repaint"),
    max_operations=12,
    max_serialized_output_bytes=2_000,
    max_changed_visible_lines=3,
    require_synchronized=True,
)
