from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from loushang.coding.resume_activation_attempt import CodingActivationAttemptV1
from loushang.coding.resume_permission_confirmation import (
    CodingResumePermissionConfirmation,
    coding_resume_permission_request,
)
from loushang.harness.approval import DenyApprovalResolver, InteractiveApprovalResolver
from loushang.harness.authorization import EffectiveExecutionProfile
from loushang.harness.config.agent import SettingsManager
from loushang.harness.tools.workspace.factory import workspace_tool_runtime_settings


@pytest.mark.parametrize("mode", ["current", "outside_view", "owner_closed", "root_closed", "owner_replaced", "subject_changed", "actor_changed", "binding_removed", "root_changed", "view_revoked", "unbound_attempt"])
def test_embedded_resume_subject_uses_default_cli_root_and_original_approval(tmp_path, monkeypatch, mode):
    from loushang.coding.bootstrap import create_services
    from loushang.coding.cli.application import default_runtime_builder
    from loushang.coding.cli.args import parse_args
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "home"))

    async def scenario():
        original = await SessionManager.new(session_dir=tmp_path / "sessions", cwd=str(tmp_path), defer_materialization=False)
        path = original.session_file
        await original.dispose_runtime_profile()
        assert path is not None
        owner = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
        foreign = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
        policy = workspace_tool_runtime_settings(None).policy_engine
        runtime = default_runtime_builder(
            args=parse_args(["--no-tools", "--composition-set", "coding-minimal"]), cwd=tmp_path,
            session_dir=tmp_path / "sessions", services=create_services(),
            tool_registry=WorkspaceToolRegistry(), approval_resolver=owner,
            tool_policy_evaluator=policy,
        )
        assert runtime._configured_resume_planning is not None
        other_runtime = None
        try:
            before = path.read_bytes()
            history = await runtime.preview_resume_history(path)
            if mode == "unbound_attempt":
                from datetime import UTC, datetime

                from loushang.coding.composition_sets import (
                    resolve_coding_composition_set,
                )
                from loushang.coding.resume_activation_plan import (
                    build_session_activation_plan,
                )

                plan = build_session_activation_plan(
                    history, resolve_coding_composition_set("coding-minimal"), workspace_root=tmp_path,
                )
                epoch = runtime._product_owner_selection.prepare_resume_epoch(
                    tmp_path, require_current_admission=owner.require_current_root_subject,
                )
                attempt = CodingActivationAttemptV1(
                    attempt_id="unbound-attempt", request_id="unbound-input", session_id=plan.session_id,
                    original_leaf_id=plan.selected_leaf_id, ancestry_digest=plan.ancestry_digest,
                    plan_fingerprint=plan.plan_id, epoch_fingerprint=epoch, subject_digest="d" * 64,
                )
                with runtime.resume_history_view_scope(path, history):
                    with pytest.raises(PermissionError, match="subject changed"):
                        await runtime.prepare_resume_continuation(
                            session_file=path, plan=plan, current_owner_inputs=(), attempt=attempt,
                            input_record_id="unbound-record", text="continue once", created_at=datetime.now(UTC),
                            require_current_admission=lambda observed: None,
                            require_current_epoch_settlement=lambda observed, receipt: None,
                        )
                assert path.read_bytes() == before
                assert runtime.current_session is None
                assert not runtime._owned_transcript_factory.pending_preparations
                return
            with pytest.raises(PermissionError, match="history input"):
                runtime.embedded_resume_subject_digest()
            with runtime.resume_history_view_scope(path, history):
                digest = runtime.embedded_resume_subject_digest()
                assert digest == runtime.embedded_resume_subject_digest()
                attempt = CodingActivationAttemptV1(
                    attempt_id="embedded-attempt", request_id="embedded-input", session_id=history.header_preview.header.conversation_id,
                    original_leaf_id=history.selected_leaf_id, ancestry_digest=history.selected_ancestry_digest,
                    plan_fingerprint="b" * 64, epoch_fingerprint="c" * 64, subject_digest=digest,
                )
                request = coding_resume_permission_request(
                    attempt, actor_id="root", expansion_codes=("authority.unknown",), embedded_subject_root=runtime,
                )

                async def present(payload):
                    assert payload["arguments"]["subjectOwner"] == "coding.embedded-root/v1"
                    assert await owner.handle_result(payload["action_id"], outcome="allow_once")

                owner.set_request_presenter(present)
                fact = await owner.confirm(request)
                assert fact is not None
            bound = CodingResumePermissionConfirmation(
                attempt, "root", ("authority.unknown",), owner, fact, embedded_subject_root=runtime,
            )
            bound.require_current(attempt)  # The captured owner survives the display scope.
            if mode == "outside_view":
                with pytest.raises(PermissionError, match="history input"):
                    runtime.embedded_resume_subject_digest()
            elif mode == "owner_closed":
                owner.dispose()
            elif mode == "root_closed":
                await runtime.dispose_session_runtime()
            elif mode == "owner_replaced":
                with pytest.raises(PermissionError):
                    runtime._bind_embedded_resume_approval_owner(foreign)
                bound = replace(bound, owner=foreign)
            elif mode == "subject_changed":
                attempt = replace(attempt, subject_digest="d" * 64)
                bound = replace(bound, attempt=attempt)
            elif mode == "actor_changed":
                bound = replace(bound, actor_id="other")
            elif mode == "binding_removed":
                bound = replace(bound, embedded_subject_root=None)
            elif mode == "root_changed":
                other_runtime = default_runtime_builder(
                    args=parse_args(["--no-tools", "--composition-set", "coding-minimal"]), cwd=tmp_path,
                    session_dir=tmp_path / "sessions", services=create_services(),
                    tool_registry=WorkspaceToolRegistry(), approval_resolver=owner,
                )
                with runtime.resume_history_view_scope(path, history):
                    with pytest.raises(PermissionError, match="history input"):
                        other_runtime.embedded_resume_subject_digest()
                with other_runtime.resume_history_view_scope(path, history):
                    assert other_runtime.embedded_resume_subject_digest() != digest
                bound = replace(bound, embedded_subject_root=other_runtime)
            elif mode == "view_revoked":
                def revoked():
                    raise PermissionError("history input revoked")

                with runtime.resume_history_view_scope(path, history, require_current_view=revoked):
                    with pytest.raises(PermissionError, match="revoked"):
                        runtime.embedded_resume_subject_digest()
            if mode not in {"current", "outside_view", "view_revoked"}:
                with pytest.raises(PermissionError):
                    bound.require_current(attempt)
            assert path.read_bytes() == before
            assert not runtime._product_owner_selection._owners
            assert runtime.current_session is None
        finally:
            if other_runtime is not None:
                await other_runtime.dispose_session_runtime()
            await runtime.dispose_session_runtime()
            owner.dispose()
            foreign.dispose()

    asyncio.run(scenario())


