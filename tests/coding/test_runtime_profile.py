from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.ai.types import UserMessage
from loushang.coding.bootstrap import create_agent_session
from loushang.coding.product_plan import (
    CODING_CAPABILITY_PROFILE,
    CODING_CAPABILITY_PROFILE_METADATA_KEY,
    CODING_RUNTIME_PROFILE_METADATA_KEY,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.conversation import FileConversationStore, MemoryConversationStore
from loushang.harness.runtime import SIDE_QUESTION_PROVIDER_SLOT, RuntimeProfileSnapshot
from loushang.harness.transcript import (
    TURN_AWARE_SUMMARY_IMPLEMENTATION,
    TURN_AWARE_SUMMARY_VERSION,
    AgentTranscriptCompactionCapability,
    AgentTranscriptProfile,
)
from loushang.harness.transcript.jsonl_file import (
    write_agent_transcript_export as write_session_file,
)


def _model() -> Model:
    return Model(
        id="profile-test",
        name="Profile Test",
        provider="test",
        endpoint="test",
        capabilities=Capabilities(context_window=128_000, max_tokens=4_096),
    )


def _durable_capability_snapshot() -> dict[str, object]:
    snapshot = CODING_CAPABILITY_PROFILE.snapshot()
    return replace(
        snapshot,
        capabilities=tuple(
            capability
            for capability in snapshot.capabilities
            if capability.slot != SIDE_QUESTION_PROVIDER_SLOT.key
        ),
    ).to_json()


def test_in_memory_session_binds_the_coding_runtime_profile_and_records_snapshot(
    tmp_path,
) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd="/tmp/project",
            persist=False,
        )
        snapshot = RuntimeProfileSnapshot.from_json(
            manager.header.metadata[CODING_RUNTIME_PROFILE_METADATA_KEY]
        )
        capability_snapshot = RuntimeProfileSnapshot.from_json(
            manager.header.metadata[CODING_CAPABILITY_PROFILE_METADATA_KEY]
        )

        assert manager.runtime_profile.product_id == "coding"
        assert snapshot.to_json() == manager.runtime_profile.snapshot().to_json()
        assert capability_snapshot.to_json() == _durable_capability_snapshot()
        assert isinstance(
            manager.get_runtime_capability("conversation.store"),
            MemoryConversationStore,
        )
        assert isinstance(
            manager.get_runtime_capability("agent.transcript_profile"),
            AgentTranscriptProfile,
        )
        assert isinstance(
            manager.get_runtime_capability("context.compaction"),
            AgentTranscriptCompactionCapability,
        )
        assert manager._transcript._profile is manager.get_runtime_capability(
            "agent.transcript_profile"
        )

        await manager.dispose_runtime_profile()
        with pytest.raises(RuntimeError, match="closed"):
            manager.get_runtime_capability("conversation.store")

    asyncio.run(scenario())


def test_persistent_session_resumes_the_snapshotted_file_profile(tmp_path) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd="/tmp/project",
            persist=True,
        )
        assert manager.session_file is not None
        assert isinstance(
            manager.get_runtime_capability("conversation.store"),
            FileConversationStore,
        )
        await manager.append_message(
            UserMessage(role="user", content="materialize", timestamp=0.0)
        )
        expected_snapshot = manager.runtime_profile.snapshot().to_json()
        expected_capability_snapshot = _durable_capability_snapshot()

        resumed = await SessionManager.load(manager.session_file, persist=True)

        assert resumed.runtime_profile.snapshot().to_json() == expected_snapshot
        assert (
            RuntimeProfileSnapshot.from_json(
                resumed.header.metadata[CODING_RUNTIME_PROFILE_METADATA_KEY]
            ).to_json()
            == expected_snapshot
        )
        assert (
            RuntimeProfileSnapshot.from_json(
                resumed.header.metadata[CODING_CAPABILITY_PROFILE_METADATA_KEY]
            ).to_json()
            == expected_capability_snapshot
        )
        assert isinstance(
            resumed.get_runtime_capability("conversation.store"),
            FileConversationStore,
        )

        await manager.dispose_runtime_profile()
        await resumed.dispose_runtime_profile()

    asyncio.run(scenario())


def test_persistent_session_accepts_snapshot_without_auxiliary_side_question(
    tmp_path,
) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd="/tmp/project",
            persist=True,
        )
        assert manager.session_file is not None
        await manager.append_message(
            UserMessage(role="user", content="materialize", timestamp=0.0)
        )
        capability_snapshot = dict(
            manager.header.metadata[CODING_CAPABILITY_PROFILE_METADATA_KEY]
        )
        capabilities = capability_snapshot["capabilities"]
        assert isinstance(capabilities, list)
        capability_snapshot["capabilities"] = [
            capability
            for capability in capabilities
            if isinstance(capability, dict)
            and capability.get("slot") != "interaction.side_question"
        ]
        header = replace(
            manager.header,
            metadata={
                **manager.header.metadata,
                CODING_CAPABILITY_PROFILE_METADATA_KEY: capability_snapshot,
            },
        )
        write_session_file(manager.session_file, header, manager.get_entries())
        await manager.dispose_runtime_profile()

        resumed = await SessionManager.load(manager.session_file, persist=True)
        await resumed.dispose_runtime_profile()

    asyncio.run(scenario())


