from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from loushang.ai.types import AssistantMessage, ImagePart, TextPart, Usage, UserMessage
from loushang.coding.composition_provenance import CodingCompositionProvenanceV1
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.resume_activation_attempt import (
    CodingActivationAttemptV1,
    CodingResumeRecoveryRequired,
    prepare_coding_activation_attempt_record,
    project_coding_activation_attempt_path,
    validate_coding_activation_attempt_record,
)
from loushang.coding.resume_binding import (
    CODING_RUNTIME_BINDING_METADATA_KEY,
    CodingRuntimeBindingV1,
    coding_user_payload_digest,
    inspect_coding_runtime_binding,
    prepare_coding_resume_user_record,
    project_coding_runtime_binding_path,
    validate_coding_runtime_binding_record,
)
from loushang.coding.resume_history import read_coding_resume_snapshot
from loushang.coding.resume_input_lookup import (
    CodingResumeInputLookupQueryV1,
    coding_resume_input_record_digest,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.conversation import StoreCommitOutcomeUnknown
from loushang.harness.conversation.repository import ConversationRepository
from loushang.harness.transcript.jsonl_file import load_agent_transcript_file
from loushang.harness.transcript.kinds import (
    CONTEXT_COMPACTION_CHECKPOINT_KIND,
    EXTENSION_DATA_KIND,
)
from loushang.harness.transcript.types import (
    ContextCompactionCheckpoint,
    ExtensionData,
    SessionImagePart,
)
from loushang.harness.transcript.writer import AgentTranscriptRecordFactory


def _binding() -> CodingRuntimeBindingV1:
    return CodingRuntimeBindingV1(
        attempt_id="attempt-1",
        input_id="input-1",
        record_id="record-1",
        session_id="session-1",
        original_leaf_id="leaf-1",
        ancestry_digest="a" * 64,
        subject_digest="b" * 64,
        origin_composition=CodingCompositionProvenanceV1("retired-set", "c" * 64),
        planned_fingerprint="d" * 64,
        actual_fingerprint="e" * 64,
        payload_digest="f" * 64,
        difference_codes=("plugin.changed", "policy.tightened"),
    )


async def _append_test_activation_attempt(
    manager: SessionManager,
    *, close_runtime_gate: bool = False,
) -> tuple[str, str | None, str]:
    original_leaf_id = manager.leaf_id
    ancestry = project_coding_runtime_binding_path(
        manager._transcript.active_path(),
        current_session_id=manager.header.conversation_id,
    ).ancestry_digest
    binding = _binding()
    attempt = CodingActivationAttemptV1(
        attempt_id=binding.attempt_id,
        request_id=binding.input_id,
        session_id=manager.header.conversation_id,
        original_leaf_id=original_leaf_id,
        ancestry_digest=ancestry,
        plan_fingerprint=binding.planned_fingerprint,
        epoch_fingerprint=binding.actual_fingerprint,
        subject_digest=binding.subject_digest,
        effect_classes=("plugin_activation",),
    )
    record = prepare_coding_activation_attempt_record(
        attempt, created_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    result = await (manager._commit_resume_activation_intent(record) if close_runtime_gate
                    else manager.commit_prebuilt_extension_data(record))
    assert result.disposition == "committed"
    return record.record_id, original_leaf_id, ancestry


@pytest.mark.parametrize("outcome", ["committed", "unknown", "failed", "cancelled"])
def test_resume_intent_closes_runtime_gate_before_commit_and_keeps_it_closed(
    tmp_path, monkeypatch, outcome,
):
    async def scenario():
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            defer_materialization=False,
        )
        store = manager._lifecycle_session.runtime_binding.store
        append = store.append
        entered, release = asyncio.Event(), asyncio.Event()

        async def held(*args, **kwargs):
            entered.set()
            await release.wait()
            if outcome == "unknown":
                await append(*args, **kwargs)
                raise StoreCommitOutcomeUnknown("intent ack lost")
            if outcome == "failed":
                raise OSError("intent write failed")
            return await append(*args, **kwargs)

        monkeypatch.setattr(store, "append", held)
        task = asyncio.create_task(_append_test_activation_attempt(manager, close_runtime_gate=True))
        entering = asyncio.create_task(entered.wait())
        try:
            await asyncio.wait((task, entering), return_when=asyncio.FIRST_COMPLETED)
            if not entered.is_set():
                await task
            assert manager.resume_runtime_publication_pending
            with pytest.raises(CodingResumeRecoveryRequired, match="runtime.publication_pending"):
                manager.require_no_unsettled_resume_activation()
            with pytest.raises(CodingResumeRecoveryRequired):
                await manager.append_message(UserMessage(role="user", content="racing input", timestamp=1.0))
            if outcome == "cancelled":
                assert task.cancel()
            release.set()
            if outcome in {"committed", "cancelled"}:
                await task
                if outcome == "cancelled":
                    # The original commit owner settles its durable operation
                    # atomically even when the caller requests cancellation.
                    assert manager.leaf_id == "attempt-1"
                    assert len(manager.get_entries()) == 1
            else:
                expected = {"unknown": StoreCommitOutcomeUnknown, "failed": OSError}[outcome]
                with pytest.raises(expected):
                    await task
            assert manager.resume_runtime_publication_pending
            with pytest.raises(CodingResumeRecoveryRequired):
                manager.require_no_unsettled_resume_activation()
        finally:
            release.set()
            entering.cancel()
            await asyncio.gather(entering, return_exceptions=True)
            await asyncio.gather(task, return_exceptions=True)
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


@pytest.mark.parametrize("changed", ["session", "leaf", "ancestry", "metadata"])
def test_resume_intent_rejects_changed_history_before_closing_gate(tmp_path, changed):
    async def scenario():
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            defer_materialization=False,
        )
        ancestry = project_coding_runtime_binding_path(
            manager._transcript.active_path(), current_session_id="session-1",
        ).ancestry_digest
        attempt = CodingActivationAttemptV1(
            attempt_id="attempt-1", request_id="input-1",
            session_id="other" if changed == "session" else "session-1",
            original_leaf_id="other" if changed == "leaf" else None,
            ancestry_digest="a" * 64 if changed == "ancestry" else ancestry,
            plan_fingerprint="b" * 64, epoch_fingerprint="c" * 64, subject_digest="d" * 64,
        )
        record = prepare_coding_activation_attempt_record(
            attempt, created_at=datetime(2026, 10, 12, tzinfo=UTC),
        )
        if changed == "metadata":
            record = replace(record, metadata={"extra": "unadmitted"})
        try:
            with pytest.raises(ValueError, match="differs"):
                await manager._commit_resume_activation_intent(record)
            assert not manager.resume_runtime_publication_pending
            assert manager.get_entries() == []
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


