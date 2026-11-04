from __future__ import annotations

import asyncio
import hashlib
import sys
import traceback
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from loushang.ai.api_registry import get_default_api_registry
from loushang.ai.json_codec import serialize_message
from loushang.ai.model import Auth, Capabilities, Model
from loushang.ai.prepared_request import PreparedModelRequest
from loushang.ai.types import UserMessage
from loushang.coding.bootstrap import _create_resume_agent_session
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.resume_activation_attempt import (
    CodingActivationAttemptV1,
    CodingResumeRecoveryRequired,
    prepare_coding_activation_attempt_record,
)
from loushang.coding.resume_activation_plan import build_session_activation_plan
from loushang.coding.resume_binding import (
    CodingRuntimeBindingV1,
    coding_user_payload_digest,
)
from loushang.coding.resume_history import read_coding_resume_snapshot
from loushang.coding.resume_input_lookup import (
    CodingResumeInputLookupQueryV1,
    coding_resume_input_record_digest,
)
from loushang.coding.resume_permission_confirmation import (
    CodingResumePermissionConfirmation,
    coding_resume_permission_request,
)
from loushang.coding.session_manager import (
    SessionManager,
    _bind_owned_session_manager,
    _create_owned_session_factory,
)
from loushang.harness.approval import DenyApprovalResolver, InteractiveApprovalResolver
from loushang.harness.conversation import StoreCommitOutcomeUnknown
from loushang.harness.session.bash import UserBashRequest
from loushang.harness.transcript import user_message_text
from loushang.harness.transcript.committer import PrebuiltUserMessageLookupResult

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux owned Coding Writer")


