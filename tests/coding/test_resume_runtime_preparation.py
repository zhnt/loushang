from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

import pytest

from loushang.coding.bootstrap import create_agent_session
from loushang.coding.resume_activation_attempt import (
    CodingActivationAttemptV1,
    CodingResumeRecoveryRequired,
    prepare_coding_activation_attempt_record,
)
from loushang.coding.resume_binding import project_coding_runtime_binding_path
from loushang.coding.session_manager import (
    _bind_owned_session_manager,
    _create_owned_session_factory,
)
from loushang.harness.conversation import StoreCommitOutcomeUnknown

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned Coding Writer")


@pytest.mark.parametrize("mode", [
    "committed", "unknown", "historical_only", "revoked", "wrong_attempt", "branch_changed",
    "revoked_during_bind",
])
def test_resume_runtime_prepares_only_for_a_definite_owned_intent(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))

    async def scenario():
        (tmp_path / "sessions").mkdir(mode=0o700)
        factory = _create_owned_session_factory()
        manager_type = _bind_owned_session_manager(factory)
        manager = await manager_type.new_with_composition(
            session_dir=tmp_path / "sessions", cwd=str(tmp_path),
            composition_set="coding-minimal", defer_materialization=False,
        )
        session = create_agent_session(session_manager=manager, composition_set="coding-minimal", no_tools=True)
        ancestry = project_coding_runtime_binding_path(
            manager.get_active_entries(), current_session_id=manager.header.conversation_id,
        ).ancestry_digest
        attempt = CodingActivationAttemptV1(
            attempt_id="attempt-1", request_id="input-1", session_id=manager.header.conversation_id,
            original_leaf_id=manager.leaf_id, ancestry_digest=ancestry,
            plan_fingerprint="a" * 64, epoch_fingerprint="b" * 64, subject_digest="c" * 64,
        )
        record = prepare_coding_activation_attempt_record(
            attempt, created_at=datetime(2026, 10, 12, tzinfo=UTC),
        )
        checks = []
        revoked = False

        def require_current_admission(observed):
            assert observed == attempt
            checks.append(attempt.attempt_id)
            if mode == "revoked" or revoked:
                raise PermissionError("current subject admission revoked")

        try:
            if mode == "unknown":
                store = manager._lifecycle_session.runtime_binding.store
                append = store.append

                async def lost_ack(*args, **kwargs):
                    await append(*args, **kwargs)
                    raise StoreCommitOutcomeUnknown("intent ack lost")

                monkeypatch.setattr(store, "append", lost_ack)
                with pytest.raises(StoreCommitOutcomeUnknown):
                    await manager._commit_resume_activation_intent(record)
            elif mode == "historical_only":
                await manager.commit_prebuilt_extension_data(record)
            else:
                await manager._commit_resume_activation_intent(record)
                if mode == "branch_changed":
                    manager.reset_leaf()
            path = manager.session_file
            assert path is not None
            before = path.read_bytes()
            if mode == "revoked_during_bind":
                bind = session._capability_graph_binder.bind

                async def revoke_after_bind(*args, **kwargs):
                    nonlocal revoked
                    result = await bind(*args, **kwargs)
                    revoked = True
                    return result

                monkeypatch.setattr(session._capability_graph_binder, "bind", revoke_after_bind)
            if mode == "committed":
                receipt = await session._prepare_resume_runtime_graph(
                    attempt_id=attempt.attempt_id, require_current_admission=require_current_admission,
                )
                assert receipt["setId"] == "coding-minimal"
                assert session._model_call_consumer is not None
                assert checks
                assert manager.resume_runtime_publication_pending
                assert not session.execution_available
                with pytest.raises(CodingResumeRecoveryRequired):
                    await session.prepare_model_call_runtime()
            else:
                expected = (PermissionError if mode.startswith("revoked") else ValueError
                            if mode == "wrong_attempt" else CodingResumeRecoveryRequired)
                with pytest.raises(expected):
                    await session._prepare_resume_runtime_graph(
                        attempt_id="other" if mode == "wrong_attempt" else attempt.attempt_id,
                        require_current_admission=require_current_admission,
                    )
                assert session._model_call_consumer is None
                if not mode.startswith("revoked"):
                    assert checks == []
                if mode == "revoked_during_bind":
                    assert session._execution_preparation_failed
                    assert not session.execution_available
                    revoked = False
                    with pytest.raises(RuntimeError, match="Session retirement"):
                        await session._prepare_resume_runtime_graph(
                            attempt_id=attempt.attempt_id,
                            require_current_admission=require_current_admission,
                        )
            assert path.read_bytes() == before
        finally:
            await session.dispose()
            await factory.close()

    asyncio.run(scenario())