def test_persistent_session_accepts_legacy_capability_semantic_snapshot(
    tmp_path,
) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd="/tmp/project",
            persist=True,
        )
        assert manager.session_file is not None
        await manager.append_message(
            UserMessage(role="user", content="materialize", timestamp=0.0)
        )
        metadata = deepcopy(dict(manager.header.metadata))
        for metadata_key in (
            CODING_RUNTIME_PROFILE_METADATA_KEY,
            CODING_CAPABILITY_PROFILE_METADATA_KEY,
        ):
            snapshot = metadata[metadata_key]
            assert isinstance(snapshot, dict)
            capabilities = snapshot["capabilities"]
            assert isinstance(capabilities, list)
            for capability in capabilities:
                assert isinstance(capability, dict)
                capability.pop("variationSemantic")
                if capability["slot"] in {
                    "prompt.sections",
                    "tool.packs",
                    "command.packs",
                }:
                    capability["shape"] = "ordered"
        header = replace(manager.header, metadata=metadata)
        write_session_file(manager.session_file, header, manager.get_entries())
        await manager.dispose_runtime_profile()

        resumed = await SessionManager.load(manager.session_file, persist=True)
        await resumed.dispose_runtime_profile()

    asyncio.run(scenario())


def test_persistent_session_rejects_a_different_capability_profile(tmp_path) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd="/tmp/project",
            persist=True,
        )
        assert manager.session_file is not None
        header = replace(
            manager.header,
            metadata={
                **manager.header.metadata,
                CODING_CAPABILITY_PROFILE_METADATA_KEY: {
                    "schemaVersion": 1,
                    "productId": "coding",
                    "capabilities": [],
                },
            },
        )
        write_session_file(manager.session_file, header, manager.get_entries())
        await manager.dispose_runtime_profile()

        with pytest.raises(ValueError, match="unsupported capability profile"):
            await SessionManager.load(manager.session_file, persist=True)

    asyncio.run(scenario())


def test_nonpersistent_open_uses_memory_without_rewriting_file_profile(
    tmp_path,
) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd="/tmp/project",
            persist=True,
        )
        assert manager.session_file is not None
        persisted_snapshot = manager.header.metadata[
            CODING_RUNTIME_PROFILE_METADATA_KEY
        ]
        await manager.append_message(
            UserMessage(role="user", content="materialize", timestamp=0.0)
        )

        transient = await SessionManager.load(manager.session_file, persist=False)

        assert isinstance(
            transient.get_runtime_capability("conversation.store"),
            MemoryConversationStore,
        )
        assert (
            transient.header.metadata[CODING_RUNTIME_PROFILE_METADATA_KEY]
            == persisted_snapshot
        )

        await manager.dispose_runtime_profile()
        await transient.dispose_runtime_profile()

    asyncio.run(scenario())


def test_agent_session_uses_and_disposes_selected_compaction_runtime(tmp_path) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            persist=False,
        )
        compaction_capability = manager.get_runtime_capability("context.compaction")
        assert isinstance(compaction_capability, AgentTranscriptCompactionCapability)
        assert compaction_capability.implementation == TURN_AWARE_SUMMARY_IMPLEMENTATION
        assert (
            compaction_capability.implementation_version == TURN_AWARE_SUMMARY_VERSION
        )

        session = create_agent_session(session_manager=manager, model=_model())
        capability_runtime = session._capability_runtime

        mirrored_runtime_names = {
            "_bash_runtime",
            "_command_controller",
            "_compaction_capability",
            "_compaction_runtime",
            "_diagnostics_bridge",
            "_extension_binding",
            "_extension_event_sink",
            "_extension_input_runtime",
            "_extension_message_controller",
            "_identity_binding",
            "_maintenance_binding",
            "_model_binding",
            "_navigation_runtime",
            "_resource_refresh_runtime",
            "_resource_watch_controller",
            "_retry_runtime",
            "_selection_runtime",
            "_session_inspector",
            "_session_runtime",
            "_tool_controller",
        }
        assert mirrored_runtime_names.isdisjoint(vars(session))
        assert session._composition.compaction_capability is compaction_capability
        assert (
            session._composition.compaction_runtime._get_policy()
            == compaction_capability.policy
        )
        assert capability_runtime is not None
        assert (
            session._composition.tool_controller.prompt_section_composer
            is capability_runtime.prompt_section_composer
        )
        assert (
            session._composition.command_controller.pack_composer
            is capability_runtime.command_pack_composer
        )

        await session.dispose()
        assert capability_runtime.binding.is_closed
        with pytest.raises(RuntimeError, match="closed"):
            manager.get_runtime_capability("context.compaction")

    asyncio.run(scenario())
