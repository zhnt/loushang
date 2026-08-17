from __future__ import annotations

import asyncio

import pytest

from loushang.harness.conversation import ConversationHeader, MemoryConversationStore
from loushang.harness.transcript import (
    TURN_AWARE_SUMMARY_IMPLEMENTATION,
    AgentTranscriptLifecycleContext,
    AgentTranscriptProfile,
    AgentTranscriptProfileRuntime,
    AgentTranscriptRuntimeSpec,
)


def _runtime(product_id: str = "research") -> AgentTranscriptProfileRuntime:
    return AgentTranscriptProfileRuntime(
        AgentTranscriptRuntimeSpec(
            product_id=product_id,
            product_name=product_id.title(),
            metadata_key="runtimeProfile",
            memory_namespace=f"{product_id}.memory",
            memory_store_implementation=f"{product_id}.memory",
            file_store_implementation=f"{product_id}.file",
            transcript_profile_implementation=f"{product_id}.agent_transcript",
        )
    )


def _context(tmp_path) -> AgentTranscriptLifecycleContext:
    return AgentTranscriptLifecycleContext(
        session_dir=tmp_path,
        cwd="/workspace",
        persist=False,
        header=ConversationHeader(
            conversation_id="research-session",
            version=1,
            created_at="2026-07-23T00:00:00Z",
        ),
    )


def test_product_runtime_binds_existing_agent_transcript_components(tmp_path) -> None:
    async def scenario() -> None:
        runtime = _runtime()
        profile = runtime.resolve(persist=False)
        binding = await runtime.bind_lifecycle(_context(tmp_path), profile)

        assert isinstance(binding.store, MemoryConversationStore)
        assert isinstance(binding.profile, AgentTranscriptProfile)
        assert binding.key.namespace == "research.memory"
        assert binding.key.conversation_id == "research-session"
        assert (
            binding.product_binding.value("context.compaction").implementation
            == TURN_AWARE_SUMMARY_IMPLEMENTATION
        )

        await binding.dispose()

    asyncio.run(scenario())


def test_product_runtime_round_trips_its_snapshot_metadata() -> None:
    runtime = _runtime()
    profile = runtime.resolve(persist=True)

    metadata = runtime.snapshot_metadata(profile)

    assert runtime.read_snapshot(metadata) == profile.snapshot()
    assert (
        runtime.validate_snapshot(metadata, profile, require_current=True)
        == profile.snapshot()
    )


def test_product_runtime_accepts_pre_release_current_format_alias() -> None:
    runtime = _runtime()
    profile = runtime.resolve(persist=True)
    metadata = runtime.snapshot_metadata(profile)
    persisted = metadata["runtimeProfile"]
    assert isinstance(persisted, dict)
    transcript = next(
        capability
        for capability in persisted["capabilities"]
        if capability["slot"] == "agent.transcript_profile"
    )
    transcript["selections"][0]["config"] = {"format": "current"}

    restored = runtime.validate_snapshot(metadata, profile, require_current=True)

    assert restored is not None
    assert (
        restored.capabilities[1].selections[0].config
        == {"format": "current"}
    )


def test_product_runtime_accepts_legacy_snapshot_without_variation_semantics() -> None:
    runtime = _runtime()
    profile = runtime.resolve(persist=True)
    metadata = runtime.snapshot_metadata(profile)
    persisted = metadata["runtimeProfile"]
    assert isinstance(persisted, dict)
    capabilities = persisted["capabilities"]
    assert isinstance(capabilities, list)
    for capability in capabilities:
        assert isinstance(capability, dict)
        capability.pop("variationSemantic")

    restored = runtime.validate_snapshot(metadata, profile, require_current=True)

    assert restored is not None
    assert all(
        capability.variation_semantic is None
        for capability in restored.capabilities
    )


def test_product_runtime_rejects_another_products_snapshot() -> None:
    research = _runtime("research")
    design = _runtime("design")
    metadata = design.snapshot_metadata(design.resolve(persist=False))

    with pytest.raises(ValueError, match="Research cannot resume"):
        research.read_snapshot(metadata)