def test_resume_confirmation_uses_actual_scoped_execution_context():
    from loushang.appserver.protocol import AppServiceError, MuxAttachV1
    from loushang.appservice.execution_contract import (
        ExecutionOutcomeV1,
        ExecutionStatusV1,
    )
    from loushang.coding.hosted_execution import (
        current_coding_hosted_resume_subject,
        current_coding_hosted_resume_submission_id,
    )
    from tests.appservice.test_execution_service import fixture

    async def scenario():
        service, host, first, second, selector, control, product = await fixture()
        issuer = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
        captured = []
        ready = asyncio.Event()

        async def run(execution_control):
            product.entered.set()
            scope, current_control, digest = current_coding_hosted_resume_subject()
            input_id = current_coding_hosted_resume_submission_id()
            assert input_id == "resume-submit"
            attempt = CodingActivationAttemptV1(
                attempt_id="execution-attempt", request_id=input_id,
                session_id=product.identity.session_id, original_leaf_id="leaf-1",
                ancestry_digest="a" * 64, plan_fingerprint="b" * 64,
                epoch_fingerprint="c" * 64, subject_digest=digest,
            )
            fact = await issuer.confirm(coding_resume_permission_request(
                attempt, actor_id=current_control.attachment_id, expansion_codes=("authority.unknown",),
                hosted_subject_scope=scope, hosted_subject_control=current_control,
            ))
            assert fact is not None
            confirmation = CodingResumePermissionConfirmation(
                attempt, current_control.attachment_id, ("authority.unknown",), issuer, fact,
                hosted_subject_scope=scope, hosted_subject_control=current_control,
            )
            confirmation.require_current(attempt)
            captured.append((scope, current_control, confirmation))
            ready.set()
            await product.release.wait()
            with pytest.raises(AppServiceError):
                confirmation.require_current(attempt)
            return ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED)

        async def confirm(payload):
            assert await issuer.handle_result(payload["action_id"], outcome="allow_once")

        issuer.set_request_presenter(confirm)
        product.run = run
        try:
            client = first.execution_client
            accepted = await client.submit_execution(control, "instance", "resume-submit", "resume once")
            await product.entered.wait()
            waiter = asyncio.create_task(ready.wait())
            try:
                assert product.guard._task is not None
                await asyncio.wait((waiter, product.guard._task), return_when=asyncio.FIRST_COMPLETED)
            finally:
                waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)
            assert len(captured) == 1
            assert captured[0][:2] == (first, control)
            with pytest.raises(AppServiceError):
                current_coding_hosted_resume_subject()
            await first.close()
            await second.attach_mux(MuxAttachV1(selector))
            product.release.set()
            binding = service._sessions[product.identity.session_id]._execution
            await service._execution_registry.wait(binding, accepted)
            assert len(captured) == 1
        finally:
            product.release.set()
            await service.close()
            issuer.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["current", "wrong_target", "takeover", "await_takeover", "stripped_owner"])
