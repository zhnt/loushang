from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from loushang.ai.types import UserMessage
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.product_plan import CODING_CAPABILITY_PROFILE_METADATA_KEY
from loushang.coding.resume_activation_attempt import (
    CodingActivationAttemptV1,
    CodingResumeRecoveryRequired,
    prepare_coding_activation_attempt_record,
)
from loushang.coding.resume_activation_plan import (
    ResumePlanStaleError,
    build_session_activation_plan,
)
from loushang.coding.resume_binding import (
    CodingRuntimeBindingV1,
    coding_user_payload_digest,
    validate_coding_runtime_binding_record,
)
from loushang.coding.resume_history import read_coding_resume_snapshot
from loushang.coding.session_manager import (
    SessionManager,
    _bind_owned_session_manager,
    _create_owned_session_factory,
)
from loushang.harness.transcript.jsonl_file import write_agent_transcript_export
from loushang.harness.transcript.writer_lease import TranscriptWriterError


def test_resume_writer_uses_the_verified_selected_branch_without_rewriting_history(tmp_path):
    async def scenario():
        original = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(tmp_path), defer_materialization=False,
        )
        first = await original.append_message(UserMessage(role="user", content="selected", timestamp=1.0))
        sibling = await original.append_message(UserMessage(role="user", content="other branch", timestamp=2.0))
        path = original.session_file
        header = original.header
        await original.dispose_runtime_profile()
        assert path is not None
        before = path.read_bytes()
        history = read_coding_resume_snapshot(path, max_bytes=1024 * 1024, selected_leaf_id=first)
        assert history.selected_leaf_id != sibling
        plan = build_session_activation_plan(
            history, resolve_coding_composition_set("coding-standard"), workspace_root=tmp_path,
        )
        factory = _create_owned_session_factory()
        manager_type = _bind_owned_session_manager(factory)
        manager = None
        try:
            manager = await manager_type._load_resume_writer(path, plan=plan, current_owner_inputs=())
            assert manager.leaf_id == first
            assert tuple(manager.get_active_entries()) == history.selected_records
            assert len(manager.get_entries()) == 2
            assert path.read_bytes() == before
            assert manager.header == header
            assert manager.resume_runtime_publication_pending
            attempt = CodingActivationAttemptV1(
                attempt_id="selected-attempt", request_id="input-1",
                session_id=header.conversation_id, original_leaf_id=first,
                ancestry_digest=plan.ancestry_digest, plan_fingerprint=plan.plan_id,
                epoch_fingerprint="a" * 64, subject_digest="b" * 64,
            )
            intent = prepare_coding_activation_attempt_record(
                attempt, created_at=datetime(2026, 10, 12, tzinfo=UTC),
            )
            manager.branch(sibling)
            with pytest.raises(ValueError, match="selected history"):
                await manager._commit_resume_activation_intent(intent)
            assert path.read_bytes() == before
            assert manager.resume_runtime_publication_pending
            manager.branch(first)
            await manager._commit_resume_activation_intent(intent)
            assert manager.get_leaf_entry().parent_id == first
            assert sibling not in {record.record_id for record in manager.get_active_entries()}
            assert len(manager.get_entries()) == 3
            assert path.read_bytes().startswith(before)
        finally:
            if manager is not None:
                await manager.dispose_runtime_profile()
            await factory.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("capability_changed", [False, True])