def test_activation_attempt_is_a_bounded_fixed_id_historical_fact() -> None:
    attempt = CodingActivationAttemptV1(
        attempt_id="attempt-1", request_id="input-1", session_id="session-1",
        original_leaf_id="leaf-1", ancestry_digest="a" * 64,
        plan_fingerprint="b" * 64, epoch_fingerprint="c" * 64,
        subject_digest="d" * 64, effect_classes=("plugin_activation",),
    )
    record = prepare_coding_activation_attempt_record(
        attempt, created_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    assert record.record_id == attempt.attempt_id
    assert record.parent_id == attempt.original_leaf_id
    assert validate_coding_activation_attempt_record(record) == attempt
    with pytest.raises(ValueError, match="identity or parent"):
        validate_coding_activation_attempt_record(replace(record, parent_id=None))
    with pytest.raises(ValueError, match="fields"):
        validate_coding_activation_attempt_record(replace(
            record, payload=replace(record.payload, data={"version": 1}),
        ))


def test_activation_attempt_lost_ack_reconciles_from_jsonl_after_restart(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            defer_materialization=False,
        )
        ancestry = project_coding_runtime_binding_path(
            manager._transcript.active_path(), current_session_id="session-1",
        ).ancestry_digest
        binding = _binding()
        attempt = CodingActivationAttemptV1(
            attempt_id=binding.attempt_id, request_id=binding.input_id,
            session_id="session-1", original_leaf_id=None,
            ancestry_digest=ancestry,
            plan_fingerprint=binding.planned_fingerprint,
            epoch_fingerprint=binding.actual_fingerprint,
            subject_digest=binding.subject_digest,
        )
        record = prepare_coding_activation_attempt_record(
            attempt, created_at=datetime(2026, 10, 12, tzinfo=UTC),
        )
        path = manager.session_file
        assert path is not None
        store = manager._lifecycle_session.runtime_binding.store
        original_append = store.append

        async def lost_ack(*args, **kwargs):
            await original_append(*args, **kwargs)
            raise StoreCommitOutcomeUnknown("ack lost after durable append")

        try:
            monkeypatch.setattr(store, "append", lost_ack)
            with pytest.raises(StoreCommitOutcomeUnknown):
                await manager.commit_prebuilt_extension_data(record)
            with pytest.raises(StoreCommitOutcomeUnknown, match="authoritative reload"):
                await manager.commit_prebuilt_extension_data(record)
        finally:
            await manager.dispose_runtime_profile()

        restored = await SessionManager.load(path)
        try:
            result = await restored.commit_prebuilt_extension_data(record)
            assert result.disposition == "already_committed"
            assert restored.leaf_id == record.record_id
        finally:
            await restored.dispose_runtime_profile()
        _, records = load_agent_transcript_file(path, read_only=True)
        assert records == [record]

    asyncio.run(scenario())


def test_selected_path_keeps_unbound_activation_attempt_pending(tmp_path) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            defer_materialization=False,
        )
        message = UserMessage(role="user", content="continue", timestamp=1.0)
        try:
            intent_id, original_leaf_id, ancestry = await _append_test_activation_attempt(
                manager
            )
            selected = manager._transcript.active_path()
            pending = project_coding_activation_attempt_path(
                selected, current_session_id="session-1",
            )
            assert pending.status == "pending"
            assert pending.record_id == intent_id
            assert pending.attempt is not None
            assert pending.attempt.request_id == "input-1"
            assert project_coding_activation_attempt_path(
                selected, current_session_id="fork-session",
            ).status == "none"

            binding = replace(
                _binding(), original_leaf_id=original_leaf_id,
                ancestry_digest=ancestry,
                payload_digest=coding_user_payload_digest(message),
            )
            record = prepare_coding_resume_user_record(
                binding, message, commit_parent_id=intent_id,
                created_at=datetime(2026, 10, 12, tzinfo=UTC),
            )
            with pytest.raises(ValueError, match="does not match intent"):
                project_coding_activation_attempt_path(
                    (*selected, replace(record, metadata={
                        **record.metadata,
                        **replace(
                            binding, planned_fingerprint="1" * 64,
                        ).to_message_metadata(),
                    })),
                    current_session_id="session-1",
                )
            await manager.commit_prebuilt_user_message(record)
            completed = project_coding_activation_attempt_path(
                manager._transcript.active_path(), current_session_id="session-1",
            )
            assert completed.status == "none"
            assert completed.attempt is None
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


