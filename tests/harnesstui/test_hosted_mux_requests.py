from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from loushang.appserver.execution.model import (
    ExecutionRecordV1,
    ExecutionStateV1,
    ExecutionStatusV1,
)
from loushang.appserver.protocol import (
    AckV1,
    MuxSelectorV1,
    SessionScopeV1,
    SessionSubmissionModeV1,
)
from loushang.harnesstui.mux.shell import HostedMuxShellV1
from loushang.tui import RenderConstraints
from loushang.tui.input import InputEvent

from .test_hosted_mux_profile import FINGERPRINT, _Client
from .test_hosted_mux_shell import _shell


async def settle(shell):
    async with asyncio.timeout(2):
        while shell.pending_actions:
            await asyncio.sleep(0)


def send(shell, text):
    shell.handle(InputEvent(kind="text", text=text))
    shell.handle(InputEvent(kind="key", key="enter"))


class _ExecutionClient:
    service_instance_id = "instance"

    def __init__(self, identity, *, fail_once=False, wait=None):
        self.identity = identity
        self.fail_once = fail_once
        self.wait = wait
        self.calls = []

    async def submit_execution(self, control, instance, submission, text):
        self.calls.append((control, instance, submission, text))
        if self.wait is not None:
            await self.wait.wait()
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("private transport failure")
        return ExecutionRecordV1(
            instance,
            self.identity,
            submission,
            ExecutionStateV1("execution", ExecutionStatusV1.ACCEPTED, 1),
        )


def _execution_shell(client, execution, *, deferred=True):
    if deferred:
        client.attachments = [
            replace(
                attachment,
                sessions=tuple(
                    replace(
                        item,
                        snapshot=replace(
                            item.snapshot,
                            submission_mode=SessionSubmissionModeV1.EXECUTION,
                        ),
                    )
                    for item in attachment.sessions
                ),
            )
            for attachment in client.attachments
        ]

        async def unavailable(request):
            raise AssertionError("execution submission must not probe legacy start")

        client.start_turn = unavailable
    return HostedMuxShellV1(
        client,
        selector=MuxSelectorV1(name="dev"),
        product_id="coding",
        scopes=(
            (SessionScopeV1.CWD, FINGERPRINT),
            (SessionScopeV1.USER_HOME, FINGERPRINT),
        ),
        execution_client=execution,
    )


