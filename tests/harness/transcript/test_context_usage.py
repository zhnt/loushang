from __future__ import annotations

import loushang.harness.transcript.context_usage as context_usage
import loushang.harness.transcript.maintenance as maintenance
from loushang.harness.transcript import (
    ContextUsageSnapshot,
    build_context_usage_snapshot,
    calculate_context_tokens,
    current_context_usage,
    estimate_context_tokens,
    estimate_message_tokens,
    has_post_compaction_usage,
    latest_compaction_entry,
    model_context_window,
)


def test_context_usage_public_exports_keep_their_stable_package_surface() -> None:
    assert ContextUsageSnapshot is context_usage.ContextUsageSnapshot
    assert maintenance.ContextUsageSnapshot is context_usage.ContextUsageSnapshot
    assert build_context_usage_snapshot is context_usage.build_context_usage_snapshot
    assert (
        maintenance.build_context_usage_snapshot
        is context_usage.build_context_usage_snapshot
    )
    assert calculate_context_tokens is context_usage.calculate_context_tokens
    assert current_context_usage is context_usage.current_context_usage
    assert estimate_context_tokens is context_usage.estimate_context_tokens
    assert estimate_message_tokens is context_usage.estimate_message_tokens
    assert has_post_compaction_usage is context_usage.has_post_compaction_usage
    assert latest_compaction_entry is context_usage.latest_compaction_entry
    assert model_context_window is context_usage.model_context_window
