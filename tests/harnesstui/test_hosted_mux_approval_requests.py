from __future__ import annotations

import asyncio

import pytest

from loushang.appserver.protocol import AckV1, AppErrorCodeV1, AppServiceError
from loushang.tui import RenderConstraints
from loushang.tui.input import InputEvent

from .test_hosted_mux_profile import _Client
from .test_hosted_mux_requests import send, settle
from .test_hosted_mux_shell import _shell


def present(shell):
    shell.handle(InputEvent(kind="key", key="f2"))
    shell.screen.render(RenderConstraints(width=100, max_height=24))
    assert shell.screen.approval_presented()
    shell.handle(InputEvent(kind="key", key="escape"))


@pytest.mark.parametrize("command", ["/approve", "/deny"])
@pytest.mark.parametrize("change", [
    "tab", "tab_aba", "refresh", "attachment", "generation", "member", "session",
    "interaction", "interaction_text", "request", "approval", "snapshot", "membership",
])
def test_late_approval_failure_cannot_change_replaced_view_or_new_request(command, change):
    async def scenario():
        client = _Client()
        entered, release = asyncio.Event(), asyncio.Event()
        requests, cancelled = [], []

        async def respond(request):
            requests.append(request)
            if len(requests) > 1:
                return AckV1()
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.append(request)
                raise
            raise AppServiceError(AppErrorCodeV1.SERVICE_CLOSED)

        client.respond_interaction = respond
        shell = _shell(client)
        await shell.start()
        try:
            window = shell.state.active_window
            window.pending_interaction_id = "question-1"
            window.pending_interaction_text = "Current action"
            if command == "/approve":
                present(shell)
            send(shell, command)
            async with asyncio.timeout(2):
                await entered.wait()
            assert tuple(shell._actions._tasks.values()) == (True,)
            assert len(requests) == 1
            assert requests[0].interaction_id == "question-1"
            if change in {"tab", "tab_aba"}:
                shell.handle(InputEvent(kind="key", key="tab"))
                if change == "tab_aba":
                    shell.handle(InputEvent(kind="key", key="tab"))
            elif change == "refresh":
                await shell._controller.refresh_snapshot()
                shell._sync_editor()
            elif change == "attachment":
                shell.state.attachment_id = "replacement"
            elif change == "generation":
                shell.state.controller_generation += 1
            elif change == "member":
                window.member_id = "replacement"
            elif change == "session":
                window.session_id = "replacement"
            elif change == "interaction":
                window.pending_interaction_id = "question-2"
            elif change == "interaction_text":
                window.pending_interaction_text = "Changed action"
            elif change == "request":
                send(shell, "new request")
            elif change == "approval":
                send(shell, "/deny")
            elif change == "snapshot":
                shell.state.snapshot_required = True
            else:
                shell._membership_pending = True
            assert not cancelled and not release.is_set()
            shell.notice = "current view notice"
            release.set()
            await settle(shell)
            assert shell.notice == "current view notice"
            assert not shell.exit_requested and shell.exit_code == 0
            assert len(requests) == (2 if change == "approval" else 1)
            assert not cancelled
            if change == "request":
                assert window.request_presentation.state == "acknowledged"
        finally:
            release.set()
            shell._membership_pending = False
            await shell.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["ack", "failure", "invalid_ack", "service_closed"])
def test_current_approval_response_keeps_safe_failure_and_never_replays(outcome):
    async def scenario():
        client, requests = _Client(), []

        async def respond(request):
            requests.append(request)
            if outcome == "failure":
                raise RuntimeError("private response error")
            if outcome == "invalid_ack":
                return None
            if outcome == "service_closed":
                raise AppServiceError(AppErrorCodeV1.SERVICE_CLOSED)
            return AckV1()

        client.respond_interaction = respond
        shell = _shell(client)
        await shell.start()
        try:
            shell.state.active_window.pending_interaction_id = "question"
            before = shell.notice
            send(shell, "/deny")
            await settle(shell)
            expected = (before if outcome == "ack" else
                        "service_closed; outcome unknown, no retry" if outcome == "service_closed" else
                        "action_failed; outcome unknown, no retry")
            assert shell.notice == expected
            assert shell.exit_requested == (outcome == "service_closed")
            await shell.poll()
            assert len(requests) == 1
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_close_cancels_only_local_approval_waiter_not_accepted_work():
    async def scenario():
        client = _Client()
        accepted, release = asyncio.Event(), asyncio.Event()
        completed, requests, remote_tasks = [], [], []

        async def remote_work():
            await release.wait()
            completed.append("responded")
            return AckV1()

        async def respond(request):
            requests.append(request)
            task = asyncio.create_task(remote_work())
            remote_tasks.append(task)
            accepted.set()
            # Model the existing server's ownership after accepting the RPC.
            return await asyncio.shield(task)

        client.respond_interaction = respond
        shell = _shell(client)
        await shell.start()
        try:
            shell.state.active_window.pending_interaction_id = "question"
            send(shell, "/deny")
            async with asyncio.timeout(2):
                await accepted.wait()
                await shell.close()
            assert not remote_tasks[0].done()
            assert len(requests) == 1 and shell.pending_actions == 0
            assert [name for name, _ in client.calls] == ["attach", "detach"]
            assert "unknown" not in shell.notice
            release.set()
            await remote_tasks[0]
            assert completed == ["responded"]
        finally:
            release.set()
            await asyncio.gather(*remote_tasks)
            await shell.close()

    asyncio.run(scenario())


def test_rejected_approval_publication_preserves_request_generation_and_draft(monkeypatch):
    async def scenario():
        client = _Client()
        shell = _shell(client)
        await shell.start()
        try:
            shell.state.active_window.pending_interaction_id = "question"
            serial = shell._request_serial

            def reject(*args, **kwargs):
                raise ValueError("action_queue_full")

            monkeypatch.setattr(shell._actions, "submit", reject)
            send(shell, "/deny")
            assert shell.notice == "action_queue_full"
            assert shell._request_serial == serial
            assert shell.screen.composer.value == shell.state.active_window.draft == "/deny "
            assert shell.pending_actions == 0
            assert [name for name, _ in client.calls] == ["attach"]
        finally:
            await shell.close()

    asyncio.run(scenario())