def test_resume_confirmation_borrows_original_hosted_controller(mode):
    from loushang.appserver.protocol import (
        AppServiceError,
        MuxAttachV1,
        SessionSnapshotRequestV1,
    )
    from tests.appservice.test_execution_service import fixture

    async def scenario():
        service, host, first, second, selector, control, product = await fixture()
        owner = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
        try:
            attempt = CodingActivationAttemptV1(
                attempt_id="hosted-attempt", request_id="hosted-input",
                session_id=product.identity.session_id, original_leaf_id="leaf-1",
                ancestry_digest="a" * 64, plan_fingerprint="b" * 64,
                epoch_fingerprint="c" * 64, subject_digest=first.resume_subject_digest(control),
            )
            if mode == "wrong_target":
                attempt = replace(attempt, session_id="different-session")
                with pytest.raises(AppServiceError):
                    coding_resume_permission_request(
                        attempt, actor_id=control.attachment_id, expansion_codes=("authority.unknown",),
                        hosted_subject_scope=first, hosted_subject_control=control,
                    )
                return

            async def takeover():
                await first.close()
                replacement = await second.attach_mux(MuxAttachV1(selector))
                current = SessionSnapshotRequestV1(
                    replacement.attachment_id, replacement.controller_generation, control.member_id,
                )
                assert second.resume_subject_digest(current) != attempt.subject_digest

            async def confirm(payload):
                assert payload["arguments"]["subjectOwner"] == "appservice.controller/v1"
                if mode == "await_takeover":
                    await takeover()
                assert await owner.handle_result(payload["action_id"], outcome="allow_once")

            owner.set_request_presenter(confirm)
            fact = await owner.confirm(coding_resume_permission_request(
                attempt, actor_id=control.attachment_id, expansion_codes=("authority.unknown",),
                hosted_subject_scope=first, hosted_subject_control=control,
            ))
            assert fact is not None
            bound = CodingResumePermissionConfirmation(
                attempt, control.attachment_id, ("authority.unknown",), owner, fact,
                hosted_subject_scope=first, hosted_subject_control=control,
            )
            if mode == "takeover":
                await takeover()
            if mode == "stripped_owner":
                bound = replace(bound, hosted_subject_scope=None, hosted_subject_control=None)
                with pytest.raises(PermissionError):
                    bound.require_current(attempt)
            elif mode == "current":
                bound.require_current(attempt)
            else:
                with pytest.raises(AppServiceError):
                    bound.require_current(attempt)
            assert not product.entered.is_set()
            assert host.pending_counts == (0, 0)
        finally:
            owner.dispose()
            await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["current", "profile", "managed_rules", "await_change", "missing_policy"])