@pytest.mark.parametrize("mode", [
    "published", "published_evidence", "published_preflight", "published_preflight_native_confirmation",
    "preflight_native_revoked",
    "preflight_revoked", "preflight_cancelled", "preflight_repeated", "preflight_changed_input", "preflight_command",
    "input_commit_unknown", "input_commit_revoked",
    "input_commit_mismatch", "input_commit_revoked_after",
    "input_unknown", "changed_leaf", "revoked", "unsettled",
    "receipt_changed", "graph_missing",
    "durable_lookup_unknown", "revoked_during_lookup",
    "durable_input_changed", "publication_cancelled",
    "dispatch_completed", "dispatch_error", "dispatch_queued", "dispatch_revoked",
    "dispatch_revoked_at_barrier", "dispatch_cancelled",
    "dispatch_aborted",
])
def test_resume_publication_requires_exact_commit_current_graph_and_owner_checks(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))

    async def scenario():
        if mode.startswith("published_preflight") or mode.startswith("preflight_"):
            skill = tmp_path / "skills" / "review" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: review\ndescription: Review changes\n---\nReview actual source bytes.\n")
            (tmp_path / "AGENTS.md").write_text("Project guidance\n")
        original = await SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(tmp_path), defer_materialization=False,
        )
        await original.append_message(UserMessage(role="user", content="history", timestamp=1.0))
        path = original.session_file
        header = original.header
        await original.dispose_runtime_profile()
        assert path is not None
        composition = resolve_coding_composition_set(
            "coding-standard" if mode.startswith("published_preflight") or mode.startswith("preflight_") else "coding-minimal",
        )
        plan = build_session_activation_plan(
            read_coding_resume_snapshot(path, max_bytes=1024 * 1024), composition, workspace_root=tmp_path,
        )
        factory = _create_owned_session_factory()
        manager_type = _bind_owned_session_manager(factory)
        manager = None
        attempt = CodingActivationAttemptV1(
            attempt_id="attempt-1", request_id="input-1", session_id=header.conversation_id,
            original_leaf_id=plan.selected_leaf_id, ancestry_digest=plan.ancestry_digest,
            plan_fingerprint=plan.plan_id, epoch_fingerprint="a" * 64, subject_digest="b" * 64,
        )
        revoked = False
        settlements = []
        requests = []
        failures = []
        barrier_hits = []
        transport_entered, transport_release = asyncio.Event(), asyncio.Event()
        registry = None
        session = None
        approval_owner = None
        permission_confirmation = None

        def admit(observed):
            assert observed == attempt
            if permission_confirmation is not None:
                permission_confirmation.require_current(observed)
            if revoked:
                raise PermissionError("current subject revoked")

        def settle_epoch(observed, receipt):
            assert observed == attempt
            assert receipt["setId"] == composition.set_id
            settlements.append(observed.attempt_id)
            if mode == "unsettled":
                raise StoreCommitOutcomeUnknown("native effect is unsettled")

        try:
            if mode in {"published_preflight_native_confirmation", "preflight_native_revoked"}:
                approval_owner = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
                permission_request = coding_resume_permission_request(
                    attempt, actor_id="root", expansion_codes=("authority.unknown", "workspace.write"),
                )
                history_bytes = path.read_bytes()

                async def confirm_permissions(payload):
                    assert manager is None  # No Resume Writer while awaiting confirmation.
                    assert path.read_bytes() == history_bytes
                    assert await approval_owner.handle_result(payload["action_id"], outcome="allow_once")

                approval_owner.set_request_presenter(confirm_permissions)
                confirmation = await approval_owner.confirm(permission_request)
                assert confirmation is not None
                permission_confirmation = CodingResumePermissionConfirmation(
                    attempt, "root", ("authority.unknown", "workspace.write"), approval_owner, confirmation,
                )
                permission_confirmation.require_current(attempt)
            manager = await manager_type._load_resume_writer(path, plan=plan, current_owner_inputs=())
            await manager._commit_resume_activation_intent(prepare_coding_activation_attempt_record(
                attempt, created_at=datetime(2026, 10, 12, tzinfo=UTC),
            ))
            session = await _create_resume_agent_session(
                session_manager=manager, attempt_id=attempt.attempt_id,
                composition_set=composition, require_current_admission=admit, no_tools=True,
            )
            if mode.startswith("dispatch_"):
                handle_failure = session.agent._handle_run_failure

                async def capture_failure(error, *, aborted):
                    if isinstance(error, RuntimeError) and str(error) == "no running event loop":
                        traceback.print_exception(error)
                    failures.append(repr(error))
                    await handle_failure(error, aborted=aborted)

                monkeypatch.setattr(session.agent, "_handle_run_failure", capture_failure)
                session.agent.model = Model(
                    id="faux-model", name="Faux", provider="faux", endpoint="resume-test",
                    api="resume-dispatch-test", base_url="https://provider.test/v1", auth=Auth(kind="none"),
                    capabilities=Capabilities(input=("text",), output=("text",), stream=True,
                                              context_window=128000, max_tokens=4096),
                )

                class Adapter:
                    api = "resume-dispatch-test"

                    def prepare_request(self, request):
                        return PreparedModelRequest.from_provider_request(request, payload={
                            "messages": [serialize_message(m) for m in request.context.messages],
                            "model": request.model.id,
                        })

                    async def invoke_prepared_raw(self, request, prepared):
                        prepared.payload_for_transport()
                        assert request.attempt == 1
                        requests.append(request.context)
                        if mode in {"dispatch_cancelled", "dispatch_aborted"}:
                            transport_entered.set()
                            await transport_release.wait()
                        if mode == "dispatch_error":
                            raise ConnectionError("network outcome unknown")
                        yield {"type": "response_start", "response_id": "resume-response"}
                        yield {"type": "text_delta", "text": "reply"}
                        yield {"type": "stop_reason", "stop_reason": "stop"}
                        yield {"type": "response_done"}

                    async def invoke_raw(self, request):
                        pytest.fail("prepared transport barrier was bypassed")
                        yield {}

                registry = get_default_api_registry()
                registry.register_api_adapter(Adapter(), source_id="resume-dispatch-test")
                if mode == "dispatch_revoked_at_barrier":
                    append_snapshot = manager._transcript.append_staged_model_input_snapshot

                    async def revoke_after_snapshot(*args, **kwargs):
                        nonlocal revoked
                        result = await append_snapshot(*args, **kwargs)
                        barrier_hits.append(True)
                        revoked = True
                        return result

                    monkeypatch.setattr(manager._transcript, "append_staged_model_input_snapshot", revoke_after_snapshot)
            if mode != "graph_missing":
                await session._prepare_resume_runtime_graph(
                    attempt_id=attempt.attempt_id, require_current_admission=admit,
                )
            message = UserMessage(role="user", content="resume once", timestamp=2.0)
            evidence = None
            if mode.startswith("published_preflight") or mode.startswith("preflight_"):
                prompt = session._composition.session_runtime.prompt_controller
                preflight = prompt.preflight_user_input_async
                entered, release = asyncio.Event(), asyncio.Event()
                preflight_calls = []

                async def observe_preflight(text, **kwargs):
                    nonlocal revoked
                    assert kwargs == {"allow_extension_commands": False}
                    preflight_calls.append(text)
                    result = await preflight(text, **kwargs)
                    assert len(result.loaded_skills) == 1
                    assert "Review actual source bytes." in result.text
                    if mode == "preflight_revoked":
                        revoked = True
                    if mode == "preflight_native_revoked":
                        assert approval_owner.release_confirmation(permission_confirmation.confirmation)
                    if mode == "preflight_cancelled":
                        entered.set()
                        await release.wait()
                    return result

                monkeypatch.setattr(prompt, "preflight_user_input_async", observe_preflight)
                if mode == "preflight_command":
                    commands = session._composition.command_controller

                    async def forbidden_command(*args):
                        pytest.fail("prepared Resume input must not execute a command")

                    commands.builtin_executor = forbidden_command
                    commands.builtin_matcher = lambda name: name == "compact"
                    with pytest.raises(CodingResumeRecoveryRequired, match="input.command_requires_separate_admission"):
                        await session._prepare_resume_first_user_input(
                            "/compact", attempt_id=attempt.attempt_id,
                            require_current_admission=admit,
                        )
                    assert not preflight_calls
                    assert len(manager.get_entries()) == 2
                    return
                task = asyncio.create_task(session._prepare_resume_first_user_input(
                    "/skill:review inspect", attempt_id=attempt.attempt_id,
                    require_current_admission=admit,
                ))
                if mode == "preflight_cancelled":
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
                    assert len(manager.get_entries()) == 2
                    assert not session.execution_available
                    return
                if mode in {"preflight_revoked", "preflight_native_revoked"}:
                    with pytest.raises(PermissionError):
                        await task
                    assert len(manager.get_entries()) == 2
                    assert not session.execution_available
                    assert not session._request_evidence_runtime._pending
                    return
                message = await task
                assert "Review actual source bytes." in user_message_text(message)
                assert len(manager.get_entries()) == 2
                with pytest.raises(CodingResumeRecoveryRequired, match="input.preflight_already_claimed"):
                    await session._prepare_resume_first_user_input(
                        "/skill:review changed", attempt_id=attempt.attempt_id,
                        require_current_admission=admit,
                    )
                assert preflight_calls == ["/skill:review inspect"]
                if mode == "preflight_repeated":
                    return
            if mode == "published_evidence":
                from loushang.harness.capabilities.prompt_preflight import (
                    PromptPreflightResult,
                )
                from tests.harness.session.test_request_evidence import _loaded_skill

                evidence_runtime = session._request_evidence_runtime
                evidence = evidence_runtime.prepare(PromptPreflightResult(
                    text=message.content, loaded_skills=(_loaded_skill(),),
                ))
                assert evidence is not None
                evidence_runtime.bind(message, evidence, owner=session)

            def prepare_binding(persisted):
                return CodingRuntimeBindingV1(
                    attempt_id=attempt.attempt_id, input_id=attempt.request_id, record_id="record-1",
                    session_id=attempt.session_id, original_leaf_id=attempt.original_leaf_id,
                    ancestry_digest=attempt.ancestry_digest, subject_digest=attempt.subject_digest,
                    origin_composition=plan.composition_comparison.origin,
                    planned_fingerprint=attempt.plan_fingerprint, actual_fingerprint=attempt.epoch_fingerprint,
                    payload_digest=coding_user_payload_digest(persisted),
                )

            stage_message = replace(message, content="changed") if mode == "preflight_changed_input" else message
            manager._stage_resume_first_user_input(
                stage_message, prepare_binding=prepare_binding,
                created_at=datetime(2026, 10, 12, tzinfo=UTC),
                original_leaf_id=attempt.original_leaf_id, ancestry_digest=attempt.ancestry_digest,
                attempt_id=attempt.attempt_id,
            )
            if mode == "preflight_changed_input":
                with pytest.raises(CodingResumeRecoveryRequired, match="input.preflight_payload_changed"):
                    await session._commit_resume_first_user_input(
                        stage_message, attempt_id=attempt.attempt_id,
                        require_current_admission=admit,
                    )
                assert len(manager.get_entries()) == 2
                return
            if mode.startswith("input_commit_"):
                native_appends = []
                store = manager._lifecycle_session.runtime_binding.store
                append = store.append

                async def observe_append(key, record, **kwargs):
                    nonlocal revoked
                    if record.record_id != "record-1":
                        return await append(key, record, **kwargs)
                    native_appends.append((record, kwargs["expected_revision"], kwargs["operation_id"]))
                    result = await append(key, record, **kwargs)
                    if mode == "input_commit_unknown":
                        raise StoreCommitOutcomeUnknown("input acknowledgement lost")
                    revoked = True
                    return result

                monkeypatch.setattr(store, "append", observe_append)
                if mode == "input_commit_revoked":
                    revoked = True
                expected = StoreCommitOutcomeUnknown if mode.endswith("unknown") else (
                    ValueError if mode.endswith("mismatch") else PermissionError
                )
                submitted = replace(message, content="different") if mode.endswith("mismatch") else message
                with pytest.raises(expected):
                    await session._commit_resume_first_user_input(
                        submitted, attempt_id=attempt.attempt_id, require_current_admission=admit,
                    )
                assert not session.execution_available
                assert manager.resume_runtime_publication_pending
                assert not settlements
                assert not requests
                if mode in {"input_commit_unknown", "input_commit_revoked_after"}:
                    expected_calls = 2 if mode == "input_commit_unknown" else 1
                    assert len(native_appends) == expected_calls
                    assert all(call == native_appends[0] for call in native_appends)
                    assert native_appends[0][2] == "record-1"
                    from loushang.harness.transcript.jsonl_file import (
                        load_agent_transcript_file,
                    )

                    _, durable = load_agent_transcript_file(path, read_only=True)
                    assert [record for record in durable if record.record_id == "record-1"] == [native_appends[0][0]]
                    with pytest.raises(CodingResumeRecoveryRequired, match="input.commit_already_claimed"):
                        await session._commit_resume_first_user_input(
                            message, attempt_id=attempt.attempt_id, require_current_admission=admit,
                        )
                    if mode == "input_commit_unknown":
                        pending = manager._resume_first_input
                        assert pending is not None and pending.prepared_record is not None
                        result = await manager.lookup_resume_input(CodingResumeInputLookupQueryV1(
                            attempt.request_id, coding_resume_input_record_digest(pending.prepared_record),
                        ))
                        assert result.status == "committed"
                    assert len(native_appends) == expected_calls
                else:
                    assert not native_appends
                    assert len(manager.get_entries()) == 2
                return
            if mode == "input_unknown":
                store = manager._lifecycle_session.runtime_binding.store
                append = store.append

                async def lose_ack(*args, **kwargs):
                    await append(*args, **kwargs)
                    raise StoreCommitOutcomeUnknown("input acknowledgement lost")

                monkeypatch.setattr(store, "append", lose_ack)
                with pytest.raises(StoreCommitOutcomeUnknown):
                    await manager.append_message(message)
            else:
                if mode.startswith("published") or mode.startswith("dispatch_"):
                    assert await session._commit_resume_first_user_input(
                        message, attempt_id=attempt.attempt_id,
                        require_current_admission=admit,
                    ) == "record-1"
                    with pytest.raises(CodingResumeRecoveryRequired, match="input.commit_already_claimed"):
                        await session._commit_resume_first_user_input(
                            message, attempt_id=attempt.attempt_id, require_current_admission=admit,
                        )
                else:
                    assert await manager.append_message(message) == "record-1"
            assert manager.resume_runtime_publication_pending
            assert not session.execution_available
            before = path.read_bytes()
            if mode == "durable_input_changed":
                changed = before.replace(b"resume once", b"broken once")
                assert changed != before
                path.write_bytes(changed)
                before = changed
            if mode == "changed_leaf":
                manager.branch(attempt.original_leaf_id)
            if mode == "revoked":
                revoked = True
            if mode in {"durable_lookup_unknown", "revoked_during_lookup"}:
                lookup = manager.lookup_prebuilt_user_message

                async def observe_input(record):
                    nonlocal revoked
                    result = await lookup(record)
                    if mode == "revoked_during_lookup":
                        revoked = True
                        return result
                    return PrebuiltUserMessageLookupResult(record.record_id, "unknown")

                monkeypatch.setattr(manager, "lookup_prebuilt_user_message", observe_input)
            if mode == "receipt_changed":
                build = session._build_current_coding_composition_receipt

                def changed_receipt():
                    receipt = build()
                    receipt["catalogSelectionFingerprint"] = "c" * 64
                    return receipt

                monkeypatch.setattr(session, "_build_current_coding_composition_receipt", changed_receipt)
            if mode == "publication_cancelled":
                entered, release = asyncio.Event(), asyncio.Event()
                lookup = manager.lookup_prebuilt_user_message

                async def held_lookup(record):
                    entered.set()
                    await release.wait()
                    return await lookup(record)

                monkeypatch.setattr(manager, "lookup_prebuilt_user_message", held_lookup)
                task = asyncio.create_task(session._publish_resume_runtime(
                    attempt_id=attempt.attempt_id, input_record_id="record-1",
                    require_current_admission=admit, require_current_epoch_settlement=settle_epoch,
                ))
                waiting = asyncio.create_task(entered.wait())
                try:
                    await asyncio.wait((task, waiting), return_when=asyncio.FIRST_COMPLETED)
                    if not entered.is_set():
                        await task
                        pytest.fail("publication returned before its durable lookup")
                    assert task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                finally:
                    release.set()
                    waiting.cancel()
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, waiting, return_exceptions=True)
                assert not session.execution_available
                assert manager.resume_runtime_publication_pending
                assert not settlements
                assert path.read_bytes() == before
            elif mode.startswith("published") or mode.startswith("dispatch_"):
                await session._publish_resume_runtime(
                    attempt_id=attempt.attempt_id, input_record_id="record-1",
                    require_current_admission=admit, require_current_epoch_settlement=settle_epoch,
                )
                assert settlements
                assert session.execution_available
                if mode.startswith("published_preflight"):
                    from loushang.harness.session.request_evidence import (
                        RESOURCE_EVIDENCE_METADATA_KEY,
                    )

                    bound = next(record for record in manager.get_entries() if record.record_id == "record-1")
                    metadata = bound.metadata[RESOURCE_EVIDENCE_METADATA_KEY]
                    assert metadata["modelVisibleText"] == user_message_text(message)
                    assert metadata["skills"][0]["observedContentDigest"] == hashlib.sha256(skill.read_bytes()).hexdigest()
                    assert (await manager.lookup_resume_input(CodingResumeInputLookupQueryV1(
                        attempt.request_id, coding_resume_input_record_digest(bound),
                    ))).status == "committed"
                if evidence is not None:
                    from loushang.harness.session.request_evidence import (
                        RESOURCE_EVIDENCE_METADATA_KEY,
                    )

                    bound = next(record for record in manager.get_entries() if record.record_id == "record-1")
                    assert bound.metadata[RESOURCE_EVIDENCE_METADATA_KEY] == evidence.to_message_metadata()
                    assert manager._require_committed_resume_input(attempt.attempt_id, "record-1")[1] == bound
                    assert session._request_evidence_runtime.commit_message(message, "record-1")
                assert not manager.resume_runtime_publication_pending
                if mode.startswith("dispatch_"):
                    options_before = session.agent.call_options
                    if mode == "dispatch_queued":
                        session.agent.follow_up(UserMessage(role="user", content="queued", timestamp=4.0))
                    if mode == "dispatch_revoked":
                        revoked = True
                    if mode in {"dispatch_queued", "dispatch_revoked"}:
                        with pytest.raises(PermissionError if mode == "dispatch_revoked" else CodingResumeRecoveryRequired):
                            await session._run_published_resume_input(attempt_id=attempt.attempt_id, input_record_id="record-1")
                        assert not requests
                        assert path.read_bytes() == before
                    else:
                        if mode in {"dispatch_cancelled", "dispatch_aborted"}:
                            task = asyncio.create_task(session._run_published_resume_input(
                                attempt_id=attempt.attempt_id, input_record_id="record-1",
                            ))
                            waiting = asyncio.create_task(transport_entered.wait())
                            try:
                                await asyncio.wait((task, waiting), return_when=asyncio.FIRST_COMPLETED)
                                if not transport_entered.is_set():
                                    await task
                                    pytest.fail("run returned before transport")
                                if mode == "dispatch_cancelled":
                                    assert task.cancel()
                                    transport_release.set()
                                    with pytest.raises(asyncio.CancelledError):
                                        await task
                                else:
                                    assert session.abort()
                                    transport_release.set()
                                    await task
                            finally:
                                transport_release.set()
                                waiting.cancel()
                                if not task.done():
                                    task.cancel()
                                await asyncio.gather(task, waiting, return_exceptions=True)
                        else:
                            await session._run_published_resume_input(attempt_id=attempt.attempt_id, input_record_id="record-1")
                        if mode == "dispatch_revoked_at_barrier":
                            assert barrier_hits == [True]
                        assert len(requests) == (0 if mode == "dispatch_revoked_at_barrier" else 1), failures
                        if requests:
                            messages = [serialize_message(m) for m in requests[0].messages]
                            assert [m["content"][0]["text"] for m in messages if m["role"] == "user"] == ["history", "resume once"]
                        snapshots = [r.payload for r in manager.get_entries() if r.kind == "model.input.prepared"]
                        assert len(snapshots) == 1
                        assert snapshots[0].source_leaf_id == "record-1"
                        from loushang.coding.resume_model_outcome import (
                            observe_coding_resume_model_outcome,
                        )

                        input_record = next(record for record in manager.get_entries() if record.record_id == "record-1")
                        query = CodingResumeInputLookupQueryV1(
                            attempt.request_id, coding_resume_input_record_digest(input_record),
                        )
                        observed = observe_coding_resume_model_outcome(
                            read_coding_resume_snapshot(path, max_bytes=8 * 1024 * 1024), query,
                        )
                        assert observed.input_record_id == "record-1"
                        assert observed.invocation_id == snapshots[0].invocation_id
                        assert observed.model_input_snapshot_ids == (snapshots[0].snapshot_id,)
                        assert observed.status == {
                            "dispatch_completed": "observed_completed",
                            "dispatch_error": "observed_failed",
                            "dispatch_revoked_at_barrier": "unknown",
                            "dispatch_cancelled": "observed_cancelled",
                            "dispatch_aborted": "observed_cancelled",
                        }[mode]
                        assert manager.rebuild_model_input(snapshots[0].snapshot_id).snapshot.purpose == "main"
                        assert len([r for r in manager.get_entries() if isinstance(r.payload, UserMessage)]) == 2
                        with pytest.raises(CodingResumeRecoveryRequired, match="model.dispatch_already_claimed"):
                            await session._run_published_resume_input(attempt_id=attempt.attempt_id, input_record_id="record-1")
                        assert len(requests) == (0 if mode == "dispatch_revoked_at_barrier" else 1)
                        assert session.execution_available == (mode == "dispatch_completed")
                    assert session.agent.call_options is options_before
                    assert not session._composition.session_runtime._committed_input_recovery_suppressed
                    return
                await session.prepare_model_call_runtime()
                assert manager.header == header
                assert path.read_bytes() == before
                await manager.append_message(UserMessage(role="user", content="next", timestamp=3.0))
                await session.prepare_model_call_runtime()
                if mode == "published_preflight_native_confirmation":
                    assert approval_owner.release_confirmation(permission_confirmation.confirmation)
                else:
                    revoked = True
                with pytest.raises(PermissionError):
                    await session.prepare_model_call_runtime()
                with pytest.raises(PermissionError):
                    await session.compact()
                with pytest.raises(PermissionError):
                    await session._before_bash(UserBashRequest("blocked", str(tmp_path), False))
                with pytest.raises(PermissionError):
                    await session._exec_command_from_extension("blocked")
                revoked = False
                manager.branch(attempt.original_leaf_id)
                with pytest.raises(CodingResumeRecoveryRequired):
                    await session.prepare_model_call_runtime()
            else:
                expected = (
                    PermissionError if mode in {"revoked", "revoked_during_lookup"} else StoreCommitOutcomeUnknown
                    if mode == "unsettled" else CodingResumeRecoveryRequired
                )
                with pytest.raises(expected):
                    await session._publish_resume_runtime(
                        attempt_id=attempt.attempt_id, input_record_id="record-1",
                        require_current_admission=admit, require_current_epoch_settlement=settle_epoch,
                    )
                assert not session.execution_available
                assert manager.resume_runtime_publication_pending
                assert path.read_bytes() == before
                if mode not in {"unsettled"}:
                    assert not settlements
        finally:
            if registry is not None:
                registry.unregister_api_adapters("resume-dispatch-test")
            if session is not None:
                await session.dispose()
            elif manager is not None:
                await manager.dispose_runtime_profile()
            if approval_owner is not None:
                approval_owner.dispose()
            await factory.close()

    asyncio.run(scenario())
