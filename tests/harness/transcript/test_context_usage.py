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
    measure_structural_envelope_fingerprint,
    model_context_window,
    project_context_from_provider_anchor,
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
    assert (
        project_context_from_provider_anchor
        is context_usage.project_context_from_provider_anchor
    )
    assert (
        measure_structural_envelope_fingerprint
        is context_usage.measure_structural_envelope_fingerprint
    )


def _envelope_fingerprint(*, system_prompt: str = "system") -> str:
    return measure_structural_envelope_fingerprint(
        system_prompt=system_prompt,
        tools=[{"name": "read", "description": "Read", "parameters": {}}],
        request_options={"temperature": 0},
        provider_id="provider-1",
        endpoint_id="endpoint-1",
        api_id="api-1",
        model_id="model-1",
    )


def test_structural_envelope_fingerprint_is_stable_and_excludes_replay() -> None:
    first = _envelope_fingerprint()
    same = _envelope_fingerprint()
    changed = _envelope_fingerprint(system_prompt="changed system")

    assert first == same
    assert first.startswith("sha256:")
    assert first != changed


def test_provider_anchor_projects_current_surface_for_display_only() -> None:
    current_surface = measure_replay_context_surface(
        [UserMessage(role="user", content="current surface is longer", timestamp=1.0)]
    )
    snapshot = ContextUsageSnapshot(
        tokens=999,
        context_window=100,
        reserve_tokens=10,
        compactable=True,
        reason="threshold",
        stale_after_compaction=True,
    )
    anchor = ProviderContextAnchor(
        invocation_id="invocation-1",
        attempt=1,
        model_input_snapshot_id="snapshot-1",
        provider_prompt_tokens=80,
        sampled_prepared_payload_hash="sha256:" + "a" * 64,
        sampled_surface_tokens=5,
        sampled_surface_fingerprint="sha256:" + "b" * 64,
        source_revision=1,
        commit_revision=2,
        provider_id="provider-1",
        endpoint_id="endpoint-1",
        api_id="api-1",
        model_id="model-1",
        sampled_structural_envelope_fingerprint=_envelope_fingerprint(),
    )

    projected = project_context_from_provider_anchor(
        snapshot,
        anchor,
        current_surface,
        structural_envelope_fingerprint=_envelope_fingerprint(),
    )

    assert projected.tokens == 80 + current_surface.tokens - 5
    assert projected.percent == projected.tokens
    assert projected.source == "provider_anchor"
    assert projected.authority == "provider_usage"
    assert projected.accuracy == "projected"
    assert projected.compactable is False
    assert projected.reason == "provider_anchor_display_only"
    assert projected.stale_after_compaction is True
    assert projected.provider_anchor == anchor
    assert projected.structural_envelope_status == "matched"


def test_provider_anchor_projection_clamps_negative_delta_at_zero() -> None:
    current_surface = measure_replay_context_surface([])
    anchor = ProviderContextAnchor(
        invocation_id="invocation-1",
        attempt=1,
        model_input_snapshot_id="snapshot-1",
        provider_prompt_tokens=3,
        sampled_prepared_payload_hash="sha256:" + "a" * 64,
        sampled_surface_tokens=10,
        sampled_surface_fingerprint="sha256:" + "b" * 64,
        source_revision=1,
        commit_revision=2,
        provider_id="provider-1",
        endpoint_id="endpoint-1",
        api_id="api-1",
        model_id="model-1",
        sampled_structural_envelope_fingerprint=_envelope_fingerprint(),
    )

    projected = project_context_from_provider_anchor(
        ContextUsageSnapshot(tokens=3, context_window=100, reserve_tokens=0),
        anchor,
        current_surface,
        structural_envelope_fingerprint=_envelope_fingerprint(),
    )

    assert projected.tokens == 0
    assert projected.percent == 0
    assert projected.compactable is False


def test_provider_anchor_projection_rejects_a_different_estimator() -> None:
    current_surface = measure_replay_context_surface([])
    snapshot = ContextUsageSnapshot(
        tokens=7,
        context_window=100,
        reserve_tokens=0,
        source="estimated",
        compactable=True,
    )
    anchor = ProviderContextAnchor(
        invocation_id="invocation-1",
        attempt=1,
        model_input_snapshot_id="snapshot-1",
        provider_prompt_tokens=80,
        sampled_prepared_payload_hash="sha256:" + "a" * 64,
        sampled_surface_tokens=5,
        sampled_surface_fingerprint="sha256:" + "b" * 64,
        source_revision=1,
        commit_revision=2,
        provider_id="provider-1",
        endpoint_id="endpoint-1",
        api_id="api-1",
        model_id="model-1",
        sampled_structural_envelope_fingerprint=_envelope_fingerprint(),
        estimator_id="different-estimator.v1",
    )

    projected = project_context_from_provider_anchor(
        snapshot,
        anchor,
        current_surface,
        structural_envelope_fingerprint=_envelope_fingerprint(),
    )

    assert projected.tokens == 7
    assert projected.source == "estimated"
    assert projected.compactable is True
    assert projected.provider_anchor == anchor


def test_provider_anchor_projection_rejects_a_changed_structural_envelope() -> None:
    current_surface = measure_replay_context_surface([])
    snapshot = ContextUsageSnapshot(
        tokens=7,
        context_window=100,
        reserve_tokens=0,
        source="estimated",
        compactable=True,
    )
    anchor = ProviderContextAnchor(
        invocation_id="invocation-1",
        attempt=1,
        model_input_snapshot_id="snapshot-1",
        provider_prompt_tokens=80,
        sampled_prepared_payload_hash="sha256:" + "a" * 64,
        sampled_surface_tokens=5,
        sampled_surface_fingerprint="sha256:" + "b" * 64,
        source_revision=1,
        commit_revision=2,
        provider_id="provider-1",
        endpoint_id="endpoint-1",
        api_id="api-1",
        model_id="model-1",
        sampled_structural_envelope_fingerprint=_envelope_fingerprint(),
    )

    projected = project_context_from_provider_anchor(
        snapshot,
        anchor,
        current_surface,
        structural_envelope_fingerprint=_envelope_fingerprint(
            system_prompt="changed system"
        ),
    )

    assert projected.tokens == 7
    assert projected.source == "estimated"
    assert projected.compactable is True
    assert projected.structural_envelope_status == "mismatched"


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
                sampled_structural_envelope_fingerprint=_envelope_fingerprint(),
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
    assert payload["providerAnchor"][
        "sampledStructuralEnvelopeFingerprint"
    ] == _envelope_fingerprint()


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