def test_resume_confirmation_revalidates_native_current_policy(tmp_path, mode):
    async def scenario():
        settings = SettingsManager(
            global_settings_path=tmp_path / "user.json", project_settings_path=tmp_path / "project.json",
        )
        policy = workspace_tool_runtime_settings(settings).policy_engine
        attempt = CodingActivationAttemptV1(
            attempt_id="attempt-1", request_id="input-1", session_id="session-1",
            original_leaf_id="leaf-1", ancestry_digest="a" * 64,
            plan_fingerprint="b" * 64, epoch_fingerprint="c" * 64, subject_digest="d" * 64,
        )
        owner = InteractiveApprovalResolver(fallback=DenyApprovalResolver())

        async def present(payload):
            assert len(payload["arguments"]["policyConfigurationFingerprint"]) == 64
            if mode == "await_change":
                settings.set_permission_profile("full_access", scope="session")
            assert await owner.handle_result(payload["action_id"], outcome="allow_once")

        owner.set_request_presenter(present)
        try:
            fact = await owner.confirm(coding_resume_permission_request(
                attempt, actor_id="root", expansion_codes=("authority.unknown",), policy_evaluator=policy,
            ))
            assert fact is not None
            bound = CodingResumePermissionConfirmation(
                attempt, "root", ("authority.unknown",), owner, fact, policy_evaluator=policy,
            )
            if mode == "profile":
                settings.set_permission_profile("full_access", scope="session")
            elif mode == "managed_rules":
                settings.update_settings(scope="session", tools={"blocked_tools": ["bash"]})
            fresh = workspace_tool_runtime_settings(settings).policy_engine
            if mode == "missing_policy":
                fresh = None
            if mode == "current":
                bound.require_current(attempt, current_policy_evaluator=fresh)
            else:
                with pytest.raises(PermissionError):
                    bound.require_current(attempt, current_policy_evaluator=fresh)
        finally:
            owner.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["current", "read", "write", "network", "denial", "missing_scope", "current_scope_changed"])
def test_native_resume_confirmation_binds_execution_scope(tmp_path, mode):
    async def scenario():
        attempt = CodingActivationAttemptV1(
            attempt_id="attempt-1", request_id="input-1", session_id="session-1",
            original_leaf_id="leaf-1", ancestry_digest="a" * 64,
            plan_fingerprint="b" * 64, epoch_fingerprint="c" * 64, subject_digest="d" * 64,
        )
        profile = EffectiveExecutionProfile(
            readable_roots=(tmp_path,), writable_roots=(tmp_path / "output",),
            denied_roots=(tmp_path / "secret",), network="restricted",
        )
        expansion = ("authority.unknown",)
        owner = InteractiveApprovalResolver(fallback=DenyApprovalResolver())

        async def present(payload):
            assert payload["arguments"]["permissionExpansion"] == [
                "authority.unknown", "execution.baseline_unknown",
            ]
            assert payload["arguments"]["executionScope"]["network"] == "restricted"
            assert payload["arguments"]["executionScope"]["writableRoots"] == [str(tmp_path / "output")]
            assert await owner.handle_result(payload["action_id"], outcome="allow_once")

        owner.set_request_presenter(present)
        try:
            fact = await owner.confirm(coding_resume_permission_request(
                attempt, actor_id="root", expansion_codes=expansion, execution_profile=profile,
            ))
            assert fact is not None
            bound = CodingResumePermissionConfirmation(
                attempt, "root", expansion, owner, fact, execution_profile=profile,
            )
            bound.require_current(attempt, current_execution_profile=profile)
            observed = profile
            if mode == "current":
                owner.release_confirmation(fact)
            elif mode == "missing_scope":
                observed = None
            elif mode == "current_scope_changed":
                observed = replace(profile, network="allowed")
            else:
                changed = replace(profile, **{
                    "read": {"readable_roots": (tmp_path.parent,)},
                    "write": {"writable_roots": (tmp_path,)},
                    "network": {"network": "allowed"},
                    "denial": {"denied_roots": ()},
                }[mode])
                bound = replace(bound, execution_profile=changed)
                observed = changed
            with pytest.raises(PermissionError):
                bound.require_current(attempt, current_execution_profile=observed)
        finally:
            owner.dispose()

    asyncio.run(scenario())


