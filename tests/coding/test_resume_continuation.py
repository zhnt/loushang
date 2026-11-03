from __future__ import annotations

import asyncio
import hashlib
import sys
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from loushang.ai.types import UserMessage
from loushang.coding import bootstrap
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.package_product_runtime import (
    CodingFencedProductApplicationSelection,
)
from loushang.coding.resume_activation_attempt import (
    CodingActivationAttemptV1,
    CodingResumeRecoveryRequired,
)
from loushang.coding.resume_activation_plan import build_session_activation_plan
from loushang.coding.resume_continuation import prepare_coding_resume_continuation
from loushang.coding.resume_history import read_coding_resume_snapshot
from loushang.coding.resume_input_lookup import coding_resume_input_record_digest
from loushang.coding.resume_model_outcome import observe_coding_resume_model_outcome
from loushang.coding.resume_permission_confirmation import (
    CodingResumePermissionConfirmation,
    coding_resume_permission_request,
)
from loushang.coding.session.agent_session import AgentSession
from loushang.coding.session_manager import (
    SessionManager,
    _bind_owned_session_manager,
    _create_owned_session_factory,
)
from loushang.harness.approval import DenyApprovalResolver, InteractiveApprovalResolver
from loushang.harness.conversation import StoreCommitOutcomeUnknown
from loushang.harness.session.prompt_controller import PromptController
from loushang.harness.session.request_evidence import RESOURCE_EVIDENCE_METADATA_KEY
from loushang.harness.transcript import user_message_text
from loushang.harness.transcript.jsonl_file import load_agent_transcript_file

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned Resume Writer")