def test_execution_submission_clears_exact_draft_only_after_stable_acceptance():
    async def scenario():
        client = _Client()
        identity = client.attachments[0].sessions[0].member.session
        release = asyncio.Event()
        execution = _ExecutionClient(identity, wait=release)
        shell = _execution_shell(client, execution)
        await shell.start()
        try:
            send(shell, "resume exactly once")
            window = shell.state.active_window
            assert window.draft == shell.screen.composer.value == "resume exactly once"
            assert window.request_presentation.state == "pending"
            release.set()
            await settle(shell)
            assert window.draft == shell.screen.composer.value == ""
            assert window.request_presentation.state == "acknowledged"
            assert len(execution.calls) == 1
            control, instance, submission, text = execution.calls[0]
            assert (control.attachment_id, control.member_id) == (
                "attachment-1",
                "member-1",
            )
            assert instance == "instance" and len(submission) == 32
            assert text == "resume exactly once"
            assert [name for name, _ in client.calls] == ["attach"]
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_execution_capability_preserves_ordinary_legacy_submission():
    async def scenario():
        client = _Client()
        identity = client.attachments[0].sessions[0].member.session
        execution = _ExecutionClient(identity)
        entered, release = asyncio.Event(), asyncio.Event()

        async def start(request):
            client.calls.append(("start", request))
            entered.set()
            await release.wait()
            return AckV1()

        client.start_turn = start
        shell = _execution_shell(client, execution, deferred=False)
        await shell.start()
        try:
            send(shell, "ordinary turn")
            await entered.wait()
            window = shell.state.active_window
            assert window.draft == shell.screen.composer.value == ""
            assert window.request_presentation.state == "pending"
            release.set()
            await settle(shell)
            assert window.request_presentation.state == "acknowledged"
            assert execution.calls == []
            assert [name for name, _ in client.calls] == ["attach", "start"]
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_execution_unknown_keeps_draft_and_explicit_retry_reuses_submission_id():
    async def scenario():
        client = _Client()
        identity = client.attachments[0].sessions[0].member.session
        execution = _ExecutionClient(identity, fail_once=True)
        shell = _execution_shell(client, execution)
        await shell.start()
        try:
            send(shell, "retry same input")
            await settle(shell)
            window = shell.state.active_window
            assert window.draft == shell.screen.composer.value == "retry same input"
            assert window.request_presentation.state == "unknown"
            shell.handle(InputEvent(kind="key", key="enter"))
            await settle(shell)
            assert window.draft == shell.screen.composer.value == ""
            assert window.request_presentation.state == "acknowledged"
            assert len(execution.calls) == 2
            assert execution.calls[0][2] == execution.calls[1][2]
            assert execution.calls[0][3] == execution.calls[1][3] == "retry same input"
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_execution_acceptance_never_erases_a_newer_draft():
    async def scenario():
        client = _Client()
        identity = client.attachments[0].sessions[0].member.session
        release = asyncio.Event()
        execution = _ExecutionClient(identity, wait=release)
        shell = _execution_shell(client, execution)
        await shell.start()
        try:
            send(shell, "submitted")
            shell.handle(InputEvent(kind="text", text=" plus newer text"))
            release.set()
            await settle(shell)
            window = shell.state.active_window
            assert window.draft == shell.screen.composer.value == (
                "submitted plus newer text"
            )
            assert window.request_presentation.state == "acknowledged"
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_ack_clears_pending_without_claiming_execution_completed():
    async def scenario():
        shell = _shell(_Client())
        await shell.start()
        try:
            window = shell.state.active_window
            window.running = True
            send(shell, "prompt")
            assert window.request_presentation.state == "pending"
            await settle(shell)
            assert window.request_presentation.state == "acknowledged"
            assert window.running
            result = shell.screen.render(RenderConstraints(width=160, max_height=24))
            text = "\n".join(line.text for line in result.lines)
            assert "request_acknowledged" in text and "request_pending" not in text
            assert "running" in text
        finally:
            await shell.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("old_fails", [False, True])
def test_late_old_result_does_not_overwrite_new_request(old_fails):
    async def scenario():
        client = _Client()
        entered = [asyncio.Event(), asyncio.Event()]
        release = [asyncio.Event(), asyncio.Event()]

        async def operation(request):
            index = int(request.text)
            entered[index].set()
            await release[index].wait()
            if index == 0 and old_fails:
                raise RuntimeError("private old failure")
            return AckV1()

        client.start_turn = operation
        shell = _shell(client)
        await shell.start()
        try:
            send(shell, "0")
            await entered[0].wait()
            send(shell, "1")
            await entered[1].wait()
            current = shell.state.active_window.request_presentation
            release[0].set()
            async with asyncio.timeout(2):
                while shell.pending_actions != 1:
                    await asyncio.sleep(0)
            assert shell.state.active_window.request_presentation is current
            assert "unknown" not in shell.notice
            release[1].set()
            await settle(shell)
            assert shell.state.active_window.request_presentation.state == "acknowledged"
        finally:
            await shell.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("refresh", [False, True])
