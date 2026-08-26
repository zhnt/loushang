from __future__ import annotations

import loushang.harness.transcript.context_usage as context_usage
import loushang.harness.transcript.maintenance as maintenance
from loushang.harness.context import serialize_context_usage_payload
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


def test_context_usage_measurement_identity_serializes_compatibly() -> None:
    payload = serialize_context_usage_payload(
        ContextUsageSnapshot(
            tokens=42,
            context_window=128_000,
            reserve_tokens=8_192,
            source="estimated",
            authority="local_estimator",
            accuracy="estimated",
            transcript_revision=7,
            leaf_id="leaf-7",
            estimator_id="harness.message_chars.v1",
        )
    )

    assert payload is not None
    assert payload["authority"] == "local_estimator"
    assert payload["accuracy"] == "estimated"
    assert payload["transcriptRevision"] == 7
    assert payload["leafId"] == "leaf-7"
    assert payload["estimatorId"] == "harness.message_chars.v1"