def test_staged_resume_cannot_skip_an_earlier_unbound_attempt(tmp_path) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            defer_materialization=False,
        )
        try:
            first_id, _, _ = await _append_test_activation_attempt(manager)
            ancestry = project_coding_runtime_binding_path(
                manager._transcript.active_path(), current_session_id="session-1",
            ).ancestry_digest
            second = CodingActivationAttemptV1(
                attempt_id="attempt-2", request_id="input-2", session_id="session-1",
                original_leaf_id=first_id, ancestry_digest=ancestry,
                plan_fingerprint="d" * 64, epoch_fingerprint="e" * 64,
                subject_digest="b" * 64,
            )
            await manager.commit_prebuilt_extension_data(
                prepare_coding_activation_attempt_record(
                    second, created_at=datetime(2026, 10, 12, tzinfo=UTC),
                )
            )
            with pytest.raises(ValueError, match="unresolved attempt"):
                manager._stage_resume_first_user_input(
                    UserMessage(role="user", content="continue", timestamp=1.0),
                    prepare_binding=lambda _message: _binding(),
                    created_at=datetime(2026, 10, 12, tzinfo=UTC),
                    original_leaf_id=first_id,
                    ancestry_digest=ancestry,
                    attempt_id="attempt-2",
                )
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


def test_ordinary_writable_resume_cannot_cross_an_unbound_attempt(tmp_path) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new_with_composition(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            composition_set="coding-standard", defer_materialization=False,
        )
        try:
            manager.bind_new_composition_plan(
                resolve_coding_composition_set("coding-standard")
            )
            await _append_test_activation_attempt(manager)
            with pytest.raises(CodingResumeRecoveryRequired) as error:
                manager.bind_new_composition_plan(
                    resolve_coding_composition_set("coding-standard")
                )
            assert error.value.reason_code == "history.activation_pending"
            with pytest.raises(CodingResumeRecoveryRequired):
                await manager.append_message(
                    UserMessage(role="user", content="continue", timestamp=1.0)
                )
            assert len(manager.get_entries()) == 1
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["pending", "unknown_version", "invalid"])
def test_reopened_jsonl_retains_activation_quarantine_and_readonly_history(
    tmp_path, status: str,
) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new_with_composition(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            composition_set="coding-standard", defer_materialization=False,
        )
        try:
            if status == "pending":
                await _append_test_activation_attempt(manager)
            else:
                version = 3 if status == "unknown_version" else 1
                await manager.append_extension_data(
                    f"coding.activation-attempt/v{version}", {"version": version},
                )
            path = manager.session_file
            assert path is not None
            original_bytes = path.read_bytes()
            original_leaf = manager.leaf_id
        finally:
            await manager.dispose_runtime_profile()

        preview = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
        assert preview.activation_status == status
        assert preview.header_preview.header.conversation_id == "session-1"
        assert preview.selected_leaf_id == original_leaf
        assert len(preview.selected_records) == 1

        restored = await SessionManager.load(path)
        try:
            assert restored.header.conversation_id == "session-1"
            with pytest.raises(CodingResumeRecoveryRequired) as error:
                restored.require_no_unsettled_resume_activation()
            assert error.value.reason_code == f"history.activation_{status}"
            with pytest.raises(CodingResumeRecoveryRequired):
                await restored.append_message(
                    UserMessage(role="user", content="continue", timestamp=1.0)
                )
            assert restored.leaf_id == original_leaf
            assert len(restored.get_entries()) == 1
        finally:
            await restored.dispose_runtime_profile()
        assert path.read_bytes() == original_bytes

    asyncio.run(scenario())