def test_resume_writer_retains_legacy_id_header_and_original_exclusive_owner(tmp_path, capability_changed):
    async def scenario():
        root = tmp_path / "sessions"
        original = await SessionManager.new(
            session_dir=root, cwd=str(tmp_path), session_id="legacy-session",
            defer_materialization=False,
        )
        await original.append_message(UserMessage(role="user", content="history", timestamp=1.0))
        path = original.session_file
        header = original.header
        records = original.get_entries()
        await original.dispose_runtime_profile()
        assert path is not None
        if capability_changed:
            header = replace(header, metadata={
                **header.metadata,
                CODING_CAPABILITY_PROFILE_METADATA_KEY: {
                    "schemaVersion": 1, "productId": "coding", "capabilities": [],
                },
            })
            write_agent_transcript_export(path, header, records)
            reopened = await SessionManager.load(path)
            await reopened.dispose_runtime_profile()
        before = path.read_bytes()
        history = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
        plan = build_session_activation_plan(
            history, resolve_coding_composition_set("coding-standard"), workspace_root=tmp_path,
        )
        assert plan.composition_comparison.status == "legacy_unknown"
        factory = _create_owned_session_factory()
        manager_type = _bind_owned_session_manager(factory)
        resumed = None
        try:
            resumed = await manager_type._load_resume_writer(path, plan=plan, current_owner_inputs=())
            assert resumed.header == header
            assert resumed.header.conversation_id == "legacy-session"
            assert path.read_bytes() == before
            assert resumed.resume_runtime_publication_pending
            with pytest.raises(CodingResumeRecoveryRequired):
                await resumed.append_message(UserMessage(role="user", content="unadmitted", timestamp=2.0))
            with pytest.raises(TranscriptWriterError):
                await manager_type._load_resume_writer(path, plan=plan, current_owner_inputs=())
            assert factory.pending_preparations == ()
            attempt = CodingActivationAttemptV1(
                attempt_id="attempt-1", request_id="input-1", session_id="legacy-session",
                original_leaf_id=plan.selected_leaf_id, ancestry_digest=plan.ancestry_digest,
                plan_fingerprint=plan.plan_id, epoch_fingerprint="a" * 64,
                subject_digest="b" * 64,
            )
            record = prepare_coding_activation_attempt_record(
                attempt, created_at=datetime(2026, 10, 12, tzinfo=UTC),
            )
            wrong = prepare_coding_activation_attempt_record(
                replace(attempt, plan_fingerprint="c" * 64),
                created_at=datetime(2026, 10, 12, tzinfo=UTC),
            )
            with pytest.raises(ValueError, match="prepared Writer Plan"):
                await resumed._commit_resume_activation_intent(wrong)
            assert path.read_bytes() == before
            assert (await resumed._commit_resume_activation_intent(record)).disposition == "committed"
            assert resumed.resume_runtime_publication_pending
            assert resumed.leaf_id == "attempt-1"
            message = UserMessage(role="user", content="continue", timestamp=3.0)
            resumed._stage_resume_first_user_input(
                message,
                prepare_binding=lambda admitted: CodingRuntimeBindingV1(
                    attempt_id=attempt.attempt_id, input_id=attempt.request_id,
                    record_id="input-record-1", session_id=attempt.session_id,
                    original_leaf_id=attempt.original_leaf_id, ancestry_digest=attempt.ancestry_digest,
                    subject_digest=attempt.subject_digest, origin_composition=None,
                    planned_fingerprint=attempt.plan_fingerprint, actual_fingerprint=attempt.epoch_fingerprint,
                    payload_digest=coding_user_payload_digest(admitted),
                    difference_codes=plan.composition_comparison.difference_codes,
                ),
                created_at=datetime(2026, 10, 12, tzinfo=UTC), original_leaf_id=attempt.original_leaf_id,
                ancestry_digest=attempt.ancestry_digest, attempt_id=attempt.attempt_id,
            )
            assert await resumed.append_message(message, metadata={"evidence": "current-owner"}) == "input-record-1"
            persisted = resumed.get_leaf_entry()
            assert persisted.metadata["evidence"] == "current-owner"
            assert validate_coding_runtime_binding_record(
                persisted, expected_session_id="legacy-session",
            ).origin_composition is None
            assert len(resumed.get_entries()) == 3
            assert resumed.header == header
            assert resumed.resume_runtime_publication_pending
            with pytest.raises(CodingResumeRecoveryRequired):
                resumed.require_no_unsettled_resume_activation()
        finally:
            if resumed is not None:
                await resumed.dispose_runtime_profile()
            await factory.close()

    asyncio.run(scenario())


def test_resume_writer_discards_changed_source_and_releases_original_preparation(tmp_path, monkeypatch):
    async def scenario():
        original = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(tmp_path), defer_materialization=False,
        )
        path = original.session_file
        await original.dispose_runtime_profile()
        assert path is not None
        history = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
        current = resolve_coding_composition_set("coding-standard")
        plan = build_session_activation_plan(history, current, workspace_root=tmp_path)
        factory = _create_owned_session_factory()
        manager_type = _bind_owned_session_manager(factory)
        construct = factory._construct_owned

        async def change_before_acquisition(*args, **kwargs):
            writer = await SessionManager.load(path)
            try:
                await writer.append_message(UserMessage(role="user", content="racing writer", timestamp=2.0))
            finally:
                await writer.dispose_runtime_profile()
            return await construct(*args, **kwargs)

        monkeypatch.setattr(factory, "_construct_owned", change_before_acquisition)
        try:
            with pytest.raises(ResumePlanStaleError, match="during acquisition"):
                await manager_type._load_resume_writer(path, plan=plan, current_owner_inputs=())
            assert factory.pending_preparations == ()
            monkeypatch.setattr(factory, "_construct_owned", construct)
            changed = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
            refreshed = build_session_activation_plan(changed, current, workspace_root=tmp_path)
            acquired = await manager_type._load_resume_writer(path, plan=refreshed, current_owner_inputs=())
            try:
                assert len(acquired.get_entries()) == 1
                assert acquired.resume_runtime_publication_pending
            finally:
                await acquired.dispose_runtime_profile()
        finally:
            await factory.close()

    asyncio.run(scenario())