@pytest.mark.parametrize("mode", ["published", "published_application_owner", "application_owner_revoked", "published_duplicate", "denied", "graph_revoked", "preflight_revoked", "preflight_cancelled", "unsettled", "commit_unknown", "publication_revoked", "cleanup_failed", "bootstrap_cleanup_failed", "identity_delivery_failed"])
def test_canonical_resume_continuation_uses_original_owners_in_order(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))

    async def scenario():
        original = await SessionManager.new(session_dir=tmp_path / "sessions", cwd=str(tmp_path), defer_materialization=False)
        await original.append_message(UserMessage(role="user", content="history", timestamp=1.0))
        path = original.session_file
        header = original.header
        await original.dispose_runtime_profile()
        assert path is not None
        skill = tmp_path / "skills" / "review" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: review\ndescription: Review source\n---\nReview actual source bytes.\n")
        (tmp_path / "AGENTS.md").write_text("Project guidance\n")
        plan = build_session_activation_plan(read_coding_resume_snapshot(path, max_bytes=1024 * 1024), resolve_coding_composition_set("coding-standard"), workspace_root=tmp_path)
        attempt = CodingActivationAttemptV1(
            attempt_id="attempt-1", request_id="input-1", session_id=header.conversation_id,
            original_leaf_id=plan.selected_leaf_id, ancestry_digest=plan.ancestry_digest,
            plan_fingerprint=plan.plan_id, epoch_fingerprint="a" * 64, subject_digest="b" * 64,
        )
        factory = _create_owned_session_factory()
        manager_type = _bind_owned_session_manager(factory)
        application_selection = CodingFencedProductApplicationSelection() if mode in {
            "published_application_owner", "application_owner_revoked",
        } else None
        selected_factories = []
        if application_selection is not None:
            select = application_selection.factory_for_session

            def borrow(manager, **kwargs):
                assert manager is managers[0]
                assert manager._require_resume_runtime_preparation(attempt.attempt_id) == attempt
                selected = select(manager, **kwargs)
                selected_factories.append(selected)
                if mode == "application_owner_revoked":
                    owner.release_confirmation(fact)
                return selected

            monkeypatch.setattr(application_selection, "factory_for_session", borrow)

            def reject_second_selection(*args, **kwargs):
                pytest.fail("Resume must borrow the application's original Product owner")

            monkeypatch.setattr(bootstrap, "_select_direct_coding_product_factory", reject_second_selection)
        owner = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
        prepared = None
        second_prepared = None
        managers = []
        stages = []
        appends = []
        input_identities = []
        debt = None
        native_sessions = []
        dispose_session = AgentSession.dispose
        entered = asyncio.Event()
        release = asyncio.Event()

        async def present(payload):
            assert all(manager._lifecycle_session._writer_owner.closing for manager in managers)
            stages.append("confirm")
            assert await owner.handle_result(payload["action_id"], outcome="allow_once")

        owner.set_request_presenter(present)
        fact = await owner.confirm(coding_resume_permission_request(attempt, actor_id="root", expansion_codes=("authority.unknown",)))
        assert fact is not None
        permission = CodingResumePermissionConfirmation(attempt, "root", ("authority.unknown",), owner, fact)

        def admit(observed):
            assert observed == attempt
            permission.require_current(observed)

        def epoch(observed, receipt):
            assert observed == attempt
            assert receipt["setId"] == "coding-standard"
            stages.append("epoch")
            if mode == "unsettled":
                raise StoreCommitOutcomeUnknown("native effect unsettled")

        load_writer = manager_type._load_resume_writer

        async def observe_writer(cls, *args, **kwargs):
            stages.append("writer")
            manager = await load_writer(*args, **kwargs)
            managers.append(manager)
            if mode == "commit_unknown":
                store = manager._lifecycle_session.runtime_binding.store
                append = store.append

                async def lost_ack(key, record, **kwargs):
                    result = await append(key, record, **kwargs)
                    if record.record_id == "input-record":
                        appends.append((record, kwargs["expected_revision"], kwargs["operation_id"]))
                        raise StoreCommitOutcomeUnknown("input acknowledgement lost")
                    return result

                monkeypatch.setattr(store, "append", lost_ack)
            return manager

        monkeypatch.setattr(manager_type, "_load_resume_writer", classmethod(observe_writer))
        graph = AgentSession._prepare_resume_runtime_graph

        async def observe_graph(session, **kwargs):
            native_sessions.append(session)
            stages.append("graph")
            result = await graph(session, **kwargs)
            if mode == "graph_revoked":
                owner.release_confirmation(fact)
            return result

        monkeypatch.setattr(AgentSession, "_prepare_resume_runtime_graph", observe_graph)
        publish = AgentSession._publish_resume_runtime

        async def observe_publish(session, **kwargs):
            if mode in {"publication_revoked", "cleanup_failed"}:
                owner.release_confirmation(fact)
            await publish(session, **kwargs)

        monkeypatch.setattr(AgentSession, "_publish_resume_runtime", observe_publish)
        if mode in {"cleanup_failed", "bootstrap_cleanup_failed"}:
            failures = []

            async def fail_cleanup_once(session, *args, **kwargs):
                if not failures:
                    failures.append(session)
                    raise OSError("native owner cleanup failed")
                await dispose_session(session, *args, **kwargs)

            monkeypatch.setattr(AgentSession, "dispose", fail_cleanup_once)
        if mode == "bootstrap_cleanup_failed":
            construct = bootstrap._create_agent_session

            def revoke_after_construct(**kwargs):
                candidate = construct(**kwargs)
                native_sessions.append(candidate)
                owner.release_confirmation(fact)
                return candidate

            monkeypatch.setattr(bootstrap, "_create_agent_session", revoke_after_construct)
        preflight = PromptController.prepare_user_message

        async def observe_preflight(prompt, *args, **kwargs):
            stages.append("preflight")
            result = await preflight(prompt, *args, **kwargs)
            if mode == "preflight_revoked":
                owner.release_confirmation(fact)
            if mode == "preflight_cancelled":
                entered.set()
                await release.wait()
            return result

        monkeypatch.setattr(PromptController, "prepare_user_message", observe_preflight)
        before = path.read_bytes()

        def observe_input_identity(query):
            input_identities.append(query)
            if mode == "identity_delivery_failed":
                raise RuntimeError("input identity receiver failed")

        try:
            if mode == "denied":
                owner.release_confirmation(fact)
            operation = prepare_coding_resume_continuation(
                manager_type=manager_type, session_file=path, plan=plan,
                current_owner_inputs=(), attempt=attempt, input_record_id="input-record",
                text="/skill:review inspect", require_current_admission=admit,
                require_current_epoch_settlement=epoch, no_tools=True,
                created_at=datetime(2026, 10, 12, tzinfo=UTC),
                observe_input_identity=observe_input_identity,
                **({"product_owner_selection": application_selection} if application_selection is not None else {}),
            )
            if mode in {"published", "published_application_owner", "published_duplicate"}:
                prepared = await operation
                assert prepared.input_record_id == "input-record"
                assert prepared.session.execution_available
                assert not prepared.session.agent.is_streaming
                assert prepared.session.session_manager.get_header() == header
            elif mode == "preflight_cancelled":
                task = asyncio.create_task(operation)
                waiting = asyncio.create_task(entered.wait())
                try:
                    await asyncio.wait((task, waiting), return_when=asyncio.FIRST_COMPLETED)
                    if not entered.is_set():
                        await task
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                finally:
                    release.set()
                    waiting.cancel()
                    await asyncio.gather(task, waiting, return_exceptions=True)
            else:
                error = RuntimeError if mode in {"cleanup_failed", "bootstrap_cleanup_failed", "identity_delivery_failed"} else (
                    StoreCommitOutcomeUnknown if mode in {"unsettled", "commit_unknown"} else PermissionError
                )
                with pytest.raises(error) as failed:
                    await operation
                if mode in {"cleanup_failed", "bootstrap_cleanup_failed"}:
                    debt = failed.value
                    assert debt.original_owner is native_sessions[0]
                    assert isinstance(debt.original_error, PermissionError)
                    assert isinstance(debt.cleanup_error, OSError)
                    assert factory._closing
                    assert not managers[0]._lifecycle_session._disposed
                    await debt.retry_cleanup()
            durable_header, records = load_agent_transcript_file(path, read_only=True)
            assert durable_header == header
            inputs = [record for record in records if record.record_id == "input-record"]
            if mode in {"published", "published_application_owner", "published_duplicate", "commit_unknown", "publication_revoked", "cleanup_failed", "identity_delivery_failed"}:
                assert len(inputs) == 1
                record = inputs[0]
                assert len(input_identities) == 1
                assert input_identities[0].input_id == attempt.request_id
                assert input_identities[0].record_digest == coding_resume_input_record_digest(record)
                observation = observe_coding_resume_model_outcome(
                    read_coding_resume_snapshot(path, max_bytes=1024 * 1024), input_identities[0],
                )
                assert observation.input_record_id == "input-record"
                assert observation.status == "unknown"
                if prepared is not None:
                    assert prepared.input_lookup_query == input_identities[0]
                assert "Review actual source bytes." in user_message_text(record.payload)
                evidence = record.metadata[RESOURCE_EVIDENCE_METADATA_KEY]
                assert evidence["skills"][0]["observedContentDigest"] == hashlib.sha256(skill.read_bytes()).hexdigest()
                assert len([r for r in records if isinstance(r.payload, UserMessage)]) == 2
            else:
                assert not inputs
                assert not input_identities
            if mode == "denied":
                assert path.read_bytes() == before
                assert stages == ["confirm"]
            elif mode in {"bootstrap_cleanup_failed", "application_owner_revoked"}:
                assert stages == ["confirm", "writer"]
            else:
                assert stages[:3] == ["confirm", "writer", "graph"]
            if mode == "unsettled":
                assert "preflight" not in stages
            if mode == "commit_unknown":
                assert len(appends) == 2  # Original UOW fixed-ID verification.
                assert appends[0] == appends[1]
            if mode not in {"published", "published_application_owner", "published_duplicate"} and managers:
                assert managers[0]._lifecycle_session._writer_owner.closing
            if mode == "published_duplicate":
                await prepared.session.dispose()
                saved_bytes = path.read_bytes()
                new_plan = build_session_activation_plan(
                    read_coding_resume_snapshot(path, max_bytes=1024 * 1024),
                    resolve_coding_composition_set("coding-standard"), workspace_root=tmp_path,
                )
                attempt = replace(attempt, attempt_id="attempt-2", original_leaf_id=new_plan.selected_leaf_id,
                                  ancestry_digest=new_plan.ancestry_digest, plan_fingerprint=new_plan.plan_id)
                fresh_fact = await owner.confirm(coding_resume_permission_request(
                    attempt, actor_id="root", expansion_codes=("authority.unknown",),
                ))
                assert fresh_fact is not None
                permission = CodingResumePermissionConfirmation(attempt, "root", ("authority.unknown",), owner, fresh_fact)
                graph_calls_before = stages.count("graph")
                with pytest.raises(CodingResumeRecoveryRequired, match="input.recovery_required"):
                    second_prepared = await prepare_coding_resume_continuation(
                        manager_type=manager_type, session_file=path, plan=new_plan, current_owner_inputs=(),
                        attempt=attempt, input_record_id="different-record", text="changed duplicate",
                        require_current_admission=admit, require_current_epoch_settlement=epoch, no_tools=True,
                        created_at=datetime(2026, 10, 12, tzinfo=UTC),
                    )
                assert path.read_bytes() == saved_bytes
                assert stages.count("graph") == graph_calls_before
        finally:
            if second_prepared is not None:
                await second_prepared.session.dispose()
            if prepared is not None:
                await prepared.session.dispose()
            elif native_sessions:
                await dispose_session(native_sessions[0])
            owner.dispose()
            await factory.close()
            if application_selection is not None:
                assert len(selected_factories) == 1
                assert len(application_selection._owners) == 1
                assert not application_selection._fenced
                for application_owner in application_selection._owners.values():
                    application_owner.epoch_runtime.assert_current()
                application_selection.close()

    asyncio.run(scenario())