def test_unbound_attempt_stops_bootstrap_before_product_factory_selection(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding import bootstrap

    def forbidden_factory(*args, **kwargs):
        pytest.fail("unresolved Resume reached Product runtime factory selection")

    monkeypatch.setattr(
        bootstrap, "_select_direct_coding_product_factory", forbidden_factory,
    )

    async def scenario() -> None:
        manager = await SessionManager.new_with_composition(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            composition_set="coding-standard", defer_materialization=False,
        )
        try:
            await _append_test_activation_attempt(manager)
            with pytest.raises(CodingResumeRecoveryRequired):
                bootstrap.create_agent_session(session_manager=manager)
            with pytest.raises(CodingResumeRecoveryRequired):
                bootstrap._build_with_package_product_selection(
                    SimpleNamespace(factory_for_session=forbidden_factory),
                    manager,
                    SimpleNamespace(),
                    forbidden_factory,
                )
            assert len(manager.get_entries()) == 1
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


def test_unbound_attempt_stops_model_preparation_before_runtime_effects(tmp_path) -> None:
    from loushang.coding.session.agent_session import AgentSession

    class PreparationSentinel:
        def __init__(self, manager: SessionManager) -> None:
            self._coding_session_manager = manager

        def __getattr__(self, name: str):
            pytest.fail(f"unresolved Resume reached runtime preparation: {name}")

    async def scenario() -> None:
        manager = await SessionManager.new_with_composition(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            composition_set="coding-standard", defer_materialization=False,
        )
        try:
            await _append_test_activation_attempt(manager)
            with pytest.raises(CodingResumeRecoveryRequired):
                await AgentSession.prepare_model_call_runtime(PreparationSentinel(manager))
            assert len(manager.get_entries()) == 1
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


def test_binding_metadata_on_ordinary_commit_invalidates_the_history_guard(tmp_path) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new_with_composition(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            composition_set="coding-standard", defer_materialization=False,
        )
        try:
            await manager.append_message(
                AssistantMessage(
                    role="assistant", content=[], api="anthropic-messages",
                    provider="offline", model="offline", endpoint="offline",
                    response_id=None, stop_reason="stop", error_message=None,
                    usage=Usage(
                        input=0, output=0, cache_read=0, cache_write=0,
                        total_tokens=0, cost={},
                    ),
                    timestamp=0.0,
                ),
                metadata={"coding.runtimeBindingV1": {"version": 2}},
            )
            with pytest.raises(CodingResumeRecoveryRequired) as error:
                manager.require_no_unsettled_resume_activation()
            assert error.value.reason_code == "history.activation_invalid"
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


def test_unknown_activation_attempt_version_is_inert_but_blocks_new_plan() -> None:
    future = AgentTranscriptRecordFactory(
        clock=lambda: datetime(2026, 10, 12, tzinfo=UTC),
        id_factory=lambda: "future-attempt",
    ).create(
        EXTENSION_DATA_KIND,
        ExtensionData("coding.activation-attempt/v2", {"version": 2}),
        parent_id=None,
    )
    projection = project_coding_activation_attempt_path(
        (future,), current_session_id="session-1",
    )
    assert projection.status == "unknown_version"
    assert projection.attempt is None


def test_runtime_binding_round_trip_keeps_historical_origin_and_bounded_metadata() -> None:
    binding = _binding()
    metadata = binding.to_message_metadata()

    observation = inspect_coding_runtime_binding(metadata)

    assert observation.status == "known"
    assert observation.binding == binding
    assert tuple(metadata) == (CODING_RUNTIME_BINDING_METADATA_KEY,)
    assert len(str(metadata).encode()) < 4096
    assert "retired-set" in str(metadata)
    assert "Credential" not in str(metadata)


def test_runtime_binding_preserves_legacy_unknown_and_unknown_schema_is_inert() -> None:
    binding = replace(_binding(), origin_composition=None, difference_codes=())
    metadata = binding.to_message_metadata()
    assert metadata[CODING_RUNTIME_BINDING_METADATA_KEY]["originEvidence"] == {
        "kind": "legacy_unknown"
    }
    assert inspect_coding_runtime_binding(metadata).binding == binding
    assert inspect_coding_runtime_binding({}).status == "absent"

    unknown = {CODING_RUNTIME_BINDING_METADATA_KEY: {"version": 2, "future": "value"}}
    result = inspect_coding_runtime_binding(unknown)
    assert result.status == "unknown_version"
    assert result.binding is None
    assert unknown[CODING_RUNTIME_BINDING_METADATA_KEY] == {
        "version": 2,
        "future": "value",
    }


@pytest.mark.parametrize(
    "change",
    [
        {"attempt_id": "contains spaces"},
        {"ancestry_digest": "A" * 64},
        {"difference_codes": ("permission=full_access",)},
        {"difference_codes": tuple(f"change.{index}" for index in range(17))},
        {"origin_composition": CodingCompositionProvenanceV1("x" * 4096, "c" * 64)},
    ],
)
def test_runtime_binding_rejects_unbounded_or_non_redacted_fields(change) -> None:
    with pytest.raises((TypeError, ValueError)):
        replace(_binding(), **change)


def test_runtime_binding_rejects_malformed_known_schema_without_authorizing_it() -> None:
    metadata = _binding().to_message_metadata()
    raw = dict(metadata[CODING_RUNTIME_BINDING_METADATA_KEY])
    raw["extraGrant"] = "full_access"
    with pytest.raises(ValueError):
        inspect_coding_runtime_binding({CODING_RUNTIME_BINDING_METADATA_KEY: raw})


def test_binding_and_resource_evidence_share_one_validated_user_record() -> None:
    message = UserMessage(role="user", content="continue", timestamp=1.0)
    binding = replace(_binding(), payload_digest=coding_user_payload_digest(message))
    record = prepare_coding_resume_user_record(
        binding,
        message,
        commit_parent_id="activation-intent-1",
        created_at=datetime(2026, 10, 12, tzinfo=UTC),
        resource_metadata={"loushang.request.resource_evidence": {"schemaVersion": 1}},
    )

    assert record.record_id == binding.record_id
    assert record.parent_id == "activation-intent-1"
    assert set(record.metadata) == {
        CODING_RUNTIME_BINDING_METADATA_KEY,
        "loushang.request.resource_evidence",
    }
    assert validate_coding_runtime_binding_record(
        record, expected_session_id=binding.session_id,
    ) == binding
    with pytest.raises(ValueError, match="payload digest"):
        validate_coding_runtime_binding_record(
            replace(record, payload=replace(message, content="changed")),
            expected_session_id=binding.session_id,
        )
    with pytest.raises(ValueError, match="metadata key conflict"):
        prepare_coding_resume_user_record(
            binding,
            message,
            commit_parent_id=None,
            created_at=datetime(2026, 10, 12, tzinfo=UTC),
            resource_metadata={CODING_RUNTIME_BINDING_METADATA_KEY: {}},
        )


def test_runtime_binding_and_resource_evidence_survive_one_jsonl_commit(tmp_path) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            defer_materialization=False,
        )
        try:
            message = UserMessage(role="user", content="continue", timestamp=1.0)
            binding = replace(
                _binding(),
                session_id=manager.header.conversation_id,
                original_leaf_id=manager.leaf_id,
                payload_digest=coding_user_payload_digest(message),
            )
            record = prepare_coding_resume_user_record(
                binding,
                message,
                commit_parent_id=manager.leaf_id,
                created_at=datetime(2026, 10, 12, tzinfo=UTC),
                resource_metadata={
                    "loushang.request.resource_evidence": {"schemaVersion": 1}
                },
            )
            first = await manager.commit_prebuilt_user_message(record)
            duplicate = await manager.commit_prebuilt_user_message(record)
            assert first.disposition == "committed"
            assert duplicate.disposition == "already_committed"
            path = manager.session_file
            assert path is not None
        finally:
            await manager.dispose_runtime_profile()

        _, records = load_agent_transcript_file(path, read_only=True)
        assert len(records) == 1
        assert records[0].metadata["loushang.request.resource_evidence"] == {
            "schemaVersion": 1
        }
        assert validate_coding_runtime_binding_record(
            records[0], expected_session_id=binding.session_id,
        ) == binding

    asyncio.run(scenario())


