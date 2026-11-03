from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.appserver.execution.codec import (
    decode_call,
    decode_execution_hello,
    decode_response,
    encode_call,
    encode_response,
    execution_hello,
)
from loushang.appserver.execution.model import (
    ExecutionCallV1,
    ExecutionContentEventV1,
    ExecutionErrorCodeV1,
    ExecutionEventsV1,
    ExecutionFailureV1,
    ExecutionObservationV1,
    ExecutionOperationV1,
    ExecutionOutcomeV1,
    ExecutionRecordV1,
    ExecutionResponseV1,
    ExecutionSessionSnapshotV1,
    ExecutionSessionViewV1,
    ExecutionSourceSnapshotV1,
    ExecutionStateV1,
    ExecutionStatusV1,
    ExecutionUpdateV1,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppFailureV1,
    InvalidAppMessageError,
    SessionEventKindV1,
    SessionEventV1,
    SessionSnapshotRequestV1,
    SessionSnapshotV1,
    SessionSubmissionModeV1,
)
from loushang.appserver.resume_model import (
    ResumeInputLookupQueryV1,
    ResumeInputLookupResultV1,
)
from tests.appservice.test_execution_snapshot import IDENTITY

CONTROL = SessionSnapshotRequestV1("attachment", 1, "member")


@pytest.mark.parametrize("operation", list(ExecutionOperationV1))
def test_closed_execution_call_round_trip(operation):
    call = ExecutionCallV1(
        "1", operation, CONTROL, "instance",
        submission_id="submission" if operation in {ExecutionOperationV1.SUBMIT, ExecutionOperationV1.FIND} else None,
        execution_id="execution" if operation in {ExecutionOperationV1.GET, ExecutionOperationV1.INTERRUPT} else None,
        text="没有输出的命令" if operation is ExecutionOperationV1.SUBMIT else None,
        resume_query=ResumeInputLookupQueryV1("input-1", "a" * 64)
        if operation is ExecutionOperationV1.RESUME_INPUT_LOOKUP else None,
    )
    assert decode_call(encode_call(call)) == call
    raw = json.loads(encode_call(call))
    raw["payload"]["unspecified"] = True
    with pytest.raises(InvalidAppMessageError):
        decode_call(json.dumps(raw).encode())


def test_record_snapshot_and_event_round_trip():
    outcome = ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED)
    state = ExecutionStateV1("execution", outcome.status, 3, outcome=outcome)
    observation = ExecutionObservationV1("execution", state.status, 0)
    snapshot = ExecutionSessionSnapshotV1(
        "instance", ExecutionSourceSnapshotV1(
            SessionSnapshotV1(IDENTITY, "title", 0, 0, False, ()), observation,
        ), ExecutionSessionViewV1(IDENTITY, 3, observation, latest_terminal=state),
    )
    for result in (
        ExecutionRecordV1("instance", IDENTITY, "submission", state), snapshot,
        ExecutionEventsV1((
            ExecutionUpdateV1(3, state),
            ExecutionContentEventV1(SessionEventV1(IDENTITY.session_id, 1, SessionEventKindV1.STATUS, "text"), "execution"),
        )),
        ExecutionFailureV1(ExecutionErrorCodeV1.INSTANCE_CHANGED),
        AppFailureV1(AppErrorCodeV1.STALE_ATTACHMENT), None,
        ResumeInputLookupResultV1("input-1", "record-1", "committed"),
    ):
        response = ExecutionResponseV1("1", result)
        assert decode_response(encode_response(response)) == response


def test_execution_snapshot_preserves_optional_submission_mode():
    observation = ExecutionObservationV1()
    source = ExecutionSourceSnapshotV1(
        SessionSnapshotV1(
            IDENTITY,
            "title",
            0,
            0,
            False,
            (),
            SessionSubmissionModeV1.EXECUTION,
        ),
        observation,
    )
    snapshot = ExecutionSessionSnapshotV1(
        "instance", source, ExecutionSessionViewV1(IDENTITY, 0, observation)
    )
    encoded = encode_response(ExecutionResponseV1("1", snapshot))
    assert json.loads(encoded)["result"]["source"]["source"]["submissionMode"] == (
        "execution"
    )
    assert decode_response(encoded).result == snapshot
    noncanonical = json.loads(encoded)
    noncanonical["result"]["source"]["source"]["submissionMode"] = "legacy"
    with pytest.raises(InvalidAppMessageError):
        decode_response(json.dumps(noncanonical).encode())


@pytest.mark.parametrize("mutation", ["bool_counter", "missing_outcome", "unknown_status", "extra_field"])
def test_malformed_state_is_rejected(mutation):
    state = ExecutionStateV1("execution", ExecutionStatusV1.ACCEPTED, 1)
    raw = json.loads(encode_response(ExecutionResponseV1("1", ExecutionRecordV1("instance", IDENTITY, "submission", state))))
    malformed = raw["result"]["state"]
    if mutation == "bool_counter":
        malformed["revision"] = True
    elif mutation == "missing_outcome":
        malformed["status"] = "succeeded"
    elif mutation == "unknown_status":
        malformed["status"] = "idle"
    else:
        malformed["binding"] = "must not be serialized"
    with pytest.raises(InvalidAppMessageError):
        decode_response(json.dumps(raw).encode())


def test_hello_exposes_exact_instance_and_retention_guarantees():
    hello = execution_hello("local-detachable-execution/v1", "instance")
    assert decode_execution_hello(hello, "local-detachable-execution/v1") == "instance"
    assert json.loads(hello)["restartRecovery"] is False
    with pytest.raises(InvalidAppMessageError):
        decode_execution_hello(hello, "local-detachable/v1")


def test_duplicate_keys_and_invalid_call_fields_are_rejected():
    call = ExecutionCallV1("1", ExecutionOperationV1.SUBMIT, CONTROL, "instance", "submission", text="text")
    with pytest.raises(ValueError):
        replace(call, execution_id="execution")
    encoded = encode_call(call)
    with pytest.raises(InvalidAppMessageError):
        decode_call(encoded.replace(b'"requestId":"1"', b'"requestId":"1","requestId":"2"'))


def test_native_client_handoff_goldens_keep_their_closed_wire_shapes():
    fixtures = json.loads((Path(__file__).parent / "fixtures/execution_v1.json").read_text())
    for name, value in fixtures.items():
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        if name == "hello":
            assert decode_execution_hello(encoded, "local-detachable-execution/v1") == "instance"
        elif name == "submit":
            assert encode_call(decode_call(encoded)) == encoded
        else:
            assert encode_response(decode_response(encoded)) == encoded


@pytest.mark.parametrize("status", ["committed", "not_committed_verified", "unknown", "conflict"])
def test_resume_lookup_result_round_trip_has_closed_status(status):
    result = ResumeInputLookupResultV1("input-1", "record-1", status)
    encoded = encode_response(ExecutionResponseV1("1", result))
    assert decode_response(encoded).result == result
    raw = json.loads(encoded)
    raw["result"]["status"] = "absent_in_memory"
    with pytest.raises(InvalidAppMessageError):
        decode_response(json.dumps(raw).encode())