def test_resume_execution_scope_request_rejects_unbounded_scope_bytes(tmp_path):
    attempt = CodingActivationAttemptV1(
        attempt_id="attempt-1", request_id="input-1", session_id="session-1",
        original_leaf_id="leaf-1", ancestry_digest="a" * 64,
        plan_fingerprint="b" * 64, epoch_fingerprint="c" * 64, subject_digest="d" * 64,
    )
    root = tmp_path
    for _ in range(6):
        root /= "x" * 100
    profile = EffectiveExecutionProfile(readable_roots=tuple(root / str(index) for index in range(64)))
    with pytest.raises(ValueError, match="byte budget"):
        coding_resume_permission_request(
            attempt, actor_id="root", expansion_codes=("authority.unknown",), execution_profile=profile,
        )


@pytest.mark.parametrize("mode", [
    "current", "actor", "scope", "subject", "candidate", "plan", "leaf", "session", "ancestry",
])
def test_permission_confirmation_is_bound_to_current_native_action(mode):
    async def scenario():
        attempt = CodingActivationAttemptV1(
            attempt_id="attempt-1", request_id="input-1", session_id="session-1",
            original_leaf_id="leaf-1", ancestry_digest="a" * 64,
            plan_fingerprint="b" * 64, epoch_fingerprint="c" * 64, subject_digest="d" * 64,
        )
        owner = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
        expansion = ("authority.unknown", "workspace.write")
        native_request = coding_resume_permission_request(attempt, actor_id="actor-1", expansion_codes=expansion)

        async def present(payload):
            assert payload["policy_code"] == "resume_permission_expansion"
            assert payload["arguments"]["permissionExpansion"] == list(expansion)
            assert await owner.handle_result(payload["action_id"], outcome="allow_once")

        owner.set_request_presenter(present)
        try:
            fact = await owner.confirm(native_request)
            assert fact is not None
            bound = CodingResumePermissionConfirmation(attempt, "actor-1", expansion, owner, fact)
            bound.require_current(attempt)
            if mode == "actor":
                bound = replace(bound, actor_id="actor-2")
            elif mode == "scope":
                bound = replace(bound, expansion_codes=("full_access",))
            elif mode != "current":
                field, value = {
                    "subject": ("subject_digest", "e" * 64),
                    "candidate": ("epoch_fingerprint", "e" * 64),
                    "plan": ("plan_fingerprint", "e" * 64),
                    "leaf": ("original_leaf_id", "leaf-2"),
                    "session": ("session_id", "session-2"),
                    "ancestry": ("ancestry_digest", "e" * 64),
                }[mode]
                attempt = replace(attempt, **{field: value})
                # Even rebinding the data wrapper cannot widen the native fact.
                bound = replace(bound, attempt=attempt)
            if mode != "current":
                with pytest.raises(PermissionError):
                    bound.require_current(attempt)
            else:
                owner.release_confirmation(fact)
                with pytest.raises(PermissionError):
                    bound.require_current(attempt)
        finally:
            owner.dispose()

    asyncio.run(scenario())