def test_resume_user_commit_externalizes_image_before_binding_payload_digest(
    tmp_path,
) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            defer_materialization=False,
        )
        message = UserMessage(
            role="user",
            content=[ImagePart(
                type="image", mime_type="image/png",
                data=base64.b64encode(b"resume-image").decode("ascii"),
            )],
            timestamp=1.0,
        )
        try:
            def prepare(persisted: UserMessage):
                assert isinstance(persisted.content, list)
                assert isinstance(persisted.content[0], SessionImagePart)
                binding = replace(
                    _binding(),
                    session_id=manager.header.conversation_id,
                    original_leaf_id=manager.leaf_id,
                    payload_digest=coding_user_payload_digest(persisted),
                )
                return prepare_coding_resume_user_record(
                    binding, persisted,
                    commit_parent_id=manager.leaf_id,
                    created_at=datetime(2026, 10, 12, tzinfo=UTC),
                    resource_metadata={"loushang.request.resource_evidence": {
                        "schemaVersion": 1,
                    }},
                )

            result = await manager.commit_prebuilt_user_message_from_message(
                message, prepare_record=prepare,
            )
            assert result.disposition == "committed"
            path = manager.session_file
            assert path is not None
        finally:
            await manager.dispose_runtime_profile()

        _, records = load_agent_transcript_file(path, read_only=True)
        assert len(records) == 1
        assert isinstance(records[0].payload.content, list)
        assert isinstance(records[0].payload.content[0], SessionImagePart)
        assert validate_coding_runtime_binding_record(
            records[0], expected_session_id=manager.header.conversation_id,
        ).payload_digest == coding_user_payload_digest(records[0].payload)
        assert records[0].metadata["loushang.request.resource_evidence"] == {
            "schemaVersion": 1,
        }

    asyncio.run(scenario())


def test_staged_resume_rejects_mutation_of_the_original_message_list(tmp_path) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            defer_materialization=False,
        )
        content = [TextPart(type="text", text="original")]
        message = UserMessage(role="user", content=content, timestamp=1.0)
        try:
            _, original_leaf_id, ancestry = await _append_test_activation_attempt(manager)
            manager._stage_resume_first_user_input(
                message,
                prepare_binding=lambda persisted: replace(
                    _binding(), original_leaf_id=original_leaf_id,
                    ancestry_digest=ancestry,
                    payload_digest=coding_user_payload_digest(persisted),
                ),
                created_at=datetime(2026, 10, 12, tzinfo=UTC),
                original_leaf_id=original_leaf_id, ancestry_digest=ancestry,
                attempt_id="attempt-1",
            )
            content[0] = TextPart(type="text", text="mutated after admission")
            with pytest.raises(ValueError, match="differs from the staged input"):
                await manager.append_message(message)
            assert len(manager.get_entries()) == 1
            assert manager.leaf_id == "attempt-1"
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


def test_staged_resume_commit_uses_frozen_input_after_async_boundary(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            defer_materialization=False,
        )
        content = [TextPart(type="text", text="original")]
        message = UserMessage(role="user", content=content, timestamp=1.0)
        original_commit = manager.commit_prebuilt_user_message_from_message
        evidence = {"schemaVersion": 1}

        async def mutate_caller_input_then_commit(admitted_message, **kwargs):
            content[0] = TextPart(type="text", text="mutated during async commit")
            evidence["schemaVersion"] = 2
            return await original_commit(admitted_message, **kwargs)

        monkeypatch.setattr(
            manager, "commit_prebuilt_user_message_from_message",
            mutate_caller_input_then_commit,
        )
        try:
            _, original_leaf_id, ancestry = await _append_test_activation_attempt(manager)
            manager._stage_resume_first_user_input(
                message,
                prepare_binding=lambda persisted: replace(
                    _binding(), original_leaf_id=original_leaf_id,
                    ancestry_digest=ancestry,
                    payload_digest=coding_user_payload_digest(persisted),
                ),
                created_at=datetime(2026, 10, 12, tzinfo=UTC),
                original_leaf_id=original_leaf_id, ancestry_digest=ancestry,
                attempt_id="attempt-1",
            )
            await manager.append_message(
                message, metadata={"loushang.request.resource_evidence": evidence},
            )
            persisted = manager.get_leaf_entry()
            assert persisted is not None
            assert persisted.payload.content == [TextPart(type="text", text="original")]
            assert persisted.metadata["loushang.request.resource_evidence"] == {
                "schemaVersion": 1,
            }
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


