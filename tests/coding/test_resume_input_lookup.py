from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from loushang.ai.types import UserMessage
from loushang.coding.resume_binding import (
    CodingRuntimeBindingV1,
    coding_user_payload_digest,
    prepare_coding_resume_user_record,
    project_coding_runtime_binding_path,
)
from loushang.coding.resume_input_lookup import (
    CodingResumeInputLookupQueryV1,
    coding_resume_input_record_digest,
)
from loushang.coding.session_manager import SessionManager


def _record(manager, *, record_id="record-1", text="continue"):
    message = UserMessage(role="user", content=text, timestamp=1.0)
    ancestry = project_coding_runtime_binding_path(
        manager._transcript.active_path(), current_session_id="session-1",
    ).ancestry_digest
    return prepare_coding_resume_user_record(
        CodingRuntimeBindingV1(
            attempt_id="attempt-1", input_id="input-1", record_id=record_id,
            session_id="session-1", original_leaf_id=manager.leaf_id,
            ancestry_digest=ancestry, subject_digest="a" * 64,
            origin_composition=None, planned_fingerprint="b" * 64,
            actual_fingerprint="c" * 64, payload_digest=coding_user_payload_digest(message),
        ),
        message, commit_parent_id=manager.leaf_id,
        created_at=datetime(2026, 10, 12, tzinfo=UTC),
        resource_metadata={"evidence": {"version": 1}},
    )


def test_logical_resume_input_lookup_survives_restart_without_a_ledger(tmp_path) -> None:
    async def scenario():
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            defer_materialization=False,
        )
        try:
            record = _record(manager)
            query = CodingResumeInputLookupQueryV1("input-1", coding_resume_input_record_digest(record))
            # A missing local record cannot prove that another service did not
            # commit it, even when this process has no submission ledger.
            assert (await manager.lookup_resume_input(query)).status == "unknown"
            await manager.commit_prebuilt_user_message(record)
            assert (await manager.lookup_resume_input(query)).status == "committed"
            path = manager.session_file
            assert path is not None
        finally:
            await manager.dispose_runtime_profile()
        restored = await SessionManager.load(path)
        try:
            before = path.read_bytes()
            target = (restored.leaf_id, restored._transcript.revision)
            observed = await restored.lookup_resume_input(query)
            assert observed.input_id == "input-1"
            assert observed.record_id == "record-1"
            assert observed.status == "committed"
            assert (await restored.lookup_resume_input(replace(query, record_digest="d" * 64))).status == "conflict"
            assert (await restored.lookup_resume_input(replace(query, input_id="missing"))).status == "unknown"
            assert path.read_bytes() == before
            assert (restored.leaf_id, restored._transcript.revision) == target
            with path.open("ab") as stream:
                stream.write(b'{"incomplete":')
            assert (await restored.lookup_resume_input(query)).status == "unknown"
        finally:
            await restored.dispose_runtime_profile()

    asyncio.run(scenario())


def test_logical_resume_input_lookup_rejects_duplicate_selected_identity(tmp_path) -> None:
    async def scenario():
        manager = await SessionManager.new(
            session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1",
            defer_materialization=False,
        )
        try:
            record = _record(manager)
            query = CodingResumeInputLookupQueryV1("input-1", coding_resume_input_record_digest(record))
            await manager.commit_prebuilt_user_message(record)
            await manager.commit_prebuilt_user_message(_record(manager, record_id="record-2", text="other"))
            assert (await manager.lookup_resume_input(query)).status == "conflict"
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


def test_resume_input_record_digest_covers_complete_metadata_and_target(tmp_path) -> None:
    async def scenario():
        manager = await SessionManager.new(session_dir=tmp_path, cwd=str(tmp_path), session_id="session-1")
        try:
            record = _record(manager)
            digest = coding_resume_input_record_digest(record)
            for changed in (
                replace(record, parent_id="other-parent"),
                replace(record, metadata={**record.metadata, "evidence": {"version": 2}}),
                replace(record, payload=replace(record.payload, timestamp=2.0)),
            ):
                assert coding_resume_input_record_digest(changed) != digest
        finally:
            await manager.dispose_runtime_profile()

    asyncio.run(scenario())


@pytest.mark.parametrize("input_id,digest", [("invalid id", "a" * 64), ("input-1", "raw-secret")])
def test_resume_input_lookup_query_rejects_invalid_identity(input_id, digest) -> None:
    with pytest.raises(ValueError):
        CodingResumeInputLookupQueryV1(input_id, digest)