def test_reply_is_bound_to_original_attachment_and_member(refresh):
    async def scenario():
        client = _Client()
        entered, release = asyncio.Event(), asyncio.Event()

        async def operation(request):
            entered.set()
            await release.wait()
            return AckV1()

        client.start_turn = operation
        shell = _shell(client)
        await shell.start()
        try:
            send(shell, "prompt")
            await entered.wait()
            old = shell.state.active_window
            if refresh:
                await shell._controller.refresh_snapshot()
                shell._sync_editor()
            else:
                shell.handle(InputEvent(kind="key", key="tab"))
            assert shell.state.active_window.request_presentation is None
            release.set()
            await settle(shell)
            assert shell.state.active_window.request_presentation is None
            assert old.request_presentation.state == ("pending" if refresh else "acknowledged")
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_unconfirmed_result_is_not_cleared_by_idle_or_retried():
    async def scenario():
        client = _Client()
        calls = []

        async def operation(request):
            calls.append(request)
            raise RuntimeError("private transport failure")

        client.start_turn = operation
        shell = _shell(client)
        await shell.start()
        try:
            send(shell, "prompt")
            await settle(shell)
            window = shell.state.active_window
            assert not window.running and window.request_presentation.state == "unknown"
            await shell.poll()
            text = "\n".join(line.text for line in shell.screen.render(
                RenderConstraints(width=160, max_height=24)).lines)
            assert "result unconfirmed, no retry" in text and "private" not in text
            assert len(calls) == 1
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_task_publication_failure_does_not_publish_pending(monkeypatch):
    async def scenario():
        shell = _shell(_Client())
        await shell.start()

        def refused(*args, **kwargs):
            raise ValueError("action_queue_full")

        monkeypatch.setattr(shell._actions, "submit", refused)
        try:
            send(shell, "kept")
            assert shell.state.active_window.request_presentation is None
            assert shell.screen.composer.value == "kept"
            assert shell.notice == "action_queue_full"
        finally:
            await shell.close()

    asyncio.run(scenario())


def test_hosted_action_binding_rejects_attachments_before_wire():
    from loushang.harnesstui.conversation.control import ConversationTextAction
    from loushang.harnesstui.mux.conversation_binding import (
        HostedConversationActionBinding,
    )

    async def scenario():
        client = _Client()
        presented = []
        binding = HostedConversationActionBinding(client, attachment_id="attachment-1", generation=1,
            member_id="member-1", present=presented.append)
        with pytest.raises(ValueError, match="image_paste_unavailable"):
            await binding.submit(ConversationTextAction("prompt", attachments=(object(),)))
        assert client.calls == [] and presented == []

    asyncio.run(scenario())


def test_invalid_whitespace_prompt_is_rejected_before_task_and_keeps_draft():
    async def scenario():
        client = _Client()
        shell = _shell(client)
        await shell.start()
        try:
            send(shell, "   ")
            assert shell.pending_actions == 0
            assert shell.screen.composer.value == "   "
            assert shell.state.active_window.request_presentation is None
            assert [name for name, _ in client.calls] == ["attach"]
        finally:
            await shell.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["tab", "request", "refresh"])
@pytest.mark.parametrize("fails", [False, True])
def test_interrupt_response_uses_same_scoped_delivery_and_control_slot(change, fails):
    async def scenario():
        client = _Client()
        entered, release = asyncio.Event(), asyncio.Event()

        async def operation(request):
            entered.set()
            await release.wait()
            if fails:
                raise RuntimeError("private old interrupt failure")
            return AckV1()

        client.interrupt_turn = operation
        shell = _shell(client)
        await shell.start()
        try:
            old = shell.state.active_window
            old.running = True
            shell.handle(InputEvent(kind="key", key="ctrl+c"))
            await entered.wait()
            assert old.request_presentation.operation == "interrupt"
            assert old.request_presentation.state == "pending"
            assert tuple(shell._actions._tasks.values()) == (True,)
            if change == "tab":
                shell.handle(InputEvent(kind="key", key="tab"))
            elif change == "request":
                send(shell, "new")
            else:
                await shell._controller.refresh_snapshot()
                shell._sync_editor()
            release.set()
            await settle(shell)
            assert "unknown" not in shell.notice
            current = shell.state.active_window.request_presentation
            if change == "request":
                assert current.operation == "steer" and current.state == "acknowledged"
            else:
                assert current is None
            if change == "tab":
                assert old.request_presentation.state == ("unknown" if fails else "acknowledged")
            assert old.running  # Only authoritative execution events may change this.
        finally:
            await shell.close()

    asyncio.run(scenario())