def test_staged_resume_retry_requires_the_original_resource_metadata(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            defer_materialization=False,
        )
        message = UserMessage(role="user", content="original", timestamp=1.0)
        original_commit = manager.commit_prebuilt_user_message_from_message
        fail_before_prepare = True

        async def fail_once_before_record_prepare(admitted_message, **kwargs):
            nonlocal fail_before_prepare
            if fail_before_prepare:
                fail_before_prepare = False
                raise RuntimeError("failed before preparing the record")
            return await original_commit(admitted_message, **kwargs)

        monkeypatch.setattr(
            manager, "commit_prebuilt_user_message_from_message",
            fail_once_before_record_prepare,
        )
        try:
            _, original_leaf_id, ancestry = await _append_test_activation_attempt(manager)
            manager._stage_resume_first_user_input(
                message,
                prepare_binding=lambda persisted: replace(
                    _binding(), original_leaf_id=original_leaf_id,
                    ancestry_digest=ancestry,
                    payload_digest=coding_user_payload_digest(persisted),
                ),
                created_at=datetime(2026, 10, 12, tzinfo=UTC),
                original_leaf_id=original_leaf_id, ancestry_digest=ancestry,
                attempt_id="attempt-1",
            )
            with pytest.raises(RuntimeError, match="before preparing"):
                await manager.append_message(message, metadata={"evidence": "original"})
            with pytest.raises(ValueError, match="no prepared record"):
                await manager._lookup_resume_first_user_input(request_id="input-1")
            with pytest.raises(ValueError, match="metadata changed after admission"):
                await manager.append_message(message, metadata={"evidence": "changed"})
            assert len(manager.get_entries()) == 1
            await manager.append_message(message, metadata={"evidence": "original"})
            assert len(manager.get_entries()) == 2
            persisted = manager.get_leaf_entry()
            assert persisted is not None
            assert persisted.metadata["evidence"] == "original"
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


def test_staged_resume_first_input_uses_the_session_append_path(tmp_path) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            session_id="session-1",
            defer_materialization=False,
        )
        message = UserMessage(role="user", content="continue", timestamp=1.0)
        try:
            intent_id, original_leaf_id, ancestry = (
                await _append_test_activation_attempt(manager, close_runtime_gate=True)
            )
            manager._stage_resume_first_user_input(
                message,
                prepare_binding=lambda persisted: replace(
                    _binding(),
                    original_leaf_id=original_leaf_id,
                    ancestry_digest=ancestry,
                    payload_digest=coding_user_payload_digest(persisted),
                ),
                created_at=datetime(2026, 10, 12, tzinfo=UTC),
                original_leaf_id=original_leaf_id,
                ancestry_digest=ancestry,
                attempt_id="attempt-1",
            )
            with pytest.raises(ValueError, match="differs from the staged input"):
                await manager.append_message(replace(message, content="other"))
            record_id = await manager.append_message(
                message,
                metadata={"loushang.request.resource_evidence": {
                    "schemaVersion": 1,
                }},
            )
            assert record_id == "record-1"
            assert manager.leaf_id == record_id
            # A bound historical attempt is settled input evidence, while live
            # Runtime publication is still a separate, uncompleted phase.
            assert project_coding_activation_attempt_path(
                manager._transcript.active_path(), current_session_id="session-1",
            ).status == "none"
            manager._activation_guard_snapshot = (manager._transcript.revision, manager.leaf_id)
            with pytest.raises(CodingResumeRecoveryRequired, match="runtime.publication_pending"):
                manager.require_no_unsettled_resume_activation()
            with pytest.raises(CodingResumeRecoveryRequired, match="runtime.publication_pending"):
                manager.mark_composition_startup_prepared()
            with pytest.raises(CodingResumeRecoveryRequired, match="runtime.publication_pending"):
                await manager.append_message(UserMessage(role="user", content="next", timestamp=2.0))
            from loushang.coding.session import AgentSession

            with pytest.raises(CodingResumeRecoveryRequired, match="runtime.publication_pending"):
                await AgentSession.prepare_model_call_runtime(SimpleNamespace(_coding_session_manager=manager))
            inert = object.__new__(AgentSession)
            inert._coding_session_manager = manager
            # Each boundary fails before it can reach extension hooks, shell
            # services, or compaction setup; the inert binding has none of them.
            with pytest.raises(CodingResumeRecoveryRequired, match="runtime.publication_pending"):
                await AgentSession._before_bash(inert, None)
            with pytest.raises(CodingResumeRecoveryRequired, match="runtime.publication_pending"):
                await AgentSession._exec_command_from_extension(inert, "forbidden-command")
            with pytest.raises(CodingResumeRecoveryRequired, match="runtime.publication_pending"):
                await AgentSession.compact(inert)
            binding = object.__new__(AgentSession)
            binding._coding_session_manager = manager
            assert binding.execution_available is False
            assert len(manager.get_entries()) == 2
            path = manager.session_file
            assert path is not None
        finally:
            await manager.dispose_runtime_profile()

        _, records = load_agent_transcript_file(path, read_only=True)
        assert len(records) == 2
        assert validate_coding_runtime_binding_record(
            records[1], expected_session_id="session-1",
        ).ancestry_digest == ancestry
        assert records[1].parent_id == intent_id
        assert records[1].metadata["loushang.request.resource_evidence"] == {
            "schemaVersion": 1,
        }

    asyncio.run(scenario())


