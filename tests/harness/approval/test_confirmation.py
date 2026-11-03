from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from loushang.harness.approval import (
    ApprovalConfirmation,
    ApprovalGrantProposal,
    ApprovalRequest,
    ApprovalRequestCollisionError,
    DenyApprovalResolver,
    HeadlessApprovalResolver,
    InteractiveApprovalResolver,
)


def request(action_id="confirm-1", actor_id="root", *, grant=False):
    return ApprovalRequest(
        tool_name="resume", action_id=action_id, actor_id=actor_id,
        action_fingerprint="candidate-current",
        arguments={"session": "session-1", "leaf": "leaf-1", "scope": ["workspace.write"]},
        session_grant=ApprovalGrantProposal(
            capability="resume.current-authority",
            constraints=(("candidate", "candidate-current"), ("session", "session-1")),
            summary="Use this candidate's current permissions",
        ) if grant else None,
    )


@pytest.mark.parametrize("mode", [
    "once", "session", "release", "close", "actor", "actor_grants_revoked", "grant_revoked",
    "changed_candidate", "changed_scope", "changed_actor", "changed_leaf",
    "copy", "other_owner",
])
def test_confirmation_revalidates_native_interactive_fact_and_exact_request(mode):
    async def scenario():
        owner = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
        native_request = request(grant=mode in {"session", "grant_revoked"})
        presentations = []

        async def present(payload):
            presentations.append(payload)
            assert await owner.handle_result(
                payload["action_id"],
                outcome="allow_session" if native_request.session_grant else "allow_once",
            )

        owner.set_request_presenter(present)
        try:
            confirmation = await owner.confirm(native_request)
            assert isinstance(confirmation, ApprovalConfirmation)
            assert len(presentations) == 1
            owner.require_current_confirmation(confirmation, request=native_request)
            checked = native_request
            validator = owner
            if mode == "release":
                assert owner.release_confirmation(confirmation)
                assert not owner.release_confirmation(confirmation)
            elif mode == "close":
                owner.close_session()
                owner.open_session()
            elif mode == "actor":
                owner.cancel_actor("root")
            elif mode == "actor_grants_revoked":
                owner.revoke_actor_grants("root")
            elif mode == "grant_revoked":
                assert owner.revoke_grant(confirmation.decision.grant_id)
            elif mode == "changed_candidate":
                checked = replace(native_request, action_fingerprint="candidate-changed")
            elif mode == "changed_scope":
                checked = replace(native_request, arguments={**native_request.arguments, "scope": ["full_access"]})
            elif mode == "changed_actor":
                checked = replace(native_request, actor_id="other")
            elif mode == "changed_leaf":
                checked = replace(native_request, arguments={**native_request.arguments, "leaf": "leaf-2"})
            elif mode == "copy":
                confirmation = replace(confirmation)
            elif mode == "other_owner":
                validator = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
            if mode not in {"once", "session"}:
                with pytest.raises(PermissionError):
                    validator.require_current_confirmation(confirmation, request=checked)
            else:
                assert owner.release_confirmation(confirmation)
            if validator is not owner:
                validator.dispose()
        finally:
            owner.dispose()

    asyncio.run(scenario())


def test_confirmation_capacity_is_bounded_and_release_reclaims_a_slot():
    async def scenario():
        owner = InteractiveApprovalResolver(fallback=DenyApprovalResolver())

        async def present(payload):
            assert await owner.handle_result(payload["action_id"], outcome="allow_session")

        owner.set_request_presenter(present)
        try:
            seed = await owner.confirm(request(grant=True))
            assert seed is not None
            owner.release_confirmation(seed)
            facts = [await owner.confirm(request(f"candidate-{index}", grant=True)) for index in range(64)]
            assert all(fact is not None for fact in facts)
            with pytest.raises(RuntimeError, match="capacity"):
                await owner.confirm(request("overflow", grant=True))
            assert len(owner._confirmations) == 64
            assert owner.release_confirmation(facts[0])
            assert await owner.confirm(request("replacement", grant=True)) is not None
            assert len(owner._confirmations) == 64
            owner.close_session()
            assert not owner._confirmations
        finally:
            owner.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["allow_once", "allow_session"])
def test_coalesced_confirmation_requires_an_exact_retained_grant_for_other_action(outcome):
    async def scenario():
        owner = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
        entered = asyncio.Event()
        presentations = []

        async def present(payload):
            presentations.append(payload)
            entered.set()

        owner.set_request_presenter(present)
        tasks = [asyncio.create_task(owner.confirm(request(f"confirm-{index}", grant=True))) for index in range(2)]
        try:
            await entered.wait()
            assert set(owner._confirmation_requests) == {"confirm-0", "confirm-1"}
            assert len(presentations) == 1
            assert await owner.handle_result(presentations[0]["action_id"], outcome=outcome)
            first, second = await asyncio.gather(*tasks)
            assert first is not None
            owner.require_current_confirmation(first, request=first.request)
            if outcome == "allow_once":
                assert second is None
            else:
                assert second is not None
                assert first.decision.grant_id == second.decision.grant_id
                owner.require_current_confirmation(second, request=second.request)
        finally:
            owner.dispose()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(scenario())


def test_headless_allow_cannot_issue_interactive_confirmation():
    async def scenario():
        owner = InteractiveApprovalResolver(fallback=HeadlessApprovalResolver(mode="allow"))
        try:
            assert (await owner.resolve(request("ordinary"))).disposition == "allow"
            assert await owner.confirm(request()) is None
            assert not owner._confirmations
            assert not owner._confirmation_requests
        finally:
            owner.dispose()

    asyncio.run(scenario())


def test_existing_exact_native_grant_is_reused_and_still_revocable():
    async def scenario():
        owner = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
        presentations = []

        async def present(payload):
            presentations.append(payload)
            assert await owner.handle_result(payload["action_id"], outcome="allow_session")

        owner.set_request_presenter(present)
        try:
            initial = await owner.confirm(request(grant=True))
            assert initial is not None
            owner.release_confirmation(initial)
            current = request("confirm-2", grant=True)
            reused = await owner.confirm(current)
            assert reused is not None
            assert len(presentations) == 1
            owner.require_current_confirmation(reused, request=current)
            assert owner.revoke_grant(initial.decision.grant_id)
            with pytest.raises(PermissionError):
                owner.require_current_confirmation(reused, request=current)
        finally:
            owner.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["cancelled", "denied", "actor_before_delivery", "close_before_delivery"])
def test_confirmation_failure_does_not_leave_a_fact(mode):
    async def scenario():
        owner = InteractiveApprovalResolver(fallback=DenyApprovalResolver())
        entered = asyncio.Event()

        async def present(payload):
            entered.set()
            if mode == "denied":
                assert await owner.handle_result(payload["action_id"], outcome="deny")
            elif mode in {"actor_before_delivery", "close_before_delivery"}:
                assert await owner.handle_result(payload["action_id"], outcome="allow_once")
                if mode == "actor_before_delivery":
                    owner.cancel_actor("root")
                else:
                    owner.close_session()
                    owner.open_session()
                with pytest.raises(ApprovalRequestCollisionError):
                    await owner.confirm(request())

        owner.set_request_presenter(present)
        task = asyncio.create_task(owner.confirm(request()))
        try:
            await entered.wait()
            if mode == "cancelled":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                assert await task is None
            assert not owner._confirmations
            assert not owner._confirmation_requests
        finally:
            owner.dispose()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
