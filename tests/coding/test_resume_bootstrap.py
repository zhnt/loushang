from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

import pytest

from loushang.ai.types import UserMessage
from loushang.coding import bootstrap
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.resume_activation_attempt import (
    CodingActivationAttemptV1,
    CodingResumeRecoveryRequired,
    prepare_coding_activation_attempt_record,
)
from loushang.coding.resume_activation_plan import build_session_activation_plan
from loushang.coding.resume_history import read_coding_resume_snapshot
from loushang.coding.session_manager import (
    SessionManager,
    _bind_owned_session_manager,
    _create_owned_session_factory,
)
from loushang.harness.conversation import StoreCommitOutcomeUnknown

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned Coding Writer")


@pytest.mark.parametrize("mode", [
    "legacy", "changed", "denied", "wrong_composition", "revoked_after_construction",
    "invalid_admission", "unknown_intent", "cleanup_failed_after_construction",
])
def test_resume_bootstrap_uses_current_plan_without_rewriting_original_header(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))

    async def scenario():
        if mode == "changed":
            original = await SessionManager.new_with_composition(
                session_dir=tmp_path / "sessions", cwd=str(tmp_path),
                composition_set="coding-standard", defer_materialization=False,
            )
            original_session = bootstrap.create_agent_session(
                session_manager=original, composition_set="coding-standard", no_tools=True,
            )
            await original_session.prepare_model_call_runtime()
        else:
            original = await SessionManager.new(
                session_dir=tmp_path / "sessions", cwd=str(tmp_path), defer_materialization=False,
            )
        await original.append_message(UserMessage(role="user", content="old history", timestamp=1.0))
        path = original.session_file
        header = original.header
        if mode == "changed":
            await original_session.dispose()
        else:
            await original.dispose_runtime_profile()
        assert path is not None
        history = read_coding_resume_snapshot(path, max_bytes=1024 * 1024)
        current = resolve_coding_composition_set("coding-minimal")
        plan = build_session_activation_plan(history, current, workspace_root=tmp_path)
        factory = _create_owned_session_factory()
        manager_type = _bind_owned_session_manager(factory)
        resumed = await manager_type._load_resume_writer(path, plan=plan, current_owner_inputs=())
        session = None
        attempt = CodingActivationAttemptV1(
            attempt_id="attempt-1", request_id="input-1", session_id=header.conversation_id,
            original_leaf_id=plan.selected_leaf_id, ancestry_digest=plan.ancestry_digest,
            plan_fingerprint=plan.plan_id, epoch_fingerprint="a" * 64, subject_digest="b" * 64,
        )
        calls = []
        revoked = False
        cleanup_debt = None
        constructed = []
        native_dispose = bootstrap.AgentSession.dispose

        def admit(observed):
            assert observed == attempt
            calls.append(observed.attempt_id)
            if mode == "denied" or revoked:
                raise PermissionError("current subject revoked")
            if mode == "invalid_admission":
                return True

        try:
            intent = prepare_coding_activation_attempt_record(
                attempt, created_at=datetime(2026, 10, 12, tzinfo=UTC),
            )
            if mode == "unknown_intent":
                store = resumed._lifecycle_session.runtime_binding.store
                append = store.append

                async def lose_ack(*args, **kwargs):
                    await append(*args, **kwargs)
                    raise StoreCommitOutcomeUnknown("intent acknowledgement lost")

                monkeypatch.setattr(store, "append", lose_ack)
                with pytest.raises(StoreCommitOutcomeUnknown):
                    await resumed._commit_resume_activation_intent(intent)
            else:
                await resumed._commit_resume_activation_intent(intent)
            before = path.read_bytes()
            with pytest.raises(CodingResumeRecoveryRequired):
                bootstrap.create_agent_session(session_manager=resumed, composition_set="coding-minimal")
            if mode in {"revoked_after_construction", "cleanup_failed_after_construction"}:
                construct = bootstrap._create_agent_session

                def revoke_after_construct(**kwargs):
                    nonlocal revoked
                    candidate = construct(**kwargs)
                    constructed.append(candidate)
                    revoked = True
                    return candidate

                monkeypatch.setattr(bootstrap, "_create_agent_session", revoke_after_construct)
                if mode == "cleanup_failed_after_construction":
                    failures = []

                    async def fail_dispose_once(candidate, *args, **kwargs):
                        if not failures:
                            failures.append(candidate)
                            raise OSError("native candidate cleanup failed")
                        await native_dispose(candidate, *args, **kwargs)

                    monkeypatch.setattr(bootstrap.AgentSession, "dispose", fail_dispose_once)
            if mode in {
                "denied", "wrong_composition", "revoked_after_construction",
                "invalid_admission", "unknown_intent", "cleanup_failed_after_construction",
            }:
                expected = (
                    RuntimeError if mode == "cleanup_failed_after_construction"
                    else PermissionError if mode in {"denied", "revoked_after_construction"}
                    else TypeError if mode == "invalid_admission"
                    else CodingResumeRecoveryRequired if mode == "unknown_intent" else ValueError
                )
                with pytest.raises(expected) as failed:
                    await bootstrap._create_resume_agent_session(
                        session_manager=resumed, attempt_id=attempt.attempt_id,
                        composition_set=resolve_coding_composition_set(
                            "coding-standard" if mode == "wrong_composition" else "coding-minimal"
                        ), require_current_admission=admit, no_tools=True,
                    )
                if mode in {"wrong_composition", "unknown_intent"}:
                    assert not calls
                if mode == "revoked_after_construction":
                    assert resumed._lifecycle_session._disposed
                    assert factory.pending_preparations == ()
                if mode == "cleanup_failed_after_construction":
                    cleanup_debt = failed.value
                    assert cleanup_debt.original_owner is constructed[0]
                    assert isinstance(cleanup_debt.original_error, PermissionError)
                    assert isinstance(cleanup_debt.cleanup_error, OSError)
                    assert factory._closing
                    await cleanup_debt.retry_cleanup()
                    assert resumed._lifecycle_session._disposed
                    assert factory.pending_preparations == ()
            else:
                session = await bootstrap._create_resume_agent_session(
                    session_manager=resumed, attempt_id=attempt.attempt_id,
                    composition_set=current, require_current_admission=admit, no_tools=True,
                )
                assert calls
                assert session._coding_composition_plan == current
                assert not session.execution_available
                receipt = await session._prepare_resume_runtime_graph(
                    attempt_id=attempt.attempt_id, require_current_admission=admit,
                )
                assert receipt["setId"] == "coding-minimal"
                assert not session.execution_available
            assert resumed.header == header
            assert path.read_bytes() == before
        finally:
            if constructed:
                await native_dispose(constructed[0])
            if session is not None:
                await session.dispose()
            else:
                await resumed.dispose_runtime_profile()
            await factory.close()

    asyncio.run(scenario())