def test_staged_resume_first_input_rejects_changed_transcript_revision(tmp_path) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            session_id="session-1",
            defer_materialization=False,
        )
        message = UserMessage(role="user", content="continue", timestamp=1.0)
        try:
            _, original_leaf_id, ancestry = await _append_test_activation_attempt(manager)
            manager._stage_resume_first_user_input(
                message,
                prepare_binding=lambda _persisted: _binding(),
                created_at=datetime(2026, 10, 12, tzinfo=UTC),
                original_leaf_id=original_leaf_id,
                ancestry_digest=ancestry,
                attempt_id="attempt-1",
            )
            await manager.append_custom_entry("test.revision", {"version": 1})
            with pytest.raises(ValueError, match="selected transcript branch changed"):
                await manager.append_message(message)
            assert len(manager.get_entries()) == 2
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


def test_reopened_bound_input_continues_with_a_fresh_current_runtime(
    tmp_path,
) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            defer_materialization=False,
        )
        message = UserMessage(role="user", content="continue", timestamp=1.0)
        try:
            _, original_leaf_id, ancestry = await _append_test_activation_attempt(
                manager, close_runtime_gate=True,
            )
            manager._stage_resume_first_user_input(
                message,
                prepare_binding=lambda persisted: replace(
                    _binding(), original_leaf_id=original_leaf_id,
                    ancestry_digest=ancestry,
                    payload_digest=coding_user_payload_digest(persisted),
                ),
                created_at=datetime(2026, 10, 12, tzinfo=UTC),
                original_leaf_id=original_leaf_id, ancestry_digest=ancestry,
                attempt_id="attempt-1",
            )
            await manager.append_message(message)
            path = manager.session_file
            assert path is not None
        finally:
            await manager.dispose_runtime_profile()

        before = path.read_bytes()
        restored = await SessionManager.load(path)

        try:
            assert project_coding_activation_attempt_path(
                restored._transcript.active_path(), current_session_id="session-1",
            ).status == "none"
            assert read_coding_resume_snapshot(path, max_bytes=1024 * 1024).binding_status == "bound"
            restored.require_no_unsettled_resume_activation()
            await restored.append_message(
                UserMessage(role="user", content="next", timestamp=2.0)
            )
            assert len(restored.get_entries()) == 3
            assert restored.get_leaf_entry().payload.content == "next"
        finally:
            await restored.dispose_runtime_profile()
        assert path.read_bytes().startswith(before)

    asyncio.run(scenario())


@pytest.mark.parametrize("mismatch", [
    {"input_id": "different-request"},
    {"planned_fingerprint": "1" * 64},
    {"actual_fingerprint": "2" * 64},
    {"subject_digest": "3" * 64},
])
def test_staged_resume_first_input_rejects_changed_activation_identity(
    tmp_path, mismatch,
) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            defer_materialization=False,
        )
        message = UserMessage(role="user", content="continue", timestamp=1.0)
        try:
            _, original_leaf_id, ancestry = await _append_test_activation_attempt(manager)
            manager._stage_resume_first_user_input(
                message,
                prepare_binding=lambda persisted: replace(
                    _binding(), original_leaf_id=original_leaf_id,
                    ancestry_digest=ancestry,
                    payload_digest=coding_user_payload_digest(persisted),
                    **mismatch,
                ),
                created_at=datetime(2026, 10, 12, tzinfo=UTC),
                original_leaf_id=original_leaf_id,
                ancestry_digest=ancestry,
                attempt_id="attempt-1",
            )
            with pytest.raises(ValueError, match="binding differs"):
                await manager.append_message(message)
            assert len(manager.get_entries()) == 1
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


def test_staged_resume_first_input_does_not_replay_after_lost_ack(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=str(tmp_path),
            session_id="session-1",
            defer_materialization=False,
        )
        message = UserMessage(role="user", content="continue", timestamp=1.0)
        try:
            _, original_leaf_id, ancestry = await _append_test_activation_attempt(manager)
            manager._stage_resume_first_user_input(
                message,
                prepare_binding=lambda persisted: replace(
                    _binding(), original_leaf_id=original_leaf_id,
                    ancestry_digest=ancestry,
                    payload_digest=coding_user_payload_digest(persisted),
                ),
                created_at=datetime(2026, 10, 12, tzinfo=UTC),
                original_leaf_id=original_leaf_id,
                ancestry_digest=ancestry,
                attempt_id="attempt-1",
            )
            store = manager._lifecycle_session.runtime_binding.store
            original = store.append
            calls = 0

            async def lost_ack(*args, **kwargs):
                nonlocal calls
                calls += 1
                await original(*args, **kwargs)
                raise StoreCommitOutcomeUnknown("ack lost after durable append")

            monkeypatch.setattr(store, "append", lost_ack)
            with pytest.raises(StoreCommitOutcomeUnknown):
                await manager.append_message(message)
            first_attempt_calls = calls
            before_lookup = manager.session_file.read_bytes()
            before_target = (manager._transcript.revision, manager.leaf_id)
            for _ in range(2):
                observed = await manager._lookup_resume_first_user_input(request_id="input-1")
                assert observed.status == "committed"
                assert observed.record_id == "record-1"
            pending = manager._resume_first_input
            assert pending is not None and pending.prepared_record is not None
            query = CodingResumeInputLookupQueryV1(
                "input-1", coding_resume_input_record_digest(pending.prepared_record),
            )
            assert (await manager.lookup_resume_input(query)).status == "committed"
            assert manager.session_file.read_bytes() == before_lookup
            assert (manager._transcript.revision, manager.leaf_id) == before_target
            path = manager.session_file
            try:
                with path.open("ab") as stream:
                    stream.write(b'{"incomplete":')
                assert (await manager._lookup_resume_first_user_input(
                    request_id="input-1",
                )).status == "unknown"
            finally:
                path.write_bytes(before_lookup)
            try:
                path.unlink()
                assert (await manager._lookup_resume_first_user_input(
                    request_id="input-1",
                )).status == "unknown"
            finally:
                path.write_bytes(before_lookup)
            assert calls == first_attempt_calls
            assert (manager._transcript.revision, manager.leaf_id) == before_target
            with pytest.raises(ValueError, match="request identity differs"):
                await manager._lookup_resume_first_user_input(request_id="different-request")
            with pytest.raises(StoreCommitOutcomeUnknown, match="authoritative reload"):
                await manager.append_message(message)
            assert calls == first_attempt_calls
            path = manager.session_file
            assert path is not None
        finally:
            await manager.dispose_runtime_profile()

        _, records = load_agent_transcript_file(path, read_only=True)
        assert len(records) == 2
        assert records[1].record_id == "record-1"

    asyncio.run(scenario())


