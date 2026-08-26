from __future__ import annotations

import loushang.harness.transcript.context_usage as context_usage
import loushang.harness.transcript.maintenance as maintenance
from loushang.ai.types import UserMessage
from loushang.harness.context import serialize_context_usage_payload
from loushang.harness.transcript import (
    ContextUsageSnapshot,
    ProviderContextAnchor,
    build_context_usage_snapshot,
    calculate_context_tokens,
    current_context_usage,
    estimate_context_tokens,
    estimate_message_tokens,
    has_post_compaction_usage,
    latest_compaction_entry,
    measure_replay_context_surface,
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
    assert (
        measure_replay_context_surface
        is context_usage.measure_replay_context_surface
    )


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
            surface_fingerprint="sha256:" + "a" * 64,
            provider_anchor=ProviderContextAnchor(
                invocation_id="invocation-1",
                attempt=1,
                model_input_snapshot_id="snapshot-1",
                provider_prompt_tokens=40,
                sampled_prepared_payload_hash="sha256:" + "b" * 64,
                sampled_surface_tokens=12,
                sampled_surface_fingerprint="sha256:" + "c" * 64,
                source_revision=5,
                commit_revision=6,
                provider_id="provider-1",
                endpoint_id="endpoint-1",
                api_id="api-1",
                model_id="model-1",
            ),
        )
    )

    assert payload is not None
    assert payload["authority"] == "local_estimator"
    assert payload["accuracy"] == "estimated"
    assert payload["transcriptRevision"] == 7
    assert payload["leafId"] == "leaf-7"
    assert payload["estimatorId"] == "harness.message_chars.v1"
    assert payload["surfaceFingerprint"] == "sha256:" + "a" * 64
    assert payload["providerAnchor"]["providerPromptTokens"] == 40
    assert payload["providerAnchor"]["modelInputSnapshotId"] == "snapshot-1"


def test_replay_surface_fingerprint_tracks_model_visible_content_only() -> None:
    first = measure_replay_context_surface(
        [UserMessage(role="user", content="hello", timestamp=1.0)]
    )
    timestamp_only = measure_replay_context_surface(
        [UserMessage(role="user", content="hello", timestamp=2.0)]
    )
    changed = measure_replay_context_surface(
        [UserMessage(role="user", content="hello!", timestamp=1.0)]
    )

    assert first.tokens == 2
    assert first.message_count == 1
    assert first.surface_fingerprint == timestamp_only.surface_fingerprint
    assert first.surface_fingerprint != changed.surface_fingerprint
