from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from loushang.appserver.execution.model import (
    ExecutionErrorCodeV1,
    ExecutionOutcomeV1,
    ExecutionRecordV1,
    ExecutionServiceErrorV1,
    ExecutionStateV1,
    ExecutionStatusV1,
)
from loushang.appserver.execution.recovery import (
    PendingSubmissionV1,
    SubmissionDeliveryV1,
    SubmissionRecoveryV1,
)
from loushang.appserver.framing import AppConnectionClosedError
from loushang.appserver.protocol import InvalidAppMessageError
from tests.appservice.test_execution_guard import scenario
from tests.appservice.test_execution_snapshot import IDENTITY

from .test_execution_protocol import CONTROL


class Client:
    def __init__(self):
        self.service_instance_id = "instance"
        self.calls = []
        self.record = None
        self.drop_response = False
        self.before_response = lambda: None

    async def submit_execution(self, control, instance, submission, text):
        self.calls.append(("submit", instance, submission, text))
        if self.record is None:
            self.record = ExecutionRecordV1(instance, IDENTITY, submission,
                                            ExecutionStateV1("execution", ExecutionStatusV1.ACCEPTED, 1))
        self.before_response()
        if self.drop_response:
            raise AppConnectionClosedError()
        return self.record

    async def find_execution_by_submission(self, control, instance, submission):
        self.calls.append(("find", instance, submission))
        return self.record


def recovery():
    return SubmissionRecoveryV1(PendingSubmissionV1("instance", IDENTITY, "submission", " exact text "))


@scenario
async def test_response_loss_recovers_by_original_submission_without_replay():
    state, client = recovery(), Client()
    client.drop_response = True
    with pytest.raises(AppConnectionClosedError):
        await state.submit(client, CONTROL)
    assert state.delivery is SubmissionDeliveryV1.UNKNOWN
    await state.recover(client, CONTROL)
    assert state.delivery is SubmissionDeliveryV1.KNOWN
    assert [call[0] for call in client.calls] == ["submit", "find"]
    client.drop_response = False
    await state.submit(client, CONTROL)
    assert client.calls[-1] == client.calls[0]


@scenario
async def test_racing_lookup_miss_requires_explicit_retry_with_same_content():
    state, client = recovery(), Client()
    await state.recover(client, CONTROL)
    assert state.delivery is SubmissionDeliveryV1.NOT_FOUND
    assert client.calls == [("find", "instance", "submission")]
    await state.submit(client, CONTROL)
    assert client.calls[-1] == ("submit", "instance", "submission", " exact text ")


@scenario
async def test_instance_change_never_sends_or_falls_back_to_old_start():
    state, client = recovery(), Client()
    client.service_instance_id = "new-instance"
    await state.recover(client, CONTROL)
    await state.submit(client, CONTROL)
    assert state.delivery is SubmissionDeliveryV1.INSTANCE_CHANGED
    assert not client.calls
    assert state.pending.text == " exact text "


@scenario
async def test_events_before_response_and_late_accepted_response_do_not_regress_status():
    state, client = recovery(), Client()
    terminal = ExecutionStateV1("execution", ExecutionStatusV1.SUCCEEDED, 3,
                                outcome=ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED))
    client.before_response = lambda: state.observe(terminal)
    await state.submit(client, CONTROL)
    assert state.record.state == terminal
    state.observe(replace(terminal, revision=2))
    assert state.record.state == terminal
    await state.recover(client, CONTROL)
    assert state.record.state == terminal


@scenario
async def test_cancelled_submit_is_unknown_and_keeps_original_intent():
    state, client = recovery(), Client()

    def cancelled():
        raise asyncio.CancelledError()

    client.before_response = cancelled
    with pytest.raises(asyncio.CancelledError):
        await state.submit(client, CONTROL)
    assert state.delivery is SubmissionDeliveryV1.UNKNOWN
    await state.recover(client, CONTROL)
    assert state.delivery is SubmissionDeliveryV1.KNOWN


@scenario
async def test_conflicting_duplicate_revision_requires_recovery_instead_of_overwrite():
    state, client = recovery(), Client()
    await state.submit(client, CONTROL)
    with pytest.raises(InvalidAppMessageError):
        state.observe(replace(state.record.state, status=ExecutionStatusV1.RUNNING))
    assert state.delivery is SubmissionDeliveryV1.UNKNOWN
    assert state.record.state.status is ExecutionStatusV1.ACCEPTED


@scenario
async def test_instance_replacement_during_lookup_preserves_original_intent():
    state, client = recovery(), Client()

    async def replaced(*args):
        raise ExecutionServiceErrorV1(ExecutionErrorCodeV1.INSTANCE_CHANGED)

    client.find_execution_by_submission = replaced
    with pytest.raises(ExecutionServiceErrorV1):
        await state.recover(client, CONTROL)
    assert state.delivery is SubmissionDeliveryV1.INSTANCE_CHANGED
    assert state.pending == recovery().pending
    assert not client.calls