def test_runtime_binding_projection_tracks_selected_branch_across_compaction() -> None:
    message = UserMessage(role="user", content="continue", timestamp=1.0)
    first = AgentTranscriptRecordFactory(
        clock=lambda: datetime(2026, 10, 12, tzinfo=UTC),
        id_factory=lambda: "initial",
    ).create("agent.message", message, parent_id=None)
    binding = replace(
        _binding(), original_leaf_id=first.record_id,
        payload_digest=coding_user_payload_digest(message),
    )
    bound = prepare_coding_resume_user_record(
        binding, message, commit_parent_id=first.record_id,
        created_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    checkpoint = AgentTranscriptRecordFactory(
        clock=lambda: datetime(2026, 10, 12, tzinfo=UTC),
        id_factory=lambda: "checkpoint",
    ).create(
        CONTEXT_COMPACTION_CHECKPOINT_KIND,
        ContextCompactionCheckpoint(
            summary="earlier context", first_kept_record_id=bound.record_id,
            tokens_before=100,
        ),
        parent_id=bound.record_id,
    )
    alternate = replace(checkpoint, record_id="alternate", parent_id=first.record_id)
    repository = ConversationRepository.create(
        header=None, records=(first, bound, checkpoint, alternate),
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
        leaf_id=checkpoint.record_id,
    )

    projected = project_coding_runtime_binding_path(
        repository.active_records(), current_session_id=binding.session_id,
    )
    assert projected.status == "bound"
    assert projected.binding == binding
    assert projected.record_id == bound.record_id
    assert len(projected.ancestry_digest) == 64

    repository.branch(alternate.record_id)
    alternate_projection = project_coding_runtime_binding_path(
        repository.active_records(), current_session_id=binding.session_id,
    )
    assert alternate_projection.status == "none"
    assert alternate_projection.ancestry_digest != projected.ancestry_digest


def test_runtime_binding_projection_does_not_inherit_fork_origin() -> None:
    message = UserMessage(role="user", content="continue", timestamp=1.0)
    binding = replace(
        _binding(), original_leaf_id=None,
        payload_digest=coding_user_payload_digest(message),
    )
    source_record = prepare_coding_resume_user_record(
        binding, message, commit_parent_id=None,
        created_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    assert project_coding_runtime_binding_path(
        (source_record,), current_session_id="fork-session",
    ).status == "none"
    target_binding = replace(
        binding, record_id="target-record", session_id="fork-session",
        original_leaf_id=source_record.record_id,
    )
    target_record = prepare_coding_resume_user_record(
        target_binding, message, commit_parent_id=source_record.record_id,
        created_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    assert project_coding_runtime_binding_path(
        (source_record, target_record), current_session_id="fork-session",
    ).binding == target_binding


def test_runtime_binding_projection_fails_closed_on_unknown_or_corrupt_path() -> None:
    message = UserMessage(role="user", content="continue", timestamp=1.0)
    binding = replace(
        _binding(), original_leaf_id=None,
        payload_digest=coding_user_payload_digest(message),
    )
    bound = prepare_coding_resume_user_record(
        binding, message, commit_parent_id=None,
        created_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    unknown = replace(
        bound, record_id="future", parent_id=bound.record_id,
        metadata={CODING_RUNTIME_BINDING_METADATA_KEY: {"version": 2}},
    )
    projected = project_coding_runtime_binding_path(
        (bound, unknown), current_session_id=binding.session_id,
    )
    assert projected.status == "unknown_version"
    assert projected.binding is None
    assert projected.record_id == unknown.record_id
    assert len(projected.ancestry_digest) == 64

    later_binding = replace(
        binding, record_id="later", original_leaf_id=unknown.record_id,
    )
    later = prepare_coding_resume_user_record(
        later_binding, message, commit_parent_id=unknown.record_id,
        created_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    later_projection = project_coding_runtime_binding_path(
        (bound, unknown, later), current_session_id=binding.session_id,
    )
    assert later_projection.status == "unknown_version"
    assert later_projection.binding is None
    assert later_projection.record_id == unknown.record_id

    with pytest.raises(ValueError, match="payload digest"):
        project_coding_runtime_binding_path(
            (replace(bound, payload=replace(message, content="tampered")),),
            current_session_id=binding.session_id,
        )
    with pytest.raises(ValueError, match="complete parent-linked"):
        project_coding_runtime_binding_path(
            (unknown,), current_session_id=binding.session_id,
        )
    with pytest.raises(ValueError, match="agent UserMessage"):
        project_coding_runtime_binding_path(
            (replace(bound, kind=CONTEXT_COMPACTION_CHECKPOINT_KIND),),
            current_session_id=binding.session_id,
        )
